"""Compute occurrence_songs.probability natively from RDB evidence.

This began as Phase 1 of the RDB-native rewrite of
song_processing/song_occurrences.py's prediction_probability() function. It
now handles both direct current-year evidence and a historical evidence row
that already carries inherited_from_year. The latter uses the same decay and
speaker factor as inherit_song_probabilities_rdb.py. That separate script is
still responsible for creating inherited rows between distinct annual
occurrences; this script only fills NULL probabilities on rows that exist.

The safe default only fills rows whose probability is NULL. A guarded
``--recalculate-existing`` mode is available for an explicitly selected year;
it recomputes non-NULL rows only when accepted linked evidence supports the
calculation. This repairs stale or previously unrecognized direct evidence
without inventing probabilities for legacy rows that have no links.

Evidence normalization, per linked evidence_items row:
  - kind: evidence_items.evidence_type, mapped through KIND_BY_EVIDENCE_TYPE
    (generic/unknown types use the reviewed occurrence_songs.evidence_status
    when it is announced/observed, otherwise the conservative "hint").
  - reliability: occurrence_song_evidence_links.confidence. Every writer of
    this table (build_master_rdb.py's build_from_song_occurrences,
    apply_youtube_setlist_occurrences_rdb.py) already stores a 0-1
    reliability value there, so this is reused rather than re-derived from
    raw_json (which only the pre-RDB-native evidence rows still carry).
  - role: legacy evidence_role(observed_at, event_start, kind) -- string
    comparison of ISO8601-ish date/datetime strings, which sorts correctly
    because both event_start (event_occurrences.date_start) and
    evidence_items.observed_at are zero-padded ISO dates/datetimes.

Default mode writes only to a copied SQLite DB. Production writes require
--apply and the confirmation phrase.
"""

import argparse
import json
import shutil
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import audit_master_rdb
from master_rdb.master_db import (
    MASTER_DB,
    connect_existing,
    now_utc,
    refresh_manifest_database_state,
    table_counts,
)


DATA = Path("data")
OUT_DB = DATA / "song_probability_calibration_dry_run.sqlite"
OUT_JSON = DATA / "song_probability_calibration_report.json"
OUT_MD = DATA / "song_probability_calibration_report.md"
BACKUP_DIR = DATA / "backups"
CONFIRM_PHRASE = "APPLY SONG PROBABILITY CALIBRATION RDB"
SCRIPT_NAME = "calibrate_song_probabilities_rdb.py"

KIND_BY_EVIDENCE_TYPE = {
    "observed": "observed",
    "hint": "hint",
    "announced": "announced",
    "firsthand_attendance": "observed",
    "historical_occurrence_video": "observed",
    "historical_occurrence_report": "observed",
    # Official/current-year setlist images are announcements, not generic
    # hints. Missing this mapping left poster-backed rows uncalibrated.
    "poster_post": "announced",
}
DECAY_RATE = 0.75

BASIS_LABEL = {
    "current_announced": "今年告知",
    "current_hint": "今年ヒント",
    "current_observed": "今年実測",
}


def rows(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def scalar(conn, query, params=()):
    return conn.execute(query, params).fetchone()[0]


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_db(source, out_db):
    source = Path(source)
    out_db = Path(out_db)
    if not source.exists():
        raise FileNotFoundError(source)
    out_db.parent.mkdir(parents=True, exist_ok=True)
    if out_db.exists():
        out_db.unlink()
    shutil.copy2(source, out_db)


def backup_db(source, now):
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(source)
    stamp = now.replace("-", "").replace(":", "").replace("+00:00", "Z")
    backup = BACKUP_DIR / f"{source.stem}.{stamp}{source.suffix}.bak"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup)
    return backup


