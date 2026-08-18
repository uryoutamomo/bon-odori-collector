"""Inherit song probability across years from the most recent past occurrence.

Phase 2 of the RDB-native rewrite of song_processing/song_occurrences.py's
prediction_probability()/evidence_view_for_year() -- Phase 1
(calibrate_song_probabilities_rdb.py) only handles a song with direct evidence
in its own occurrence year. This script reimplements the legacy algorithm's
"past_evidence" branch: for a series' target-year occurrence, a song observed
only in an earlier occurrence of the same series is carried forward as a
role='prediction' row with a decayed probability, instead of vanishing from
the target year's song list entirely.

Scope: creates a new occurrence_songs row when the target-year occurrence has
no direct row for that normalized_title, and refreshes only rows previously
created by this inheritance script. Existing direct evidence (Phase 1's job)
always wins and is never overwritten. Direct evidence from every available
past event year is grouped by year, decayed, and combined; repeated annual
appearances therefore score higher than a single appearance. X-song materializer-owned facts and
X-song claim evidence are deliberately excluded: their publication contract
requires an active materialization ledger entry, which an inherited prediction
cannot preserve.

Probability formula (ported from song_processing/song_occurrences.py's
prediction_probability(), past-evidence branch):
    annual = noisy_or(reliability within year)
             * decay_rate ** (target_year - source_year)
             * speaker_factor_within_year
    probability = noisy_or(annual contribution from every source year) * 100
    clamped to [5, 90]
decay_rate defaults to 0.75, matching DEFAULT_PREDICTION_PARAMS in
song_processing/song_occurrences.py.

Older imported rows that have a reviewed event-year probability but no
accepted per-source link use that probability as the annual base fallback;
they still receive the same speaker adjustment, year decay, and cross-year
noisy-or. This lets repeated legacy years contribute without treating the
old event-year probability as a current-year fact.

Default mode writes only to a copied SQLite DB. Production writes require
--apply and the confirmation phrase.
"""

import argparse
import json
import shutil
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

import audit_master_rdb
from calibrate_song_probabilities_rdb import (
    DECAY_RATE,
    compute_historical_probability,
    normalize_kind,
)
from master_rdb.master_db import (
    MASTER_DB,
    connect_existing,
    now_utc,
    refresh_manifest_database_state,
    stable_id,
    table_counts,
)


DATA = Path("data")
OUT_DB = DATA / "song_probability_inheritance_dry_run.sqlite"
OUT_JSON = DATA / "song_probability_inheritance_report.json"
OUT_MD = DATA / "song_probability_inheritance_report.md"
BACKUP_DIR = DATA / "backups"
CONFIRM_PHRASE = "APPLY SONG PROBABILITY INHERITANCE RDB"
SCRIPT_NAME = "inherit_song_probabilities_rdb.py"

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


