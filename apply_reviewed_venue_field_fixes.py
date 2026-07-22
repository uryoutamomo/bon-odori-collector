"""Apply tightly reviewed venue fixes for remaining Ph2 core field gaps.

Default mode writes to a copied SQLite DB. Apply mode only performs the
explicit fixes listed in this file; it does not write Notion or public JSON.
"""

import argparse
import json
import shutil
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from master_rdb.master_db import MASTER_DB, connect_existing, normalize_text, refresh_manifest_database_state, stable_id, table_counts


DATA = Path("data")
OUT_DB = DATA / "reviewed_venue_field_fixes_dry_run.sqlite"
OUT_JSON = DATA / "reviewed_venue_field_fixes_apply_report.json"
OUT_MD = DATA / "reviewed_venue_field_fixes_apply_report.md"
BACKUP_DIR = DATA / "backups"
CONFIRM = "APPLY REVIEWED VENUE FIELD FIXES"


EXISTING_VENUE_FIXES = [
    {
        "occurrence_id": "occ_31e875571ef97fea",
        "event_name": "マロニエまつり盆踊り大会",
        "venue_id": "ven_e82a2aed94e45d29",
        "reason": "same-date curated 浅草橋マロニエまつり盆踊り occurrence already uses ヒューリック浅草橋ビル前",
    },
    {
        "occurrence_id": "occ_7a555fbc00d0c059",
        "event_name": "新橋こいち祭",
        "venue_id": "ven_331b917a98238b0d",
        "reason": "same official source and prior curated 第28回新橋こいち祭 盆踊り occurrence use 桜田公園",
    },
]