def validate_apply_request(args):
    if args.recalculate_existing and not (args.target_year or args.occurrence_id):
        raise ValueError("--recalculate-existing requires --target-year or --occurrence-id")
    if not args.apply:
        return
    if args.confirm != CONFIRM_PHRASE:
        raise ValueError(f"--apply requires --confirm '{CONFIRM_PHRASE}'")
    if Path(args.out_db) == Path(args.master_db):
        raise ValueError("--out-db must not equal --master-db")


def normalize_kind(evidence_type, evidence_status=None):
    """Normalize source type, using the reviewed song-row status as fallback."""
    kind = KIND_BY_EVIDENCE_TYPE.get(evidence_type, "hint")
    if kind == "hint" and evidence_status in {"announced", "observed"}:
        return evidence_status
    return kind


def evidence_role(observed_at, event_start, kind):
    if observed_at and event_start:
        return "prediction" if str(observed_at) < str(event_start) else "result"
    if kind == "observed":
        return "result"
    return "prediction"


def noisy_or(reliabilities):
    miss = 1.0
    for reliability in reliabilities:
        miss *= 1.0 - max(0.0, min(1.0, float(reliability)))
    return 1.0 - miss


def speaker_key(value):
    value = str(value or "").strip()
    return value or "unknown"


def compute_probability(evidence_rows):
    """Port of prediction_probability()'s current-evidence branches.

    Returns None when the linked evidence gives no basis for a probability
    in this pass's scope (would fall through to the past_evidence/prior
    branches of the legacy algorithm, which this pass does not implement).
    """
    current_predictions = [ev for ev in evidence_rows if ev["role"] != "result"]
    if current_predictions:
        probability = round(noisy_or(ev["reliability"] for ev in current_predictions) * 100)
        kinds = {ev["kind"] for ev in current_predictions}
        speakers = {speaker_key(ev["speaker"]) for ev in current_predictions}
        basis = "current_announced" if "announced" in kinds else "current_hint"
        return {
            "probability": max(1, min(99, probability)),
            "basis": basis,
            "basis_label": BASIS_LABEL[basis],
            "speaker_count": len(speakers),
            "evidence_used": len(current_predictions),
        }
    if any(ev["kind"] == "observed" for ev in evidence_rows):
        probability = round(noisy_or(ev["reliability"] for ev in evidence_rows) * 100)
        speakers = {speaker_key(ev["speaker"]) for ev in evidence_rows}
        return {
            "probability": max(1, min(99, probability)),
            "basis": "current_observed",
            "basis_label": BASIS_LABEL["current_observed"],
            "speaker_count": len(speakers),
            "evidence_used": len(evidence_rows),
        }
    return None


def _historical_kind(evidence_rows):
    kinds = {ev["kind"] for ev in evidence_rows}
    return "announced" if "announced" in kinds else "observed" if "observed" in kinds else "hint"


def _historical_kind_label(kind):
    return BASIS_LABEL.get("current_" + kind, "過去実績").removeprefix("今年")


