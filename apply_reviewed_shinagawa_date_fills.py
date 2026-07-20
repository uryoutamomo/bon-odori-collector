"""Apply reviewed 2026 Shinagawa City festival date fills to the master RDB.

Default mode writes to a copied SQLite DB. Apply mode only fills dates for
explicit current-year official matches; it does not write Notion or public JSON.
"""

import argparse
import json
import shutil
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from event_state_axes import update_occurrence_state_axes
from master_db import MASTER_DB, connect_existing, refresh_manifest_database_state, stable_id, table_counts


DATA = Path("data")
OUT_DB = DATA / "reviewed_shinagawa_date_fills_dry_run.sqlite"
OUT_JSON = DATA / "reviewed_shinagawa_date_fills_apply_report.json"
OUT_MD = DATA / "reviewed_shinagawa_date_fills_apply_report.md"
BACKUP_DIR = DATA / "backups"
CONFIRM = "APPLY REVIEWED SHINAGAWA DATE FILLS"
SOURCE_URL = "https://www.city.shinagawa.tokyo.jp/PC/shisetsu/shisetsu-kuyakusyo/shisetsu-kuyakusyo-chiiki/hpg000017088.html"


FIXES = [
    {
        "occurrence_id": "occ_10d1650413afccf4",
        "event_name": "品川区民まつり 八潮地区",
        "date_start": "2026-09-20",
        "date_end": "",
        "venue_name": "八潮公園",
        "source_excerpt": "日時 9月20日（日）午前11時～午後8時30分 / 会場 八潮公園多目的広場",
    },
    {
        "occurrence_id": "occ_ba6a308f4bcbfff2",
        "event_name": "品川区民まつり 荏原第三地区",
        "date_start": "2026-10-18",
        "date_end": "",
        "venue_name": "京陽小学校",
        "source_excerpt": "日時 10月18日（日）午前11時～午後3時 / 会場 京陽小学校",
    },
    {
        "occurrence_id": "occ_400f1f551ca689a7",
        "event_name": "品川区民まつり 荏原第四地区",
        "date_start": "2026-10-11",
        "date_end": "",
        "venue_name": "上神明小学校",
        "source_excerpt": "日時 10月11日（日）午前10時～正午、午後4時～午後7時30分 / 会場 上神明小学校",
    },
]