def find_inheritance_candidates(conn, target_year):
    """Return prior-year direct songs absent from a series' target occurrence.

    Every available past event year is retained for cross-year combination;
    a direct-evidence row on the target occurrence always excludes inheritance.
    """
    series_occs = defaultdict(list)
    for row in rows(
        conn,
        "SELECT series_id, event_year, occurrence_id FROM event_occurrences WHERE origin='curated'",
    ):
        series_occs[row["series_id"]].append((row["event_year"], row["occurrence_id"]))

    candidates = []
    for series_id, occs in series_occs.items():
        occs.sort()
        target_occurrence_id = next(
            (occ_id for year, occ_id in occs if year == target_year), None
        )
        if not target_occurrence_id:
            continue
        past = [(year, occ_id) for year, occ_id in occs if year < target_year]
        if not past:
            continue
        existing_titles = {
            row["normalized_title"]
            for row in rows(
                conn,
                "SELECT normalized_title FROM occurrence_songs "
                "WHERE occurrence_id = ? AND origin != 'inherited_prediction'",
                (target_occurrence_id,),
            )
        }
        candidates_by_title = {}
        for source_year, source_occurrence_id in sorted(past, reverse=True):
            source_songs = rows(
                conn,
                """
                SELECT occurrence_song_id, song_id, song_title_raw, normalized_title,
                       role, evidence_status, probability, source_count
                FROM occurrence_songs
                WHERE occurrence_id = ?
                  AND origin NOT IN ('observed_x_post', 'inherited_prediction')
                ORDER BY CASE role WHEN 'result' THEN 0 WHEN 'setlist' THEN 1 ELSE 2 END
                """,
                (source_occurrence_id,),
            )
            # The same song can exist under multiple roles in one occurrence.
            # Keep its most-observed direct row for that event year.
            picked_titles = set()
            for song in source_songs:
                normalized_title = song["normalized_title"]
                if normalized_title in existing_titles or normalized_title in picked_titles:
                    continue
                picked_titles.add(normalized_title)
                candidate = candidates_by_title.get(normalized_title)
                if candidate is None:
                    candidate = {
                        "series_id": series_id,
                        "target_occurrence_id": target_occurrence_id,
                        "target_year": target_year,
                        # Compatibility fields identify the latest direct source.
                        "source_occurrence_id": source_occurrence_id,
                        "source_year": source_year,
                        "source_occurrence_song_id": song["occurrence_song_id"],
                        "source_role": song["role"],
                        "source_evidence_status": song["evidence_status"],
                        "source_probability": song["probability"],
                        "source_count": song["source_count"],
                        "song_id": song["song_id"],
                        "song_title_raw": song["song_title_raw"],
                        "normalized_title": normalized_title,
                        "source_occurrence_songs": [],
                    }
                    candidates_by_title[normalized_title] = candidate
                candidate["source_occurrence_songs"].append(
                    {
                        "source_occurrence_id": source_occurrence_id,
                        "source_occurrence_song_id": song["occurrence_song_id"],
                        "source_year": source_year,
                        "source_role": song["role"],
                        "source_evidence_status": song["evidence_status"],
                        "source_probability": song["probability"],
                        "source_count": song["source_count"],
                    }
                )
        candidates.extend(
            sorted(candidates_by_title.values(), key=lambda row: row["normalized_title"])
        )
    return candidates


def gather_evidence(
    conn,
    occurrence_song_id,
    source_year=None,
    include_evidence_id=False,
    evidence_status=None,
):
    evidence_rows = rows(
        conn,
        """
        SELECT e.evidence_id, e.evidence_type, e.account_key, e.source_key,
               l.confidence AS reliability
        FROM occurrence_song_evidence_links l
        JOIN evidence_items e ON e.evidence_id = l.evidence_id
        WHERE l.occurrence_song_id = ?
          AND l.link_status = 'accepted'
          AND e.evidence_type != 'x_song_claim_v2'
        """,
        (occurrence_song_id,),
    )
    result = []
    for row in evidence_rows:
        evidence = {
            "kind": normalize_kind(row["evidence_type"], evidence_status),
            "reliability": row["reliability"],
            "speaker": row["account_key"] or row["source_key"],
        }
        if source_year is not None:
            evidence["source_year"] = source_year
        if include_evidence_id:
            evidence["evidence_id"] = row["evidence_id"]
        result.append(evidence)
    return result


def compute_inherited_probability(evidence_rows, target_year, source_year):
    return compute_historical_probability(evidence_rows, target_year, source_year)