def compute_historical_probability(
    evidence_rows,
    target_year,
    source_year=None,
    *,
    annual_fallbacks=None,
):
    """Combine historical evidence by event year, then across event years.

    Evidence from one year is first combined with the existing noisy-or and
    distinct-speaker adjustment.  Each annual contribution then decays by
    0.75 per elapsed year.  Contributions from different event years are
    combined with noisy-or, so consecutive annual appearances raise the
    prediction without counting duplicate sources inside one year twice as
    separate recurrence evidence.

    ``source_year`` remains as the fallback for legacy evidence rows that do
    not yet carry detected_event_date/source_year themselves.
    """
    annual_fallbacks = annual_fallbacks or []
    if not evidence_rows and not annual_fallbacks:
        return None

    by_year = {}
    for evidence in evidence_rows:
        evidence_year = evidence.get("source_year")
        if evidence_year is None:
            evidence_year = source_year
        try:
            evidence_year = int(evidence_year)
        except (TypeError, ValueError):
            continue
        if evidence_year >= target_year:
            continue
        by_year.setdefault(evidence_year, []).append(evidence)
    fallback_by_year = {}
    for fallback in annual_fallbacks:
        try:
            fallback_year = int(fallback.get("source_year"))
            fallback_probability = float(fallback.get("probability"))
        except (TypeError, ValueError):
            continue
        if fallback_year >= target_year or fallback_probability <= 0:
            continue
        current = fallback_by_year.get(fallback_year)
        if current is None or fallback_probability > float(current.get("probability") or 0):
            fallback_by_year[fallback_year] = fallback

    evidence_years = set(by_year)
    fallback_years = set(fallback_by_year) - evidence_years
    source_years_available = evidence_years | fallback_years
    if not source_years_available:
        return None

    annual = []
    for evidence_year in sorted(source_years_available):
        annual_evidence = by_year.get(evidence_year, [])
        if annual_evidence:
            base = noisy_or(ev["reliability"] for ev in annual_evidence)
            annual_speakers = {speaker_key(ev["speaker"]) for ev in annual_evidence}
            speaker_count = len(annual_speakers)
            source_kind = _historical_kind(annual_evidence)
            evidence_used = len(annual_evidence)
        else:
            # Older imported setlists can have a reviewed event-year
            # probability but no per-source evidence link. Reuse that annual
            # score only as a conservative fallback, then apply the same
            # single/multi-source factor and year decay as native evidence.
            fallback = fallback_by_year[evidence_year]
            base = max(0.0, min(1.0, float(fallback["probability"]) / 100.0))
            speaker_count = max(1, int(fallback.get("source_count") or 1))
            source_kind = fallback.get("source_kind") or "hint"
            evidence_used = 0
        speaker_factor = min(1.0, 0.65 + 0.15 * max(1, speaker_count))
        contribution = base * (DECAY_RATE ** (target_year - evidence_year)) * speaker_factor
        annual.append(
            {
                "source_year": evidence_year,
                "probability": contribution,
                "source_kind": source_kind,
                "speaker_count": speaker_count,
                "evidence_used": evidence_used,
            }
        )

    probability = round(noisy_or(row["probability"] for row in annual) * 100)
    source_years = [row["source_year"] for row in annual]
    source_kinds = {row["source_kind"] for row in annual}
    source_kind = annual[-1]["source_kind"]
    if len(source_kinds) == 1:
        kind_label = _historical_kind_label(source_kind)
    else:
        kind_label = "実績"
    year_label = "・".join(str(year) for year in source_years)
    used_evidence = [evidence for annual_rows in by_year.values() for evidence in annual_rows]
    speakers = {speaker_key(ev["speaker"]) for ev in used_evidence}
    fallback_speaker_count = sum(
        row["speaker_count"] for row in annual if row["source_year"] in fallback_years
    )
    return {
        "probability": max(5, min(90, probability)),
        "basis": "past_evidence",
        "basis_label": f"{year_label}年{kind_label}",
        "speaker_count": len(speakers) + fallback_speaker_count,
        "evidence_used": sum(row["evidence_used"] for row in annual),
        "source_years": source_years,
        "source_kind": source_kind,
        "fallback_years": sorted(fallback_years),
        "annual_probabilities": [
            {
                **row,
                "probability": round(row["probability"] * 100),
            }
            for row in annual
        ],
    }


