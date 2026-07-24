"""Merge RDB series that were split across an earlier-year and a 2026 occurrence
under different series_id values, found by export_public_events.py's
find_series_split_review_candidates() audit.

Default mode writes to a copied SQLite DB. Apply mode moves the earlier-year
occurrence onto the 2026 series and marks the old duplicate series as merged
without deleting rows. Modeled on legacy/apply/apply_gujo_series_merge.py,
generalized to handle multiple targets in one guarded run.
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
OUT_DB = DATA / "series_split_merge_dry_run.sqlite"
OUT_JSON = DATA / "series_split_merge_report.json"
OUT_MD = DATA / "series_split_merge_report.md"
BACKUP_DIR = DATA / "backups"
CONFIRM = "APPLY SERIES SPLIT MERGE"

MERGE_TARGETS = [
    {
        "event_name": "新橋こいち祭",
        "old_series_id": "ser_b25e3d3ce5b22a32",
        "new_series_id": "ser_f91d329d77a2eda7",
        "old_occurrence_id": "occ_85b5772373d4e5df",
        "new_occurrence_id": "occ_7a555fbc00d0c059",
    },
    {
        "event_name": "神楽坂まつり",
        "old_series_id": "ser_1ab93540c9d8028a",
        "new_series_id": "ser_f7a0b21ef9031aa9",
        "old_occurrence_id": "occ_bc8483c70338a8e1",
        "new_occurrence_id": "occ_a73c7ed17c227fad",
    },
]


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


def snapshot_target(conn, target):
    return {
        "old_series": series(conn, target["old_series_id"]),
        "new_series": series(conn, target["new_series_id"]),
        "old_occurrence": occurrence(conn, target["old_occurrence_id"]),
        "new_occurrence": occurrence(conn, target["new_occurrence_id"]),
        "predicted_dates": rows(
            conn,
            """
            SELECT predicted_date_id, target_series_id, target_occurrence_id,
                   date_start, date_end, application_status
            FROM predicted_occurrence_dates
            WHERE target_event_name = ?
            """,
            (target["event_name"],),
        ),
        "historical_candidates": rows(
            conn,
            """
            SELECT candidate_id, target_series_id, target_occurrence_id, target_event_name
            FROM historical_promotion_candidates
            WHERE target_event_name = ?
            """,
            (target["event_name"],),
        ),
    }


def snapshot(conn):
    return {target["event_name"]: snapshot_target(conn, target) for target in MERGE_TARGETS}


def validate_preconditions(conn, target):
    issues = []
    old_series = series(conn, target["old_series_id"])
    new_series = series(conn, target["new_series_id"])
    old_occ = occurrence(conn, target["old_occurrence_id"])
    new_occ = occurrence(conn, target["new_occurrence_id"])
    label = target["event_name"]
    if not old_series:
        issues.append({"severity": "high", "issue_type": "missing_old_series", "event": label})
    if not new_series:
        issues.append({"severity": "high", "issue_type": "missing_new_series", "event": label})
    if not old_occ:
        issues.append({"severity": "high", "issue_type": "missing_old_occurrence", "event": label})
    if not new_occ:
        issues.append({"severity": "high", "issue_type": "missing_new_occurrence", "event": label})
    if old_occ and old_occ.get("series_id") != target["old_series_id"]:
        issues.append({"severity": "high", "issue_type": "unexpected_old_series", "event": label})
    if new_occ and new_occ.get("series_id") != target["new_series_id"]:
        issues.append({"severity": "high", "issue_type": "unexpected_new_series", "event": label})
    if old_occ and new_occ and old_occ.get("venue_id") != new_occ.get("venue_id"):
        issues.append({"severity": "high", "issue_type": "venue_mismatch", "event": label})
    if old_occ:
        conflict = scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM event_occurrences
            WHERE series_id = ?
              AND event_year = ?
              AND occurrence_id != ?
            """,
            (target["new_series_id"], old_occ.get("event_year"), target["old_occurrence_id"]),
        )
        if conflict:
            issues.append(
                {"severity": "high", "issue_type": "new_series_year_conflict", "event": label, "count": conflict}
            )
    return issues


