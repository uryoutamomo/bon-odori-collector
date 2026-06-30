"""Apply reviewed missing occurrence venue candidates to the master RDB.

Default mode writes to a copied SQLite DB. Apply mode fills venue_id for
rows classified as ready_existing_venue_candidate and can create explicitly
reviewed/auto-confirmed new venues. It does not write Notion or public JSON.
"""

import argparse
import json
import shutil
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from master_db import (
    MASTER_DB,
    connect_existing,
    normalize_text,
    refresh_manifest_database_state,
    stable_id,
    table_counts,
)


DATA = Path("data")
REVIEW_JSON = DATA / "missing_occurrence_venue_review.json"
OUT_DB = DATA / "reviewed_missing_occurrence_venues_dry_run.sqlite"
OUT_JSON = DATA / "reviewed_missing_occurrence_venues_apply_report.json"
OUT_MD = DATA / "reviewed_missing_occurrence_venues_apply_report.md"
BACKUP_DIR = DATA / "backups"
CONFIRM = "APPLY REVIEWED MISSING OCCURRENCE VENUES"


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
    result = rows(
        conn,
        """
        SELECT o.occurrence_id, o.series_id, s.usual_venue_id,
               o.display_name, o.event_year, o.venue_id,
               v.canonical_name AS venue_name, o.date_start, o.date_end,
               o.date_status, o.source_url
        FROM event_occurrences o
        JOIN event_series s ON s.series_id = o.series_id
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE o.occurrence_id = ?
        """,
        (occurrence_id,),
    )
    return result[0] if result else None


def venue(conn, venue_id):
    result = rows(
        conn,
        "SELECT venue_id, canonical_name, area, address FROM venues WHERE venue_id = ?",
        (venue_id,),
    )
    return result[0] if result else None


def find_venue_by_name_address(conn, data):
    result = rows(
        conn,
        """
        SELECT venue_id, canonical_name, area, address
        FROM venues
        WHERE normalized_name = ?
          AND COALESCE(address, '') = ?
        """,
        (normalize_text(data["canonical_name"]), data.get("address") or ""),
    )
    return result[0] if result else None


def ensure_new_venue(conn, data, now):
    existing = find_venue_by_name_address(conn, data)
    if existing:
        venue_id = existing["venue_id"]
        conn.execute(
            """
            UPDATE venues
            SET area = ?,
                access = ?,
                source_url = ?,
                review_status = 'active',
                updated_at = ?
            WHERE venue_id = ?
            """,
            (
                data.get("area") or "",
                data.get("access") or "",
                data.get("source_url") or "",
                now,
                venue_id,
            ),
        )
        created = False
    else:
        venue_id = stable_id(
            "ven",
            data["canonical_name"],
            data.get("address") or "",
            data.get("source_url") or "",
        )
        conn.execute(
            """
            INSERT INTO venues(
              venue_id, origin, canonical_name, normalized_name, area, address,
              access, scale, public_intro, past_memo, source_url,
              latitude, longitude, review_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                venue_id,
                "curated",
                data["canonical_name"],
                normalize_text(data["canonical_name"]),
                data.get("area") or "",
                data.get("address") or "",
                data.get("access") or "",
                "",
                "",
                "",
                data.get("source_url") or "",
                None,
                None,
                "active",
                now,
                now,
            ),
        )
        created = True

    aliases = [data["canonical_name"], *(data.get("aliases") or [])]
    for index, alias in enumerate(alias for alias in aliases if alias):
        conn.execute(
            """
            INSERT OR IGNORE INTO venue_aliases(
              venue_id, alias, normalized_alias, source, confidence
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                venue_id,
                alias,
                normalize_text(alias),
                "canonical" if index == 0 else "reviewed_missing_occurrence_venues",
                "manual" if index == 0 else "auto",
            ),
        )
    return venue_id, created


def ready_items(review):
    items = []
    for item in review.get("review") or []:
        if item.get("review_action") == "ready_existing_venue_candidate" and item.get("candidate_venue_id"):
            items.append(item)
        elif item.get("review_action") == "ready_new_venue_candidate" and item.get("candidate_venue_data"):
            items.append(item)
    return items