def calibrate(
    conn,
    now,
    occurrence_id=None,
    *,
    target_year=None,
    recalculate_existing=False,
):
    query = (
        "SELECT os.occurrence_song_id, os.occurrence_id, os.normalized_title, os.origin, "
        "os.inherited_from_year, os.notes, os.evidence_status, eo.event_year "
        "FROM occurrence_songs os JOIN event_occurrences eo ON eo.occurrence_id=os.occurrence_id "
        "WHERE 1=1"
    )
    params = []
    if not recalculate_existing:
        query += " AND os.probability IS NULL"
    if occurrence_id:
        query += " AND os.occurrence_id = ?"
        params.append(occurrence_id)
    if target_year is not None:
        query += " AND eo.event_year = ?"
        params.append(int(target_year))
    targets = rows(conn, query, tuple(params))
    updated = []
    skipped_no_current_evidence = []
    for target in targets:
        occurrence = conn.execute(
            "SELECT date_start FROM event_occurrences WHERE occurrence_id = ?",
            (target["occurrence_id"],),
        ).fetchone()
        event_start = occurrence[0] if occurrence else None

        evidence_rows = rows(
            conn,
            """
            SELECT e.evidence_type, e.observed_at, e.detected_event_date,
                   l.confidence AS reliability,
                   e.account_key, e.source_key
            FROM occurrence_song_evidence_links l
            JOIN evidence_items e ON e.evidence_id = l.evidence_id
            WHERE l.occurrence_song_id = ?
              AND l.link_status = 'accepted'
            """,
            (target["occurrence_song_id"],),
        )
        normalized = []
        for ev in evidence_rows:
            kind = normalize_kind(ev["evidence_type"], target["evidence_status"])
            role = evidence_role(ev["observed_at"], event_start, kind)
            normalized.append(
                {
                    "kind": kind,
                    "role": role,
                    "reliability": ev["reliability"],
                    "speaker": ev["account_key"] or ev["source_key"],
                    "source_year": (
                        int(str(ev["detected_event_date"])[:4])
                        if str(ev["detected_event_date"] or "")[:4].isdigit()
                        else None
                    ),
                }
            )

        if target["inherited_from_year"]:
            result = compute_historical_probability(
                normalized,
                int(target["event_year"]),
                int(target["inherited_from_year"]),
            )
        else:
            # Historical links can remain attached after direct current-year
            # evidence upgrades the same result row.  They remain provenance,
            # but must not be recomputed as un-decayed current hints.
            current_year = int(target["event_year"])
            current_evidence = [
                evidence
                for evidence in normalized
                if evidence.get("source_year") in {None, current_year}
            ]
            result = compute_probability(current_evidence)
        if result is None:
            skipped_no_current_evidence.append(
                {
                    "occurrence_song_id": target["occurrence_song_id"],
                    "normalized_title": target["normalized_title"],
                    "origin": target["origin"],
                    "evidence_linked": len(normalized),
                }
            )
            continue

        notes = target["notes"]
        if target["inherited_from_year"]:
            try:
                notes_data = json.loads(notes or "{}")
            except (TypeError, ValueError):
                notes_data = {}
            if not isinstance(notes_data, dict):
                notes_data = {}
            notes_data.update(
                {
                    "source_year": max(result["source_years"]),
                    "source_years": result["source_years"],
                    "source_kind": result["source_kind"],
                    "historical_basis_label": result["basis_label"],
                    "annual_probabilities": result["annual_probabilities"],
                    "decay_rate": DECAY_RATE,
                    "year_combination": "independent_noisy_or",
                }
            )
            notes = json.dumps(notes_data, ensure_ascii=False, sort_keys=True)
        conn.execute(
            "UPDATE occurrence_songs SET probability = ?, notes = ?, updated_at = ? "
            "WHERE occurrence_song_id = ?",
            (result["probability"], notes, now, target["occurrence_song_id"]),
        )
        updated.append(
            {
                "occurrence_song_id": target["occurrence_song_id"],
                "normalized_title": target["normalized_title"],
                "origin": target["origin"],
                "probability": result["probability"],
                "basis": result["basis"],
                "basis_label": result["basis_label"],
                "speaker_count": result["speaker_count"],
                "evidence_used": result["evidence_used"],
            }
        )
    return {
        "targets_considered": len(targets),
        "updated": updated,
        "skipped_no_current_evidence": skipped_no_current_evidence,
    }