def rows(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def scalar(conn, query, params=()):
    return conn.execute(query, params).fetchone()[0]


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def occurrence(conn, occurrence_id):
    result = rows(
        conn,
        """
        SELECT o.occurrence_id, o.display_name, o.event_year, o.venue_id,
               v.canonical_name AS venue_name, o.date_start, o.date_end,
               o.date_status, o.lifecycle_status, o.confidence,
               o.source_kind, o.source_url
        FROM event_occurrences o
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE o.occurrence_id = ?
        """,
        (occurrence_id,),
    )
    return result[0] if result else None


def build_plan(conn):
    planned = []
    skipped = []
    for fix in FIXES:
        before = occurrence(conn, fix["occurrence_id"])
        if not before:
            skipped.append({**fix, "skip_reason": "missing_occurrence"})
            continue
        if before.get("date_start"):
            skipped.append({**fix, "skip_reason": "occurrence_already_has_date"})
            continue
        if before.get("event_year") != 2026:
            skipped.append({**fix, "skip_reason": "unexpected_event_year", "before": before})
            continue
        if fix["venue_name"] not in (before.get("venue_name") or ""):
            skipped.append({**fix, "skip_reason": "venue_name_mismatch", "before": before})
            continue
        planned.append({**fix, "before": before})
    return planned, skipped


def upsert_occurrence_date(conn, item, now):
    occurrence_date_id = stable_id(
        "odate",
        item["occurrence_id"],
        item["date_start"],
        item.get("date_end") or "",
        SOURCE_URL,
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO occurrence_dates(
          occurrence_date_id, occurrence_id, date_start, date_end, date_type,
          confidence, source_evidence_id, basis, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            occurrence_date_id,
            item["occurrence_id"],
            item["date_start"],
            item.get("date_end") or "",
            "confirmed",
            "high",
            None,
            "official_current_year",
            now,
        ),
    )
    return occurrence_date_id


def apply_plan(conn, planned, now):
    applied = []
    for item in planned:
        conn.execute(
            """
            UPDATE event_occurrences
            SET date_start = ?,
                date_end = ?,
                date_status = 'confirmed',
                confidence = 'high',
                source_kind = 'official_current_year',
                source_url = ?,
                updated_at = ?
            WHERE occurrence_id = ?
              AND COALESCE(date_start, '') = ''
            """,
            (
                item["date_start"],
                item.get("date_end") or "",
                SOURCE_URL,
                now,
                item["occurrence_id"],
            ),
        )
        update_occurrence_state_axes(conn, item["occurrence_id"], "confirmed", "confirmed")
        occurrence_date_id = upsert_occurrence_date(conn, item, now)
        after = occurrence(conn, item["occurrence_id"])
        applied.append({**item, "occurrence_date_id": occurrence_date_id, "after": after})
    return applied


def consistency_checks(conn, applied):
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
    for item in applied:
        after = item.get("after") or {}
        if after.get("date_start") != item["date_start"]:
            issues.append(
                {
                    "severity": "high",
                    "issue_type": "date_start_not_applied",
                    "occurrence_id": item["occurrence_id"],
                }
            )
    return issues


def render_markdown(result):
    lines = [
        "# Reviewed Shinagawa date fills apply report",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- target_db: `{result['outputs']['target_db']}`",
        f"- dry_run_db: `{result['outputs']['dry_run_db']}`",
        f"- backup_db: `{result['outputs']['backup_db']}`",
        f"- db_committed: {result['write_guard']['db_committed']}",
        f"- rolled_back: {result['write_guard']['rolled_back']}",
        f"- applied_count: {result['summary']['applied_count']}",
        f"- skipped_count: {result['summary']['skipped_count']}",
        f"- issues_by_severity: {result['summary']['issues_by_severity']}",
        f"- missing_date_start_count: {result['summary']['missing_date_start_count']}",
        "",
        "| event | date | venue | source excerpt |",
        "| --- | --- | --- | --- |",
    ]
    for item in result["applied"]:
        date_text = item["date_start"]
        if item.get("date_end"):
            date_text = f"{item['date_start']} to {item['date_end']}"
        lines.append(
            f"| {item['event_name']} | {date_text} | {item['venue_name']} | {item['source_excerpt']} |"
        )
    if result["skipped"]:
        lines.extend(["", "## Skipped", ""])
        for item in result["skipped"]:
            lines.append(f"- {item.get('event_name')}: {item.get('skip_reason')}")
    if result["issues"]:
        lines.extend(["", "## Issues", ""])
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
        planned, skipped = build_plan(conn)
        applied = apply_plan(conn, planned, now)
        issues = consistency_checks(conn, applied)
        has_high_issue = any(issue.get("severity") == "high" for issue in issues)
        if args.apply and has_high_issue:
            conn.rollback()
            committed = False
            rolled_back = True
            applied_out = []
        else:
            conn.commit()
            committed = True
            rolled_back = False
            applied_out = applied
        missing_date_start_count = scalar(
            conn,
            "SELECT COUNT(*) FROM event_occurrences WHERE COALESCE(date_start, '') = ''",
        )
        counts = table_counts(conn)
    if args.apply and committed:
        refresh_manifest_database_state(args.master_db, updated_at=now)

    result = {
        "generated_by": "apply_reviewed_shinagawa_date_fills.py",
        "generated_at": now,
        "mode": "apply" if args.apply else "dry_run",
        "scope": (
            "source_master_db_apply_no_notion_no_public_json"
            if args.apply
            else "copied_sqlite_only_no_notion_no_public_json"
        ),
        "sources": {"master_db": str(args.master_db), "official_source": SOURCE_URL},
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
            "planned_count": len(planned),
            "applied_count": len(applied_out),
            "skipped_count": len(skipped),
            "issues_count": len(issues),
            "issues_by_severity": dict(Counter(issue["severity"] for issue in issues)),
            "missing_date_start_count": missing_date_start_count,
            "table_counts": counts,
        },
        "applied": applied_out,
        "skipped": skipped,
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
        "reviewed Shinagawa date fills: "
        f"mode={result['mode']} "
        f"applied={result['summary']['applied_count']} "
        f"missing_date_start={result['summary']['missing_date_start_count']} "
        f"issues={result['summary']['issues_by_severity']}"
    )
    return 1 if result["summary"]["issues_by_severity"].get("high") else 0


if __name__ == "__main__":
    raise SystemExit(main())
