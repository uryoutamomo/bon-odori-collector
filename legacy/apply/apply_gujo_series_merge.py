"""Merge the duplicate Gujo Odori in Aoyama event series in the master RDB.

Default mode writes to a copied SQLite DB. Apply mode moves the 2025 occurrence
onto the 2026 confirmed series, fills its venue, and marks the old duplicate
series as merged without deleting rows.
"""

import argparse
import json
import shutil
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from master_rdb.master_db import MASTER_DB, connect_existing, normalize_text, refresh_manifest_database_state, table_counts


DATA = Path("data")
OUT_DB = DATA / "gujo_series_merge_dry_run.sqlite"
OUT_JSON = DATA / "gujo_series_merge_report.json"
OUT_MD = DATA / "gujo_series_merge_report.md"
BACKUP_DIR = DATA / "backups"
CONFIRM = "APPLY GUJO SERIES MERGE"

EVENT_NAME = "郡上おどり in 青山"
OLD_SERIES_ID = "ser_ae34d6aa992bd0c8"
NEW_SERIES_ID = "ser_d39870ddba633c11"
OCC_2025_ID = "occ_56d48c1deeded4ab"
OCC_2026_ID = "occ_23ad1c8ae9eb48cf"
VENUE_ID = "ven_a52431fddb1891f8"


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rows(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def scalar(conn, query, params=()):
    return conn.execute(query, params).fetchone()[0]


def copy_db(source, out_db):
    out_db = Path(out_db)
    out_db.parent.mkdir(parents=True, exist_ok=True)
    if out_db.exists():
        out_db.unlink()
    shutil.copy2(source, out_db)


def backup_db(source, now):
    source = Path(source)
    stamp = now.replace("-", "").replace(":", "").replace("+00:00", "Z")
    backup = BACKUP_DIR / f"{source.stem}.{stamp}{source.suffix}.bak"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup)
    return backup


def series(conn, series_id):
    result = rows(
        conn,
        """
        SELECT s.*, v.canonical_name AS usual_venue
        FROM event_series s
        LEFT JOIN venues v ON v.venue_id = s.usual_venue_id
        WHERE s.series_id = ?
        """,
        (series_id,),
    )
    return result[0] if result else None


def occurrence(conn, occurrence_id):
    result = rows(
        conn,
        """
        SELECT o.*, v.canonical_name AS venue
        FROM event_occurrences o
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE o.occurrence_id = ?
        """,
        (occurrence_id,),
    )
    return result[0] if result else None


def snapshot(conn):
    return {
        "old_series": series(conn, OLD_SERIES_ID),
        "new_series": series(conn, NEW_SERIES_ID),
        "occurrence_2025": occurrence(conn, OCC_2025_ID),
        "occurrence_2026": occurrence(conn, OCC_2026_ID),
        "predicted_dates": rows(
            conn,
            """
            SELECT predicted_date_id, target_series_id, target_occurrence_id,
                   date_start, date_end, application_status
            FROM predicted_occurrence_dates
            WHERE target_event_name = ?
            """,
            (EVENT_NAME,),
        ),
        "historical_candidates": rows(
            conn,
            """
            SELECT candidate_id, target_series_id, target_occurrence_id, target_event_name
            FROM historical_promotion_candidates
            WHERE target_event_name = ?
            """,
            (EVENT_NAME,),
        ),
        "series_links": rows(
            conn,
            """
            SELECT system, source_key, external_id, master_table, master_id, relation_kind
            FROM external_record_links
            WHERE master_table = 'event_series'
              AND master_id IN (?, ?)
            ORDER BY external_id, master_id
            """,
            (OLD_SERIES_ID, NEW_SERIES_ID),
        ),
    }