def consistency_checks(conn, calibration):
    issues = []
    fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_rows:
        issues.append(
            {
                "severity": "high",
                "issue_type": "foreign_key_check_failed",
                "count": len(fk_rows),
                "sample": [tuple(row) for row in fk_rows[:10]],
            }
        )
    out_of_range = scalar(
        conn,
        "SELECT COUNT(*) FROM occurrence_songs WHERE probability IS NOT NULL "
        "AND (probability < 0 OR probability > 100)",
    )
    if out_of_range:
        issues.append({"severity": "high", "issue_type": "probability_out_of_range", "count": out_of_range})
    ids = [row["occurrence_song_id"] for row in calibration["updated"]]
    if ids:
        placeholders = ",".join("?" for _ in ids)
        still_null = scalar(
            conn,
            f"SELECT COUNT(*) FROM occurrence_songs WHERE occurrence_song_id IN ({placeholders}) "
            "AND probability IS NULL",
            ids,
        )
        if still_null:
            issues.append({"severity": "high", "issue_type": "update_did_not_apply", "count": still_null})
    return issues


def audit_db(db_path, out_json=None, out_md=None):
    args = SimpleNamespace(
        db=str(db_path),
        notion_db=str(audit_master_rdb.NOTION_DB),
        song_occurrences=str(audit_master_rdb.SONG_OCCURRENCES),
        manifest=str(audit_master_rdb.MASTER_MANIFEST),
        out_json=str(out_json or OUT_JSON.with_suffix(".audit.json")),
        out_md=str(out_md or OUT_MD.with_suffix(".audit.md")),
    )
    return audit_master_rdb.audit(args)


def issue_summary(issues):
    return dict(Counter(row.get("severity") for row in issues))


def render_markdown(result):
    summary = result["summary"]
    lines = [
        "# Song probability RDB calibration report",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- target_db: `{result['outputs']['target_db']}`",
        f"- backup_db: `{result['outputs']['backup_db']}`",
        f"- db_committed: {result['write_guard']['db_committed']}",
        f"- rolled_back: {result['write_guard']['rolled_back']}",
        "",
        "## Summary",
        "",
    ]
    for key, value in summary.items():
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## Scope",
            "",
            (
                "- Recalculates existing probabilities only where accepted linked evidence supports it."
                if result["options"]["recalculate_existing"]
                else "- Only fills occurrence_songs rows where probability IS NULL."
            ),
            "- Direct evidence uses the current_predictions/current_observed branches.",
            "- Rows carrying inherited_from_year use past-evidence decay; this does not create new inherited rows.",
            (
                "- Legacy rows without accepted evidence links are skipped, never assigned an invented value."
                if result["options"]["recalculate_existing"]
                else "- Existing non-NULL probability values (legacy JSON transcriptions) are left untouched."
            ),
            "",
        ]
    )
    if result["calibration"]["skipped_no_current_evidence"]:
        lines.extend(["## Skipped (no current-year evidence found)", ""])
        for row in result["calibration"]["skipped_no_current_evidence"][:20]:
            lines.append(f"- {row['normalized_title']} ({row['origin']}, {row['occurrence_song_id']})")
        lines.append("")
    if result["issues"]:
        lines.extend(["## Issues", ""])
        for issue in result["issues"]:
            lines.append(f"- {issue['severity']} {issue['issue_type']}: {issue}")
        lines.append("")
    return "\n".join(lines)