NEW_VENUE_FIXES = [
    {
        "occurrence_id": "occ_47fe4ad246321896",
        "event_name": "中野駅前大盆踊り大会",
        "venue": {
            "canonical_name": "中野セントラルパーク",
            "area": "中野区",
            "address": "",
            "access": "JR中央線、JR総武線、東京メトロ東西線「中野」駅より徒歩5分",
            "source_url": "https://www.nakano-centralpark.jp/access",
        },
        "occurrence_update": {
            "date_start": "2026-08-01",
            "date_end": "2026-08-02",
            "date_status": "confirmed",
            "confidence": "high",
            "source_kind": "official_current_year",
            "source_url": "https://nakabon.jp/",
        },
        "reason": "2026 official site confirms 中野セントラルパーク and 2026-08-01 to 2026-08-02",
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
        SELECT o.occurrence_id, o.series_id, o.display_name, o.event_year,
               o.venue_id, v.canonical_name AS venue_name,
               o.date_start, o.date_end, o.date_status, o.lifecycle_status,
               o.confidence, o.source_kind, o.source_url,
               s.usual_venue_id, s.canonical_name AS series_name
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
        """
        SELECT venue_id, canonical_name, area, address, access, source_url
        FROM venues
        WHERE venue_id = ?
        """,
        (venue_id,),
    )
    return result[0] if result else None


def find_venue_by_name_address(conn, data):
    result = rows(
        conn,
        """
        SELECT venue_id, canonical_name, area, address, access, source_url
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
    conn.execute(
        """
        INSERT OR IGNORE INTO venue_aliases(
          venue_id, alias, normalized_alias, source, confidence
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (venue_id, data["canonical_name"], normalize_text(data["canonical_name"]), "canonical", "manual"),
    )
    return venue_id, created


def build_plan(conn):
    planned = []
    skipped = []
    for fix in EXISTING_VENUE_FIXES:
        before = occurrence(conn, fix["occurrence_id"])
        candidate = venue(conn, fix["venue_id"])
        if not before:
            skipped.append({**fix, "skip_reason": "missing_occurrence"})
            continue
        if not candidate:
            skipped.append({**fix, "skip_reason": "missing_candidate_venue"})
            continue
        if before.get("venue_id"):
            skipped.append({**fix, "skip_reason": "occurrence_already_has_venue"})
            continue
        planned.append(
            {
                "action": "fill_existing_venue",
                "occurrence_id": fix["occurrence_id"],
                "event_name": fix["event_name"],
                "new_venue_id": candidate["venue_id"],
                "new_venue_name": candidate["canonical_name"],
                "set_series_usual_venue": not before.get("usual_venue_id"),
                "reason": fix["reason"],
                "before": before,
            }
        )
    for fix in NEW_VENUE_FIXES:
        before = occurrence(conn, fix["occurrence_id"])
        if not before:
            skipped.append({**fix, "skip_reason": "missing_occurrence"})
            continue
        if before.get("venue_id"):
            skipped.append({**fix, "skip_reason": "occurrence_already_has_venue"})
            continue
        planned.append(
            {
                "action": "create_venue_and_fill_occurrence",
                "occurrence_id": fix["occurrence_id"],
                "event_name": fix["event_name"],
                "venue": fix["venue"],
                "occurrence_update": fix["occurrence_update"],
                "set_series_usual_venue": not before.get("usual_venue_id"),
                "reason": fix["reason"],
                "before": before,
            }
        )
    return planned, skipped


def upsert_occurrence_date(conn, occurrence_id, update, now):
    date_start = update.get("date_start") or ""
    if not date_start:
        return None
    date_end = update.get("date_end") or ""
    source_url = update.get("source_url") or ""
    date_type = update.get("date_status") or "confirmed"
    occurrence_date_id = stable_id("odate", occurrence_id, date_start, date_end, source_url)
    conn.execute(
        """
        INSERT OR REPLACE INTO occurrence_dates(
          occurrence_date_id, occurrence_id, date_start, date_end, date_type,
          confidence, source_evidence_id, basis, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            occurrence_date_id,
            occurrence_id,
            date_start,
            date_end,
            date_type,
            update.get("confidence") or "high",
            None,
            update.get("source_kind") or "official_current_year",
            now,
        ),
    )
    return occurrence_date_id


def apply_plan(conn, planned, now):
    applied = []
    for item in planned:
        if item["action"] == "fill_existing_venue":
            venue_id = item["new_venue_id"]
            venue_created = False
            occurrence_update = {}
        else:
            venue_id, venue_created = ensure_new_venue(conn, item["venue"], now)
            occurrence_update = item["occurrence_update"]
        if occurrence_update:
            conn.execute(
                """
                UPDATE event_occurrences
                SET venue_id = ?,
                    date_start = ?,
                    date_end = ?,
                    date_status = ?,
                    confidence = ?,
                    source_kind = ?,
                    source_url = ?,
                    updated_at = ?
                WHERE occurrence_id = ?
                  AND venue_id IS NULL
                """,
                (
                    venue_id,
                    occurrence_update.get("date_start") or "",
                    occurrence_update.get("date_end") or "",
                    occurrence_update.get("date_status") or "confirmed",
                    occurrence_update.get("confidence") or "high",
                    occurrence_update.get("source_kind") or "official_current_year",
                    occurrence_update.get("source_url") or "",
                    now,
                    item["occurrence_id"],
                ),
            )
            occurrence_date_id = upsert_occurrence_date(conn, item["occurrence_id"], occurrence_update, now)
        else:
            conn.execute(
                """
                UPDATE event_occurrences
                SET venue_id = ?,
                    updated_at = ?
                WHERE occurrence_id = ?
                  AND venue_id IS NULL
                """,
                (venue_id, now, item["occurrence_id"]),
            )
            occurrence_date_id = None
        if item["set_series_usual_venue"]:
            conn.execute(
                """
                UPDATE event_series
                SET usual_venue_id = ?,
                    updated_at = ?
                WHERE series_id = ?
                  AND COALESCE(usual_venue_id, '') = ''
                """,
                (venue_id, now, item["before"]["series_id"]),
            )
        after = occurrence(conn, item["occurrence_id"])
        applied.append(
            {
                **item,
                "new_venue_id": venue_id,
                "venue_created": venue_created,
                "occurrence_date_id": occurrence_date_id or "",
                "after": after,
            }
        )
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
        update = item.get("occurrence_update") or {}
        if update and after.get("date_start") != update.get("date_start"):
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
        "# Reviewed venue field fixes apply report",
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
        f"- missing_date_start_count: {result['summary']['missing_date_start_count']}",
        "",
        "| action | event | venue | date update | reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in result["applied"]:
        update = item.get("occurrence_update") or {}
        date_update = ""
        if update.get("date_start"):
            date_update = f"{update['date_start']} to {update.get('date_end') or update['date_start']}"
        lines.append(
            f"| {item['action']} | {item['event_name']} | "
            f"{item.get('new_venue_name') or (item.get('venue') or {}).get('canonical_name')} "
            f"(`{item['new_venue_id']}`) | {date_update or '(none)'} | {item['reason']} |"
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
        missing_venue_count = scalar(conn, "SELECT COUNT(*) FROM event_occurrences WHERE venue_id IS NULL")
        missing_date_start_count = scalar(
            conn,
            "SELECT COUNT(*) FROM event_occurrences WHERE COALESCE(date_start, '') = ''",
        )
        counts = table_counts(conn)
    if args.apply and committed:
        refresh_manifest_database_state(args.master_db, updated_at=now)

    result = {
        "generated_by": "apply_reviewed_venue_field_fixes.py",
        "generated_at": now,
        "mode": "apply" if args.apply else "dry_run",
        "scope": (
            "source_master_db_apply_no_notion_no_public_json"
            if args.apply
            else "copied_sqlite_only_no_notion_no_public_json"
        ),
        "sources": {
            "master_db": str(args.master_db),
            "official_sources": [
                "https://nakabon.jp/",
                "https://www.nakano-centralpark.jp/access",
            ],
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
        "reviewed venue field fixes: "
        f"mode={result['mode']} "
        f"applied={result['summary']['applied_count']} "
        f"missing_venue={result['summary']['missing_venue_count']} "
        f"missing_date_start={result['summary']['missing_date_start_count']} "
        f"issues={result['summary']['issues_by_severity']}"
    )
    return 1 if result["summary"]["issues_by_severity"].get("high") else 0


if __name__ == "__main__":
    raise SystemExit(main())
