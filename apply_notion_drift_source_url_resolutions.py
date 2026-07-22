"""Apply reviewed source_url resolutions from Notion drift review.

Default mode writes to a copied SQLite DB. Apply mode mutates only the master
RDB and does not write Notion or public JSON.
"""

import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from master_rdb.master_db import MASTER_DB, connect_existing, refresh_manifest_database_state


DATA = Path("data")
OUT_DB = DATA / "notion_drift_source_url_resolutions_dry_run.sqlite"
OUT_JSON = DATA / "notion_drift_source_url_resolutions_apply_report.json"
OUT_MD = DATA / "notion_drift_source_url_resolutions_apply_report.md"
BACKUP_DIR = DATA / "backups"
CONFIRM = "APPLY NOTION DRIFT SOURCE URL RESOLUTIONS"


SERIES_SOURCE_URL_UPDATES = [
    {
        "series_id": "ser_d0140daa64d7a876",
        "title": "SHIBUYA MIYASHITA PARK BON DANCE",
        "old_source_url": "https://miyashita-bondance.jp/2025/",
        "new_source_url": "https://mantan-web.jp/prtimes/article/20260527prt00m200000530a.html",
        "reason": "Notion 2026 page points to a dated PR TIMES/MANTAN source confirming the 2026 occurrence; replace the 2025 archive URL for series-level current evidence.",
    }
]


def rows(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def series_row(conn, series_id):
    result = rows(
        conn,
        """
        SELECT series_id, canonical_name, source_url
        FROM event_series
        WHERE series_id = ?
        """,
        (series_id,),
    )
    return result[0] if result else None


def build_plan(conn):
    planned = []
    skipped = []
    for item in SERIES_SOURCE_URL_UPDATES:
        before = series_row(conn, item["series_id"])
        if not before:
            skipped.append({**item, "skip_reason": "missing_event_series"})
            continue
        if (before.get("source_url") or "") != item["old_source_url"]:
            skipped.append(
                {
                    **item,
                    "skip_reason": "source_url_changed_since_review",
                    "actual_source_url": before.get("source_url") or "",
                }
            )
            continue
        planned.append({**item, "before": before})
    return planned, skipped


def apply_plan(conn, planned, now):
    applied = []
    for item in planned:
        cursor = conn.execute(
            """
            UPDATE event_series
            SET source_url = ?,
                updated_at = ?
            WHERE series_id = ?
              AND COALESCE(source_url, '') = ?
            """,
            (item["new_source_url"], now, item["series_id"], item["old_source_url"]),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"failed to update series source_url: {item['series_id']}")
        applied.append({**item, "after": series_row(conn, item["series_id"])})
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
        if (item.get("after") or {}).get("source_url") != item["new_source_url"]:
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
        "# Notion drift source URL resolutions apply report",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- applied: {result['applied']}",
        f"- applied_count: {result['summary']['applied_count']}",
        f"- skipped_count: {result['summary']['skipped_count']}",
        f"- issues_by_severity: {result['summary']['issues_by_severity']}",
        "- writes: Master RDB only; Notion and public JSON untouched",
        "",
        "| title | before | after | reason |",
        "| --- | --- | --- | --- |",
    ]
    for item in result["applied_items"]:
        lines.append(
            f"| {item['title']} | {item['old_source_url']} | {item['new_source_url']} | {item['reason']} |"
        )
    if result["skipped_items"]:
        lines.extend(["", "## Skipped", ""])
        for item in result["skipped_items"]:
            lines.append(f"- {item['title']}: {item['skip_reason']}")
    if result["issues"]:
        lines.extend(["", "## Issues", ""])
        for issue in result["issues"]:
            lines.append(f"- {issue['severity']} {issue['issue_type']}: {issue}")
    return "\n".join(lines) + "\n"


def run(args):
    if args.apply and args.confirm != CONFIRM:
        raise SystemExit(f"--confirm must be exactly: {CONFIRM}")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if args.apply:
        target_db = Path(args.master_db)
        backup = str(backup_db(target_db, now))
    else:
        target_db = Path(args.out_db)
        copy_db(args.master_db, target_db)
        backup = ""

    with connect_existing(target_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        planned, skipped = build_plan(conn)
        applied = apply_plan(conn, planned, now)
        issues = consistency_checks(conn, applied)
        if args.apply and any(issue.get("severity") == "high" for issue in issues):
            conn.rollback()
            committed = False
        else:
            conn.commit()
            committed = True

    if args.apply and committed:
        refresh_manifest_database_state(Path(args.master_db), updated_at=now)

    by_severity = {}
    for issue in issues:
        by_severity[issue["severity"]] = by_severity.get(issue["severity"], 0) + 1
    result = {
        "generated_by": "apply_notion_drift_source_url_resolutions.py",
        "generated_at": now,
        "mode": "apply" if args.apply else "dry_run",
        "applied": bool(args.apply and committed),
        "master_db": str(args.master_db),
        "target_db": str(target_db),
        "backup": backup,
        "summary": {
            "planned_count": len(planned),
            "applied_count": len(applied) if committed else 0,
            "skipped_count": len(skipped),
            "issues_by_severity": by_severity,
        },
        "applied_items": applied if committed else [],
        "skipped_items": skipped,
        "issues": issues,
    }
    write_json(args.out_json, result)
    Path(args.out_md).write_text(render_markdown(result), encoding="utf-8")
    print(
        "notion drift source URL resolutions: "
        f"mode={result['mode']} applied_count={result['summary']['applied_count']} "
        f"skipped_count={len(skipped)} out={args.out_json}"
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-db", type=Path, default=MASTER_DB)
    parser.add_argument("--out-db", type=Path, default=OUT_DB)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