def run(args):
    validate_apply_request(args)
    now = now_utc()

    target_db = Path(args.master_db if args.apply else args.out_db)
    backup_path = ""
    if args.apply:
        preflight_db = DATA / "song_probability_calibration_apply_preflight.sqlite"
        copy_db(args.master_db, preflight_db)
        with connect_existing(preflight_db) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            preflight_calibration = calibrate(
                conn,
                now,
                args.occurrence_id,
                target_year=args.target_year,
                recalculate_existing=args.recalculate_existing,
            )
            preflight_issues = consistency_checks(conn, preflight_calibration)
            conn.commit()
        preflight_audit = audit_db(preflight_db)
        if any(row.get("severity") == "high" for row in preflight_issues + preflight_audit["issues"]):
            raise ValueError(
                "preflight refused high severity issues: "
                f"checks={issue_summary(preflight_issues)} "
                f"audit={preflight_audit['issues_by_severity']}"
            )
        backup_path = str(backup_db(args.master_db, now))
    else:
        copy_db(args.master_db, args.out_db)

    committed = False
    rolled_back = False
    with connect_existing(target_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        calibration = calibrate(
            conn,
            now,
            args.occurrence_id,
            target_year=args.target_year,
            recalculate_existing=args.recalculate_existing,
        )
        issues = consistency_checks(conn, calibration)
        has_high_issue = any(row.get("severity") == "high" for row in issues)
        if has_high_issue:
            conn.rollback()
            rolled_back = True
        else:
            conn.commit()
            committed = True
        counts = table_counts(conn)

    audit_result = audit_db(
        target_db,
        out_json=args.out_json.with_suffix(".audit.json"),
        out_md=args.out_md.with_suffix(".audit.md"),
    )
    if args.apply and audit_result["issues_by_severity"].get("high"):
        raise ValueError(f"post-apply audit has high issues: {audit_result['issues_by_severity']}")
    if args.apply and committed:
        refresh_manifest_database_state(args.master_db, updated_at=now)

    result = {
        "generated_by": SCRIPT_NAME,
        "generated_at": now,
        "mode": "apply" if args.apply else "dry_run",
        "sources": {"master_db": str(args.master_db)},
        "outputs": {
            "target_db": str(target_db),
            "dry_run_db": "" if args.apply else str(args.out_db),
            "backup_db": backup_path,
            "json": str(args.out_json),
            "markdown": str(args.out_md),
        },
        "options": {
            "apply": bool(args.apply),
            "occurrence_id": args.occurrence_id,
            "target_year": args.target_year,
            "recalculate_existing": bool(args.recalculate_existing),
        },
        "write_guard": {
            "db_committed": committed,
            "rolled_back": rolled_back,
            "rollback_reason": "high_severity_issue" if rolled_back else "",
        },
        "summary": {
            "targets_considered": calibration["targets_considered"],
            "rows_updated": len(calibration["updated"]),
            "rows_skipped_no_current_evidence": len(calibration["skipped_no_current_evidence"]),
            "probability_min": min((r["probability"] for r in calibration["updated"]), default=None),
            "probability_max": max((r["probability"] for r in calibration["updated"]), default=None),
            "basis_distribution": dict(Counter(r["basis"] for r in calibration["updated"])),
            "issues_by_severity": issue_summary(issues),
            "audit_issues_by_severity": audit_result["issues_by_severity"],
            "table_counts": counts,
        },
        "calibration": calibration,
        "issues": issues,
        "audit": {
            "issue_count": audit_result["issue_count"],
            "issues_by_severity": audit_result["issues_by_severity"],
            "issues_by_type": audit_result["issues_by_type"],
        },
    }
    write_json(args.out_json, result)
    Path(args.out_md).write_text(render_markdown(result), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-db", type=Path, default=MASTER_DB)
    parser.add_argument("--out-db", type=Path, default=OUT_DB)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    parser.add_argument("--occurrence-id", default="")
    parser.add_argument("--target-year", type=int)
    parser.add_argument("--recalculate-existing", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        result = run(args)
    except ValueError as exc:
        parser.error(str(exc))
    print(
        "song probability calibration: "
        f"mode={result['mode']} "
        f"committed={result['write_guard']['db_committed']} "
        f"updated={result['summary']['rows_updated']}/{result['summary']['targets_considered']} "
        f"skipped={result['summary']['rows_skipped_no_current_evidence']} "
        f"basis={result['summary']['basis_distribution']} "
        f"issues={result['summary']['issues_by_severity']} "
        f"audit={result['summary']['audit_issues_by_severity']}"
    )
    return 1 if result["summary"]["issues_by_severity"].get("high") else 0


if __name__ == "__main__":
    raise SystemExit(main())
