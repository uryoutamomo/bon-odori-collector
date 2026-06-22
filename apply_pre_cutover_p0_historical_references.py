"""Apply reviewed P0 historical reference dates to the master RDB.

This helper intentionally does not confirm 2026 dates. It only records prior
year dates in occurrence_dates as historical_reference rows for future review
and prediction work. Default mode writes to a copied SQLite DB.
"""

import argparse
import json
import shutil
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from master_db import MASTER_DB, refresh_manifest_database_state, stable_id, table_counts


DATA = Path("data")
PLAN_JSON = DATA / "pre_cutover_p0_apply_plan_post_rdb_state.json"
OUT_DB = DATA / "pre_cutover_p0_historical_references_dry_run.sqlite"
OUT_JSON = DATA / "pre_cutover_p0_historical_references_apply_report.json"
OUT_MD = DATA / "pre_cutover_p0_historical_references_apply_report.md"
BACKUP_DIR = DATA / "backups"
CONFIRM = "APPLY PRE CUTOVER P0 HISTORICAL REFERENCES"


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


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


def occurrence(conn, occurrence_id):
    found = rows(
        conn,
        """
        SELECT o.occurrence_id, o.event_year, o.display_name, o.date_start,
               o.date_end, o.date_status, o.source_url, s.canonical_name AS series_name
        FROM event_occurrences o
        JOIN event_series s ON s.series_id = o.series_id
        WHERE o.occurrence_id = ?
        """,
        (occurrence_id,),
    )
    return found[0] if found else None


def historical_plan_rows(plan):
    return [
        row
        for row in plan.get("rows") or []
        if row.get("bucket") == "historical_reference_only"
           and row.get("historical_date_start")
           and row.get("occurrence_id")
    ]


def build_plan(conn, plan):
    planned = []
    skipped = []
    for row in historical_plan_rows(plan):
        target = occurrence(conn, row["occurrence_id"])
        if not target:
            skipped.append({**row, "skip_reason": "missing_target_occurrence"})
            continue
        target_year = int(target["event_year"])
        historical_year = int(str(row["historical_date_start"])[:4])
        if historical_year >= target_year:
            skipped.append({**row, "skip_reason": "not_before_target_occurrence_year"})
            continue
        date_start = row["historical_date_start"]
        date_end = row.get("historical_date_end") or ""
        exists = scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM occurrence_dates
            WHERE occurrence_id = ?
              AND date_start = ?
              AND COALESCE(date_end, '') = ?
              AND date_type = 'historical_reference'
            """,
            (row["occurrence_id"], date_start, date_end),
        )
        if exists:
            skipped.append({**row, "skip_reason": "historical_reference_already_exists"})
            continue
        occurrence_date_id = stable_id(
            "odate",
            "pre_cutover_p0_historical_reference",
            row["occurrence_id"],
            date_start,
            date_end,
            row.get("source_url") or row.get("current_source_url") or "",
        )
        planned.append(
            {
                "occurrence_date_id": occurrence_date_id,
                "occurrence_id": row["occurrence_id"],
                "event_name": row["event_name"],
                "target_occurrence_year": target_year,
                "historical_year": historical_year,
                "date_start": date_start,
                "date_end": date_end,
                "confidence": row.get("confidence") or "unknown",
                "historical_venue": row.get("historical_venue") or "",
                "source_url": row.get("source_url") or row.get("current_source_url") or "",
                "basis": {
                    "source": "pre_cutover_p0_apply_plan",
                    "source_plan": "build_pre_cutover_p0_apply_plan.py",
                    "event_name": row["event_name"],
                    "target_occurrence_id": row["occurrence_id"],
                    "target_occurrence_year": target_year,
                    "historical_year": historical_year,
                    "historical_venue_name": row.get("historical_venue") or "",
                    "source_url": row.get("source_url") or row.get("current_source_url") or "",
                    "recommended_action": row.get("recommended_action") or "",
                    "requires_human_review": bool(row.get("requires_human_review")),
                    "does_not_confirm_target_year": True,
                },
            }
        )
    return planned, skipped


def apply_plan(conn, planned, now):
    for item in planned:
        conn.execute(
            """
            INSERT INTO occurrence_dates(
              occurrence_date_id, occurrence_id, date_start, date_end, date_type,
              confidence, basis, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["occurrence_date_id"],
                item["occurrence_id"],
                item["date_start"],
                item["date_end"] or None,
                "historical_reference",
                item["confidence"],
                json.dumps(item["basis"], ensure_ascii=False, sort_keys=True),
                now,
            ),
        )


