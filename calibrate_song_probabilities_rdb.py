"""Compute occurrence_songs.probability natively from RDB evidence.

Phase 1 of the RDB-native rewrite of song_processing/song_occurrences.py's
prediction_probability()/evidence_view_for_year() (see that module's header
and apply_youtube_setlist_occurrences_rdb.py's docstring, which deliberately
left probability NULL pending this rewrite).

Scope (2026-07-24 spot-check on the live master DB): every occurrence_songs
row with probability IS NULL turned out to have evidence linked directly via
occurrence_song_evidence_links for its own occurrence year -- none needed
cross-year inheritance (no row has inherited_from_year set yet; that's the
"past_evidence"/"prior" branches of the legacy algorithm and is out of scope
for this pass). So this script only reimplements the "current year, direct
evidence" branches (current_predictions / current_observed) of the legacy
prediction_probability(). Cross-year inheritance is a separate follow-up.

Never touches a row whose probability is already non-NULL -- those are
legacy JSON-computed values transcribed once by build_master_rdb.py's
build_from_song_occurrences(); leaving them alone avoids silently changing
already-published numbers in this pass.

Evidence normalization, per linked evidence_items row:
  - kind: evidence_items.evidence_type, mapped through KIND_BY_EVIDENCE_TYPE
    (unknown types fall back to "hint", the conservative legacy default).
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
}

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
    if not args.apply:
        return
    if args.confirm != CONFIRM_PHRASE:
        raise ValueError(f"--apply requires --confirm '{CONFIRM_PHRASE}'")
    if Path(args.out_db) == Path(args.master_db):
        raise ValueError("--out-db must not equal --master-db")


def normalize_kind(evidence_type):
    return KIND_BY_EVIDENCE_TYPE.get(evidence_type, "hint")


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


def calibrate(conn, now):
    targets = rows(
        conn,
        "SELECT occurrence_song_id, occurrence_id, normalized_title, origin "
        "FROM occurrence_songs WHERE probability IS NULL",
    )
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
            SELECT e.evidence_type, e.observed_at, l.confidence AS reliability,
                   e.account_key, e.source_key
            FROM occurrence_song_evidence_links l
            JOIN evidence_items e ON e.evidence_id = l.evidence_id
            WHERE l.occurrence_song_id = ?
            """,
            (target["occurrence_song_id"],),
        )
        normalized = []
        for ev in evidence_rows:
            kind = normalize_kind(ev["evidence_type"])
            role = evidence_role(ev["observed_at"], event_start, kind)
            normalized.append(
                {
                    "kind": kind,
                    "role": role,
                    "reliability": ev["reliability"],
                    "speaker": ev["account_key"] or ev["source_key"],
                }
            )

        result = compute_probability(normalized)
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

        conn.execute(
            "UPDATE occurrence_songs SET probability = ?, updated_at = ? WHERE occurrence_song_id = ?",
            (result["probability"], now, target["occurrence_song_id"]),
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
        "# Song probability RDB calibration report (Phase 1: direct evidence only)",
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
            "- Only fills occurrence_songs rows where probability IS NULL.",
            "- Only uses evidence directly linked to that occurrence_song's own year "
            "(current_predictions / current_observed branches of the legacy algorithm).",
            "- Cross-year inheritance (past_evidence/prior branches) is out of scope "
            "for this pass -- no row had inherited_from_year set at calibration time.",
            "- Existing non-NULL probability values (legacy JSON transcriptions) are left untouched.",
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
            preflight_calibration = calibrate(conn, now)
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
        calibration = calibrate(conn, now)
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
        "options": {"apply": bool(args.apply)},
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