def build_plan(conn, review):
    planned = []
    skipped = []
    for item in ready_items(review):
        before = occurrence(conn, item["occurrence_id"])
        candidate = venue(conn, item.get("candidate_venue_id") or "")
        if not before:
            skipped.append({**item, "reason": "missing_occurrence"})
            continue
        if item.get("review_action") == "ready_existing_venue_candidate" and not candidate:
            skipped.append({**item, "reason": "missing_candidate_venue"})
            continue
        if before.get("venue_id"):
            skipped.append({**item, "reason": "occurrence_already_has_venue"})
            continue
        if item.get("review_action") == "ready_new_venue_candidate":
            venue_data = item.get("candidate_venue_data") or {}
            if not venue_data.get("canonical_name"):
                skipped.append({**item, "reason": "missing_candidate_venue_data"})
                continue
            planned.append(
                {
                    "action": "create_venue_and_fill_occurrence",
                    "occurrence_id": item["occurrence_id"],
                    "event_name": item["event_name"],
                    "event_year": item["event_year"],
                    "series_id": before["series_id"],
                    "set_series_usual_venue": not before.get("usual_venue_id"),
                    "old_venue_id": before.get("venue_id") or "",
                    "new_venue_id": "",
                    "new_venue_name": venue_data["canonical_name"],
                    "new_venue_address": venue_data.get("address") or "",
                    "candidate_venue_data": venue_data,
                    "confidence": item.get("confidence") or "unknown",
                    "reason": item.get("reason") or "",
                    "before": before,
                }
            )
            continue
        planned.append(
            {
                "action": "fill_existing_venue",
                "occurrence_id": item["occurrence_id"],
                "event_name": item["event_name"],
                "event_year": item["event_year"],
                "series_id": before["series_id"],
                "set_series_usual_venue": not before.get("usual_venue_id"),
                "old_venue_id": before.get("venue_id") or "",
                "new_venue_id": candidate["venue_id"],
                "new_venue_name": candidate["canonical_name"],
                "new_venue_address": candidate.get("address") or "",
                "confidence": item.get("confidence") or "unknown",
                "reason": item.get("reason") or "",
                "before": before,
            }
        )
    return planned, skipped


def apply_plan(conn, planned, now):
    applied = []
    for item in planned:
        if item["action"] == "create_venue_and_fill_occurrence":
            venue_id, venue_created = ensure_new_venue(conn, item["candidate_venue_data"], now)
            item["new_venue_id"] = venue_id
        else:
            venue_created = False
        cursor = conn.execute(
            """
            UPDATE event_occurrences
            SET venue_id = ?,
                updated_at = ?
            WHERE occurrence_id = ?
              AND venue_id IS NULL
            """,
            (item["new_venue_id"], now, item["occurrence_id"]),
        )
        if cursor.rowcount < 1:
            raise ValueError(f"failed to update occurrence venue: {item['occurrence_id']}")
        if item["set_series_usual_venue"]:
            conn.execute(
                """
                UPDATE event_series
                SET usual_venue_id = ?,
                    updated_at = ?
                WHERE series_id = ?
                  AND COALESCE(usual_venue_id, '') = ''
                """,
                (item["new_venue_id"], now, item["series_id"]),
            )
        after = occurrence(conn, item["occurrence_id"])
        applied.append({**item, "venue_created": venue_created, "after": after})
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
        if after.get("venue_id") != item["new_venue_id"]:
            issues.append(
                {
                    "severity": "high",
                    "issue_type": "venue_id_not_applied",
                    "occurrence_id": item["occurrence_id"],
                    "expected": item["new_venue_id"],
                    "actual": after.get("venue_id") or "",
                }
            )
    return issues


def render_markdown(result):
    lines = [
        "# Reviewed missing occurrence venues apply report",
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
        f"- missing_venue_count: {result['summary']['missing_venue_count']}",
        "",
        "| action | event | before | after | venue created | series usual venue updated | reason |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in result["applied"]:
        lines.append(
            f"| {item['action']} | {item['event_name']} | {item['old_venue_id'] or '(none)'} | "
            f"{item['new_venue_name']} (`{item['new_venue_id']}`) | "
            f"{item.get('venue_created', False)} | "
            f"{item['set_series_usual_venue']} | {item['reason']} |"
        )
    if result["skipped"]:
        lines.extend(["", "## Skipped", ""])
        for item in result["skipped"]:
            lines.append(f"- {item.get('event_name')}: {item.get('reason')}")
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
    review = load_json(args.review_json, {})
    target_db = Path(args.master_db if args.apply else args.out_db)
    backup = ""
    if args.apply:
        backup = str(backup_db(args.master_db, now))
    else:
        copy_db(args.master_db, args.out_db)

    with connect_existing(target_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        planned, skipped = build_plan(conn, review)
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
        missing_venue_count = scalar(conn, "SELECT COUNT(*) FROM event_occurrences WHERE venue_id IS NULL")
        counts = table_counts(conn)
    if args.apply and committed:
        refresh_manifest_database_state(args.master_db, updated_at=now)

    result = {
        "generated_by": "apply_reviewed_missing_occurrence_venues.py",
        "generated_at": now,
        "mode": "apply" if args.apply else "dry_run",
        "scope": (
            "source_master_db_apply_no_notion_no_public_json"
            if args.apply
            else "copied_sqlite_only_no_notion_no_public_json"
        ),
        "sources": {
            "master_db": str(args.master_db),
            "review_json": str(args.review_json),
        },
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
            "missing_venue_count": missing_venue_count,
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
    parser.add_argument("--review-json", type=Path, default=REVIEW_JSON)
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
        "reviewed missing occurrence venues: "
        f"mode={result['mode']} "
        f"applied={result['summary']['applied_count']} "
        f"missing_venue={result['summary']['missing_venue_count']} "
        f"issues={result['summary']['issues_by_severity']}"
    )
    return 1 if result["summary"]["issues_by_severity"].get("high") else 0


if __name__ == "__main__":
    raise SystemExit(main())