def consistency_checks(conn, planned):
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
    for item in planned:
        exists = scalar(
            conn,
            "SELECT COUNT(*) FROM occurrence_dates WHERE occurrence_date_id = ?",
            (item["occurrence_date_id"],),
        )
        if not exists:
            issues.append(
                {
                    "severity": "high",
                    "issue_type": "historical_reference_missing_after_apply",
                    "occurrence_date_id": item["occurrence_date_id"],
                }
            )
    return issues


def render_markdown(result):
    lines = [
        "# Pre-cutover P0 historical references apply report",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- target_db: `{result['outputs']['target_db']}`",
        f"- dry_run_db: `{result['outputs']['dry_run_db']}`",
        f"- backup_db: `{result['outputs']['backup_db']}`",
        f"- db_committed: {result['write_guard']['db_committed']}",
        f"- rolled_back: {result['write_guard']['rolled_back']}",
        f"- planned_count: {result['summary']['planned_count']}",
        f"- applied_count: {result['summary']['applied_count']}",
        f"- skipped_count: {result['summary']['skipped_count']}",
        f"- issues_by_severity: {result['summary']['issues_by_severity']}",
        f"- historical_reference_dates: {result['summary']['historical_reference_dates']}",
        "",
        "| event | historical date | venue | source |",
        "| --- | --- | --- | --- |",
    ]
    for item in result["applied"]:
        date = item["date_start"]
        if item.get("date_end"):
            date = f"{date} to {item['date_end']}"
        lines.append(
            f"| {item['event_name']} | {date} | {item.get('historical_venue', '')} | {item.get('source_url', '')} |"
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
    plan = load_json(args.plan_json, {})
    target_db = Path(args.master_db if args.apply else args.out_db)
    backup = ""
    if args.apply:
        backup = str(backup_db(args.master_db, now))
    else:
        copy_db(args.master_db, args.out_db)

    with sqlite3.connect(target_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        planned, skipped = build_plan(conn, plan)
        apply_plan(conn, planned, now)
        issues = consistency_checks(conn, planned)
        has_high_issue = any(issue.get("severity") == "high" for issue in issues)
        if args.apply and has_high_issue:
            conn.rollback()
            committed = False
            rolled_back = True
        else:
            conn.commit()
            committed = bool(args.apply)
            rolled_back = False
        historical_reference_dates = scalar(
            conn,
            "SELECT COUNT(*) FROM occurrence_dates WHERE date_type = 'historical_reference'",
        )
        counts = table_counts(conn)
    if args.apply and committed:
        refresh_manifest_database_state(args.master_db, updated_at=now)

    result = {
        "generated_by": "apply_pre_cutover_p0_historical_references.py",
        "generated_at": now,
        "mode": "apply" if args.apply else "dry_run",
        "inputs": {"plan_json": str(args.plan_json), "master_db": str(args.master_db)},
        "outputs": {
            "target_db": str(target_db),
            "dry_run_db": "" if args.apply else str(args.out_db),
            "backup_db": backup,
            "out_json": str(args.out_json),
            "out_md": str(args.out_md),
        },
        "write_guard": {
            "db_committed": committed,
            "rolled_back": rolled_back,
            "notion_written": False,
            "public_json_written": False,
            "does_not_confirm_target_year": True,
        },
        "summary": {
            "planned_count": len(planned),
            "applied_count": len(planned) if not rolled_back else 0,
            "skipped_count": len(skipped),
            "issues_by_severity": dict(Counter(issue["severity"] for issue in issues)),
            "historical_reference_dates": historical_reference_dates,
            "table_counts": counts,
        },
        "applied": planned if not rolled_back else [],
        "skipped": skipped,
        "issues": issues,
    }
    write_json(args.out_json, result)
    Path(args.out_md).write_text(render_markdown(result), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-json", default=str(PLAN_JSON))
    parser.add_argument("--master-db", default=str(MASTER_DB))
    parser.add_argument("--out-db", default=str(OUT_DB))
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    result = run(args)
    print(
        "pre-cutover P0 historical references: "
        f"mode={result['mode']} applied={result['summary']['applied_count']} "
        f"skipped={result['summary']['skipped_count']} "
        f"historical_reference_dates={result['summary']['historical_reference_dates']} "
        f"issues={result['summary']['issues_by_severity']}"
    )


if __name__ == "__main__":
    main()