def apply_one_merge(conn, target, now):
    conn.execute(
        """
        UPDATE event_occurrences
        SET series_id = ?, updated_at = ?
        WHERE occurrence_id = ?
        """,
        (target["new_series_id"], now, target["old_occurrence_id"]),
    )
    conn.execute(
        """
        UPDATE historical_promotion_candidates
        SET target_series_id = ?, updated_at = ?
        WHERE target_series_id = ? AND target_event_name = ?
        """,
        (target["new_series_id"], now, target["old_series_id"], target["event_name"]),
    )
    conn.execute(
        """
        UPDATE predicted_occurrence_dates
        SET target_series_id = ?, target_occurrence_id = ?,
            application_status = 'superseded_by_curated', updated_at = ?
        WHERE target_series_id = ? AND target_event_name = ?
        """,
        (target["new_series_id"], target["new_occurrence_id"], now, target["old_series_id"], target["event_name"]),
    )
    conn.execute(
        """
        UPDATE notion_sync_jobs
        SET status = 'superseded_by_curated', result_json = ?
        WHERE target_table = 'predicted_occurrence_dates'
          AND target_id IN (
            SELECT predicted_date_id FROM predicted_occurrence_dates WHERE target_event_name = ?
          )
          AND status = 'pending'
        """,
        (
            json.dumps(
                {
                    "reviewed_by": "apply_2026_series_split_merge.py",
                    "reviewed_at": now,
                    "reason": "curated_2026_occurrence_exists_after_series_merge",
                    "curated_occurrence_id": target["new_occurrence_id"],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            target["event_name"],
        ),
    )
    conn.execute(
        """
        UPDATE external_record_links
        SET master_id = ?
        WHERE master_table = 'event_series' AND master_id = ?
        """,
        (target["new_series_id"], target["old_series_id"]),
    )
    merged_name = f"{target['event_name']}（統合済み）"
    conn.execute(
        """
        UPDATE event_series
        SET canonical_name = ?, normalized_name = ?, status = 'merged', updated_at = ?
        WHERE series_id = ?
        """,
        (merged_name, normalize_text(merged_name), now, target["old_series_id"]),
    )


def apply_merge(conn, now):
    before = snapshot(conn)
    pre_issues = []
    for target in MERGE_TARGETS:
        pre_issues.extend(validate_preconditions(conn, target))
    if any(issue["severity"] == "high" for issue in pre_issues):
        return before, before, pre_issues

    for target in MERGE_TARGETS:
        apply_one_merge(conn, target, now)

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
    for target in MERGE_TARGETS:
        label = target["event_name"]
        old_occ = occurrence(conn, target["old_occurrence_id"])
        if not old_occ or old_occ.get("series_id") != target["new_series_id"]:
            issues.append({"severity": "high", "issue_type": "occurrence_not_merged", "event": label, "occurrence": old_occ})
        predicted = rows(
            conn,
            """
            SELECT predicted_date_id, target_series_id, target_occurrence_id, application_status
            FROM predicted_occurrence_dates
            WHERE target_event_name = ?
            """,
            (label,),
        )
        for row in predicted:
            if row["target_series_id"] != target["new_series_id"] or row["target_occurrence_id"] != target["new_occurrence_id"]:
                issues.append({"severity": "high", "issue_type": "prediction_not_relinked", "event": label, "row": row})
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
            {"severity": "medium", "issue_type": "duplicate_active_series_names_remain", "rows": duplicate_active}
        )
    return issues


def render_markdown(result):
    before = result["before"]
    after = result["after"]
    lines = [
        "# 2026 series split merge report",
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
        "## Changes",
        "",
        "| event | old occurrence series (before → after) | old series status (before → after) |",
        "| --- | --- | --- |",
    ]
    for target in MERGE_TARGETS:
        label = target["event_name"]
        b = before.get(label, {})
        a = after.get(label, {})
        b_occ = (b.get("old_occurrence") or {}).get("series_id")
        a_occ = (a.get("old_occurrence") or {}).get("series_id")
        b_status = (b.get("old_series") or {}).get("status")
        a_status = (a.get("old_series") or {}).get("status")
        lines.append(f"| {label} | {b_occ} → {a_occ} | {b_status} → {a_status} |")
    lines.append("")
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
    if args.apply and committed:
        refresh_manifest_database_state(args.master_db, updated_at=now)

    result = {
        "generated_by": "apply_2026_series_split_merge.py",
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
        "series split merge: "
        f"mode={result['mode']} "
        f"duplicate_series={result['summary']['duplicate_series_name_count']} "
        f"issues={result['summary']['issues_by_severity']}"
    )
    return 1 if result["summary"]["issues_by_severity"].get("high") else 0


if __name__ == "__main__":
    raise SystemExit(main())
