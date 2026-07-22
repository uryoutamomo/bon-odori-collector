"""Fill missing event_series.source_url from its sourced occurrences.

Apply mode mutates only the master RDB. It does not write Notion or public JSON.
"""

import argparse
import json
import shutil
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from master_rdb.master_db import MASTER_DB, connect_existing, refresh_manifest_database_state


DATA = Path("data")
OUT_DB = DATA / "series_source_url_inheritance_dry_run.sqlite"
OUT_JSON = DATA / "series_source_url_inheritance_apply_report.json"
OUT_MD = DATA / "series_source_url_inheritance_apply_report.md"
BACKUP_DIR = DATA / "backups"
CONFIRM = "APPLY SERIES SOURCE URL INHERITANCE"


def rows(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


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


def build_plan(conn):
    candidates = rows(
        conn,
        """
        SELECT s.series_id, s.canonical_name, s.source_url AS old_source_url,
               o.occurrence_id, o.display_name, o.source_url AS new_source_url
        FROM event_series s
        JOIN event_occurrences o ON o.series_id = s.series_id
        WHERE COALESCE(s.source_url, '') = ''
          AND COALESCE(o.source_url, '') != ''
        ORDER BY s.canonical_name, o.event_year DESC, o.updated_at DESC
        """,
    )
    by_series = {}
    skipped = []
    for item in candidates:
        existing = by_series.get(item["series_id"])
        if not existing:
            by_series[item["series_id"]] = item
            continue
        if existing["new_source_url"] != item["new_source_url"]:
            skipped.append({**item, "skip_reason": "multiple_occurrence_source_urls"})
    return list(by_series.values()), skipped


def apply_plan(conn, planned, now):
    applied = []
    for item in planned:
        cursor = conn.execute(
            """
            UPDATE event_series
            SET source_url = ?,
                updated_at = ?
            WHERE series_id = ?
              AND COALESCE(source_url, '') = ''
            """,
            (item["new_source_url"], now, item["series_id"]),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"failed to update event_series source_url: {item['series_id']}")
        after = rows(
            conn,
            "SELECT series_id, canonical_name, source_url FROM event_series WHERE series_id = ?",
            (item["series_id"],),
        )[0]
        applied.append({**item, "after": after})
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
        if item["after"]["source_url"] != item["new_source_url"]:
            issues.append(
                {
                    "severity": "high",
                    "issue_type": "source_url_not_applied",
                    "series_id": item["series_id"],
                }
            )
    return issues


def render_markdown(result):
    lines = [
        "# Series source URL inheritance apply report",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- target_db: `{result['outputs']['target_db']}`",
        f"- backup_db: `{result['outputs']['backup_db']}`",
        f"- applied_count: {result['summary']['applied_count']}",
        f"- skipped_count: {result['summary']['skipped_count']}",
        f"- issues_by_severity: {result['summary']['issues_by_severity']}",
        f"- missing_series_source_url_count: {result['summary']['missing_series_source_url_count']}",
        "",
        "| series | occurrence | source_url |",
        "| --- | --- | --- |",
    ]
    for item in result["applied"]:
        lines.append(f"| {item['canonical_name']} | {item['display_name']} | {item['new_source_url']} |")
    if result["skipped"]:
        lines.extend(["", "## Skipped", ""])
        for item in result["skipped"]:
            lines.append(f"- {item['canonical_name']}: {item['skip_reason']}")
    if result["issues"]:
        lines.extend(["", "## Issues", ""])
        for issue in result["issues"]:
            lines.append(f"- {issue['severity']} {issue['issue_type']}: {issue}")
    lines.append("")
    return "\n".join(lines)


def run(args):
    if args.apply and args.confirm != CONFIRM:
        raise ValueError(f"--apply requires --confirm '{CONFIRM}'")
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
        if args.apply and any(issue.get("severity") == "high" for issue in issues):
            conn.rollback()
            committed = False
            applied_out = []
        else:
            conn.commit()
            committed = True
            applied_out = applied
        missing_series_source_url_count = conn.execute(
            "SELECT COUNT(*) FROM event_series WHERE COALESCE(source_url, '') = ''"
        ).fetchone()[0]

    if args.apply and committed:
        refresh_manifest_database_state(args.master_db, updated_at=now)

    result = {
        "generated_by": "apply_series_source_url_inheritance.py",
        "generated_at": now,
        "mode": "apply" if args.apply else "dry_run",
        "scope": "master_db_series_source_url_only_no_notion_no_public_json",
        "outputs": {
            "target_db": str(target_db),
            "backup_db": backup,
        },
        "summary": {
            "planned_count": len(planned),
            "applied_count": len(applied_out),
            "skipped_count": len(skipped),
            "issues_by_severity": dict(Counter(issue["severity"] for issue in issues)),
            "missing_series_source_url_count": missing_series_source_url_count,
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
        "series source URL inheritance: "
        f"mode={result['mode']} "
        f"applied={result['summary']['applied_count']} "
        f"missing_series_source_url={result['summary']['missing_series_source_url_count']} "
        f"issues={result['summary']['issues_by_severity']}"
    )
    return 1 if result["summary"]["issues_by_severity"].get("high") else 0


if __name__ == "__main__":
    raise SystemExit(main())