def inherit(conn, target_year, now):
    candidates = find_inheritance_candidates(conn, target_year)
    created = []
    updated = []
    skipped_no_evidence = []
    for candidate in candidates:
        evidence_by_id = {}
        for source in candidate["source_occurrence_songs"]:
            source_evidence = gather_evidence(
                conn,
                source["source_occurrence_song_id"],
                source_year=source["source_year"],
                include_evidence_id=True,
                evidence_status=source["source_evidence_status"],
            )
            for evidence in source_evidence:
                # If one evidence item was accidentally linked to more than one
                # historical occurrence, keep its latest-year interpretation.
                evidence_by_id.setdefault(evidence["evidence_id"], evidence)
        evidence_rows = [
            {key: value for key, value in evidence.items() if key != "evidence_id"}
            for evidence in evidence_by_id.values()
        ]
        years_with_evidence = {row["source_year"] for row in evidence_rows}
        annual_fallbacks = []
        for source in candidate["source_occurrence_songs"]:
            if source["source_year"] in years_with_evidence or source["source_probability"] is None:
                continue
            source_kind = {
                "announced": "announced",
                "observed": "observed",
            }.get(source["source_evidence_status"], "hint")
            annual_fallbacks.append(
                {
                    "source_year": source["source_year"],
                    "probability": source["source_probability"],
                    "source_count": source["source_count"],
                    "source_kind": source_kind,
                }
            )
        result = compute_historical_probability(
            evidence_rows,
            target_year,
            candidate["source_year"],
            annual_fallbacks=annual_fallbacks,
        )
        if result is None:
            skipped_no_evidence.append(candidate)
            continue

        occurrence_song_id = stable_id(
            "ocs_inherit", candidate["target_occurrence_id"], candidate["normalized_title"], "prediction"
        )
        existing = conn.execute(
            """
            SELECT occurrence_song_id FROM occurrence_songs
            WHERE occurrence_id = ? AND normalized_title = ? AND role = 'prediction'
              AND origin = 'inherited_prediction'
            """,
            (candidate["target_occurrence_id"], candidate["normalized_title"]),
        ).fetchone()
        notes = json.dumps(
            {
                "basis": "past_evidence",
                "source_occurrence_song_id": candidate["source_occurrence_song_id"],
                "source_occurrence_song_ids": [
                    source["source_occurrence_song_id"]
                    for source in candidate["source_occurrence_songs"]
                ],
                "source_year": max(result["source_years"]),
                "source_years": result["source_years"],
                "source_kind": result["source_kind"],
                "historical_basis_label": result["basis_label"],
                "annual_probabilities": result["annual_probabilities"],
                "fallback_years": result["fallback_years"],
                "speaker_count": result["speaker_count"],
                "decay_rate": DECAY_RATE,
                "year_combination": "independent_noisy_or",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if existing:
            conn.execute(
                """
                UPDATE occurrence_songs
                SET probability = ?, source_count = ?, evidence_count = ?,
                    inherited_from_year = ?, notes = ?, updated_at = ?
                WHERE occurrence_song_id = ?
                """,
                (
                    result["probability"],
                    result["speaker_count"],
                    result["evidence_used"],
                    max(result["source_years"]),
                    notes,
                    now,
                    existing[0],
                ),
            )
            updated.append(
                {
                    "occurrence_song_id": existing[0],
                    "series_id": candidate["series_id"],
                    "target_year": target_year,
                    "song_title_raw": candidate["song_title_raw"],
                    "source_years": result["source_years"],
                    "probability": result["probability"],
                    "basis_label": result["basis_label"],
                    "speaker_count": result["speaker_count"],
                }
            )
            continue

        conn.execute(
            """
            INSERT INTO occurrence_songs(
              occurrence_song_id, origin, occurrence_id, song_id, song_title_raw, normalized_title,
              role, evidence_status, probability, confidence, source_count, evidence_count,
              inherited_from_year, first_observed_at, last_observed_at, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                occurrence_song_id,
                "inherited_prediction",
                candidate["target_occurrence_id"],
                candidate["song_id"],
                candidate["song_title_raw"],
                candidate["normalized_title"],
                "prediction",
                "predicted",
                result["probability"],
                "unknown",
                result["speaker_count"],
                result["evidence_used"],
                max(result["source_years"]),
                "",
                "",
                notes,
                now,
                now,
            ),
        )
        created.append(
            {
                "occurrence_song_id": occurrence_song_id,
                "series_id": candidate["series_id"],
                "target_year": target_year,
                "song_title_raw": candidate["song_title_raw"],
                "source_years": result["source_years"],
                "probability": result["probability"],
                "basis_label": result["basis_label"],
                "speaker_count": result["speaker_count"],
            }
        )
    return {
        "candidates_considered": len(candidates),
        "created": created,
        "updated": updated,
        "skipped_no_evidence": skipped_no_evidence,
    }


def consistency_checks(conn, inheritance):
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
        "SELECT COUNT(*) FROM occurrence_songs WHERE origin='inherited_prediction' "
        "AND (probability < 5 OR probability > 90)",
    )
    if out_of_range:
        issues.append({"severity": "high", "issue_type": "probability_out_of_range", "count": out_of_range})
    missing_year = scalar(
        conn,
        "SELECT COUNT(*) FROM occurrence_songs WHERE origin='inherited_prediction' "
        "AND inherited_from_year IS NULL",
    )
    if missing_year:
        issues.append({"severity": "high", "issue_type": "inherited_row_missing_source_year", "count": missing_year})
    overwrote_direct_evidence = scalar(
        conn,
        """
        SELECT COUNT(*) FROM (
          SELECT occurrence_id, normalized_title, COUNT(DISTINCT role) c
          FROM occurrence_songs
          WHERE origin != 'inherited_prediction'
          GROUP BY occurrence_id, normalized_title
        )
        """,
    )
    # Sanity signal only, not an issue by itself; kept out of `issues` since a
    # count here is expected (role='prediction' + role='result' can coexist).
    del overwrote_direct_evidence
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
        "# Song probability year-over-year inheritance report",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- target_year: {result['options']['target_year']}",
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
            "- Only series with BOTH a target_year occurrence and an earlier occurrence are considered.",
            "- Direct evidence from every available past event year is combined after per-year decay.",
            "- A direct song row already present on the target occurrence is never overwritten; "
            "only an existing inherited_prediction row can be refreshed.",
            "- New rows are written with role='prediction', origin='inherited_prediction', "
            "inherited_from_year=<source year>.",
            "",
        ]
    )
    if result["inheritance"]["created"]:
        lines.extend(["## Sample created rows", ""])
        for row in result["inheritance"]["created"][:20]:
            lines.append(
                f"- {row['song_title_raw']}: {row['probability']}% ({row['basis_label']}, "
                f"speakers={row['speaker_count']})"
            )
        lines.append("")
    if result["inheritance"]["updated"]:
        lines.extend(["## Sample updated rows", ""])
        for row in result["inheritance"]["updated"][:20]:
            lines.append(
                f"- {row['song_title_raw']}: {row['probability']}% ({row['basis_label']}, "
                f"speakers={row['speaker_count']})"
            )
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
        preflight_db = DATA / "song_probability_inheritance_apply_preflight.sqlite"
        copy_db(args.master_db, preflight_db)
        with connect_existing(preflight_db) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            preflight_inheritance = inherit(conn, args.target_year, now)
            preflight_issues = consistency_checks(conn, preflight_inheritance)
            conn.commit()
        preflight_audit = audit_db(preflight_db)
        if any(row.get("severity") == "high" for row in preflight_issues + preflight_audit["issues"]):
            raise ValueError(
                "preflight refused high severity issues: "
                f"checks={issue_summary(preflight_issues)} "
                f"audit={preflight_audit['issues_by_severity']}"
            )
        backup_path = str(backup_db(args.master_db, now))
        preflight_db.unlink(missing_ok=True)
    else:
        copy_db(args.master_db, args.out_db)

    committed = False
    rolled_back = False
    with connect_existing(target_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        inheritance = inherit(conn, args.target_year, now)
        issues = consistency_checks(conn, inheritance)
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

    changed_rows = inheritance["created"] + inheritance["updated"]
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
        "options": {"apply": bool(args.apply), "target_year": args.target_year},
        "write_guard": {
            "db_committed": committed,
            "rolled_back": rolled_back,
            "rollback_reason": "high_severity_issue" if rolled_back else "",
        },
        "summary": {
            "candidates_considered": inheritance["candidates_considered"],
            "rows_created": len(inheritance["created"]),
            "rows_updated": len(inheritance["updated"]),
            "rows_skipped_no_evidence": len(inheritance["skipped_no_evidence"]),
            "probability_min": min((r["probability"] for r in changed_rows), default=None),
            "probability_max": max((r["probability"] for r in changed_rows), default=None),
            "issues_by_severity": issue_summary(issues),
            "audit_issues_by_severity": audit_result["issues_by_severity"],
            "table_counts": counts,
        },
        "inheritance": inheritance,
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
    parser.add_argument("--target-year", type=int, required=True)
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
        "song probability inheritance: "
        f"mode={result['mode']} "
        f"committed={result['write_guard']['db_committed']} "
        f"created={result['summary']['rows_created']}/{result['summary']['candidates_considered']} "
        f"skipped={result['summary']['rows_skipped_no_evidence']} "
        f"issues={result['summary']['issues_by_severity']} "
        f"audit={result['summary']['audit_issues_by_severity']}"
    )
    return 1 if result["summary"]["issues_by_severity"].get("high") else 0


if __name__ == "__main__":
    raise SystemExit(main())