def validate_preconditions(conn):
    issues = []
    old_series = series(conn, OLD_SERIES_ID)
    new_series = series(conn, NEW_SERIES_ID)
    occ_2025 = occurrence(conn, OCC_2025_ID)
    occ_2026 = occurrence(conn, OCC_2026_ID)
    if not old_series:
        issues.append({"severity": "high", "issue_type": "missing_old_series"})
    if not new_series:
        issues.append({"severity": "high", "issue_type": "missing_new_series"})
    if not occ_2025:
        issues.append({"severity": "high", "issue_type": "missing_2025_occurrence"})
    if not occ_2026:
        issues.append({"severity": "high", "issue_type": "missing_2026_occurrence"})
    if occ_2025 and occ_2025.get("series_id") != OLD_SERIES_ID:
        issues.append({"severity": "high", "issue_type": "unexpected_2025_series"})
    if occ_2026 and occ_2026.get("series_id") != NEW_SERIES_ID:
        issues.append({"severity": "high", "issue_type": "unexpected_2026_series"})
    if occ_2026 and occ_2026.get("venue_id") != VENUE_ID:
        issues.append({"severity": "high", "issue_type": "unexpected_2026_venue"})
    conflict = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM event_occurrences
        WHERE series_id = ?
          AND event_year = 2025
          AND occurrence_sequence = 1
          AND occurrence_id != ?
        """,
        (NEW_SERIES_ID, OCC_2025_ID),
    )
    if conflict:
        issues.append({"severity": "high", "issue_type": "new_series_2025_sequence_conflict", "count": conflict})
    return issues


def apply_merge(conn, now):
    before = snapshot(conn)
    pre_issues = validate_preconditions(conn)
    if any(issue["severity"] == "high" for issue in pre_issues):
        return before, before, pre_issues

    conn.execute(
        """
        UPDATE event_occurrences
        SET series_id = ?,
            venue_id = ?,
            updated_at = ?
        WHERE occurrence_id = ?
        """,
        (NEW_SERIES_ID, VENUE_ID, now, OCC_2025_ID),
    )
    conn.execute(
        """
        UPDATE historical_promotion_candidates
        SET target_series_id = ?,
            updated_at = ?
        WHERE target_series_id = ?
          AND target_event_name = ?
        """,
        (NEW_SERIES_ID, now, OLD_SERIES_ID, EVENT_NAME),
    )
    conn.execute(
        """
        UPDATE predicted_occurrence_dates
        SET target_series_id = ?,
            target_occurrence_id = ?,
            application_status = 'superseded_by_curated',
            updated_at = ?
        WHERE target_series_id = ?
          AND target_event_name = ?
        """,
        (NEW_SERIES_ID, OCC_2026_ID, now, OLD_SERIES_ID, EVENT_NAME),
    )
    conn.execute(
        """
        UPDATE notion_sync_jobs
        SET status = 'superseded_by_curated',
            result_json = ?
        WHERE target_table = 'predicted_occurrence_dates'
          AND target_id IN (
            SELECT predicted_date_id
            FROM predicted_occurrence_dates
            WHERE target_event_name = ?
          )
          AND status = 'pending'
        """,
        (
            json.dumps(
                {
                    "reviewed_by": "apply_gujo_series_merge.py",
                    "reviewed_at": now,
                    "reason": "curated_2026_occurrence_exists_after_series_merge",
                    "curated_occurrence_id": OCC_2026_ID,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            EVENT_NAME,
        ),
    )
    conn.execute(
        """
        UPDATE external_record_links
        SET master_id = ?
        WHERE master_table = 'event_series'
          AND master_id = ?
        """,
        (NEW_SERIES_ID, OLD_SERIES_ID),
    )
    conn.execute(
        """
        UPDATE event_series
        SET canonical_name = ?,
            normalized_name = ?,
            status = 'merged',
            updated_at = ?
        WHERE series_id = ?
        """,
        (
            f"{EVENT_NAME}（統合済み）",
            normalize_text(f"{EVENT_NAME}（統合済み）"),
            now,
            OLD_SERIES_ID,
        ),
    )
    after = snapshot(conn)
    return before, after, pre_issues


def consistency_checks(conn):
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
    occ_2025 = occurrence(conn, OCC_2025_ID)
    if not occ_2025 or occ_2025.get("series_id") != NEW_SERIES_ID or occ_2025.get("venue_id") != VENUE_ID:
        issues.append(
            {
                "severity": "high",
                "issue_type": "2025_occurrence_not_merged",
                "occurrence": occ_2025,
            }
        )
    duplicate_active = rows(
        conn,
        """
        SELECT normalized_name, COUNT(*) AS c
        FROM event_series
        WHERE status = 'active'
        GROUP BY normalized_name
        HAVING c > 1
        """,
    )
    if duplicate_active:
        issues.append(
            {
                "severity": "medium",
                "issue_type": "duplicate_active_series_names_remain",
                "rows": duplicate_active,
            }
        )
    predicted = rows(
        conn,
        """
        SELECT predicted_date_id, target_series_id, target_occurrence_id, application_status
        FROM predicted_occurrence_dates
        WHERE target_event_name = ?
        """,
        (EVENT_NAME,),
    )
    for row in predicted:
        if row["target_series_id"] != NEW_SERIES_ID or row["target_occurrence_id"] != OCC_2026_ID:
            issues.append({"severity": "high", "issue_type": "gujo_prediction_not_relinked", "row": row})
    return issues


def render_markdown(result):
    before = result["before"]
    after = result["after"]
    lines = [
        "# Gujo series merge report",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- target_db: `{result['outputs']['target_db']}`",
        f"- dry_run_db: `{result['outputs']['dry_run_db']}`",
        f"- backup_db: `{result['outputs']['backup_db']}`",
        f"- db_committed: {result['write_guard']['db_committed']}",
        f"- rolled_back: {result['write_guard']['rolled_back']}",
        f"- issues_by_severity: {result['summary']['issues_by_severity']}",
        "",
        "## Change",
        "",
        "| item | before | after |",
        "| --- | --- | --- |",
        f"| 2025 occurrence series | {before['occurrence_2025'].get('series_id')} | {after['occurrence_2025'].get('series_id')} |",
        f"| 2025 occurrence venue | {before['occurrence_2025'].get('venue') or ''} | {after['occurrence_2025'].get('venue') or ''} |",
        f"| old series status | {before['old_series'].get('status')} | {after['old_series'].get('status')} |",
        f"| old series name | {before['old_series'].get('canonical_name')} | {after['old_series'].get('canonical_name')} |",
        f"| predicted status | {before['predicted_dates']} | {after['predicted_dates']} |",
        "",
    ]
    if result["issues"]:
        lines.extend(["## Issues", ""])
        for issue in result["issues"]:
            lines.append(f"- {issue['severity']} {issue['issue_type']}: {issue}")
        lines.append("")
    return "\n".join(lines)


def validate_apply(args):
    if not args.apply:
        return
    if args.confirm != CONFIRM:
        raise ValueError(f"--apply requires --confirm '{CONFIRM}'")
    if Path(args.out_db) == Path(args.master_db):
        raise ValueError("--out-db must not equal --master-db")


def run(args):
    validate_apply(args)
    now = datetime.now(timezone.utc).isoformat()
    target_db = Path(args.master_db if args.apply else args.out_db)
    backup = ""
    if args.apply:
        backup = str(backup_db(args.master_db, now))
    else:
        copy_db(args.master_db, args.out_db)

    with connect_existing(target_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        before, after, pre_issues = apply_merge(conn, now)
        issues = pre_issues + consistency_checks(conn)
        has_high_issue = any(issue["severity"] == "high" for issue in issues)
        if args.apply and has_high_issue:
            conn.rollback()
            committed = False
            rolled_back = True
        else:
            conn.commit()
            committed = True
            rolled_back = False
        counts = table_counts(conn)
        duplicate_series = rows(
            conn,
            """
            SELECT normalized_name, COUNT(*) AS c
            FROM event_series
            GROUP BY normalized_name
            HAVING c > 1
            ORDER BY c DESC, normalized_name
            """,
        )
        missing_venue_count = scalar(conn, "SELECT COUNT(*) FROM event_occurrences WHERE venue_id IS NULL")
    if args.apply and committed:
        refresh_manifest_database_state(args.master_db, updated_at=now)

    result = {
        "generated_by": "apply_gujo_series_merge.py",
        "generated_at": now,
        "mode": "apply" if args.apply else "dry_run",
        "scope": (
            "source_master_db_apply_no_notion_no_public_json"
            if args.apply
            else "copied_sqlite_only_no_notion_no_public_json"
        ),
        "outputs": {
            "target_db": str(target_db),
            "dry_run_db": "" if args.apply else str(args.out_db),
            "backup_db": backup,
        },
        "write_guard": {
            "db_committed": committed,
            "rolled_back": rolled_back,
            "rollback_reason": "high_severity_issue" if rolled_back else "",
        },
        "summary": {
            "issues_count": len(issues),
            "issues_by_severity": dict(Counter(issue["severity"] for issue in issues)),
            "missing_venue_count": missing_venue_count,
            "duplicate_series_name_count": len(duplicate_series),
            "table_counts": counts,
        },
        "before": before,
        "after": after,
        "duplicate_series": duplicate_series,
        "issues": issues,
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
        "gujo series merge: "
        f"mode={result['mode']} "
        f"missing_venue={result['summary']['missing_venue_count']} "
        f"duplicate_series={result['summary']['duplicate_series_name_count']} "
        f"issues={result['summary']['issues_by_severity']}"
    )
    return 1 if result["summary"]["issues_by_severity"].get("high") else 0


if __name__ == "__main__":
    raise SystemExit(main())
