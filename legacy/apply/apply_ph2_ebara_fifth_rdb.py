#!/usr/bin/env python3
"""Apply the reviewed Ph2 Ebara fifth update to the master RDB.

Default mode writes only to a copied SQLite DB. Production writes require
--apply and the confirmation phrase. This path is RDB-primary and does not
create Notion sync jobs or write public JSON.
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
from build_ph2_ebara_fifth_venue_plan import (
    DATE_END,
    DATE_START,
    EVENT_NAME,
    GEOCODE_MATCHED_TITLE,
    GEOCODE_SOURCE,
    LATITUDE,
    LONGITUDE,
    NEW_VENUE_ADDRESS,
    NEW_VENUE_AREA,
    NEW_VENUE_NAME,
    SOURCE_URL,
)
from master_db import MASTER_DB, connect_existing, normalize_text, refresh_manifest_database_state, stable_id, table_counts


DATA = Path("data")
OUT_DB = DATA / "ph2_ebara_fifth_apply_dry_run.sqlite"
OUT_JSON = DATA / "ph2_ebara_fifth_apply_report.json"
OUT_MD = DATA / "ph2_ebara_fifth_apply_report.md"
BACKUP_DIR = DATA / "backups"
CONFIRM_PHRASE = "APPLY PH2 EBARA FIFTH RDB"
SCRIPT_NAME = "apply_ph2_ebara_fifth_rdb.py"


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


def target_occurrence(conn):
    result = rows(
        conn,
        """
        SELECT o.occurrence_id, o.series_id, o.event_year, o.display_name,
               o.venue_id, v.canonical_name AS venue_name, v.address AS venue_address,
               o.date_start, o.date_end, o.date_status, o.lifecycle_status,
               o.confidence, o.source_kind, o.source_url
        FROM event_occurrences o
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE o.display_name = ?
          AND o.event_year = 2026
        """,
        (EVENT_NAME,),
    )
    if len(result) != 1:
        raise ValueError(f"expected exactly one target occurrence for {EVENT_NAME}, got {len(result)}")
    return result[0]


def venue_by_exact_name_address(conn):
    result = rows(
        conn,
        """
        SELECT venue_id, canonical_name, address, latitude, longitude
        FROM venues
        WHERE normalized_name = ?
          AND address = ?
        """,
        (normalize_text(NEW_VENUE_NAME), NEW_VENUE_ADDRESS),
    )
    return result[0] if result else None


def ensure_new_venue(conn, now):
    existing = venue_by_exact_name_address(conn)
    venue_id = stable_id("ven", NEW_VENUE_NAME, NEW_VENUE_ADDRESS)
    if existing:
        conn.execute(
            """
            UPDATE venues
            SET canonical_name = ?,
                area = ?,
                source_url = ?,
                latitude = ?,
                longitude = ?,
                review_status = 'active',
                updated_at = ?
            WHERE venue_id = ?
            """,
            (
                NEW_VENUE_NAME,
                NEW_VENUE_AREA,
                SOURCE_URL,
                LATITUDE,
                LONGITUDE,
                now,
                existing["venue_id"],
            ),
        )
        venue_id = existing["venue_id"]
        created = False
    else:
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
                NEW_VENUE_NAME,
                normalize_text(NEW_VENUE_NAME),
                NEW_VENUE_AREA,
                NEW_VENUE_ADDRESS,
                "",
                "",
                "",
                "",
                SOURCE_URL,
                LATITUDE,
                LONGITUDE,
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
        (venue_id, NEW_VENUE_NAME, normalize_text(NEW_VENUE_NAME), "canonical", "manual"),
    )
    return venue_id, created


def occurrence_state(conn, occurrence_id):
    return rows(
        conn,
        """
        SELECT o.*, v.canonical_name AS venue_name, v.address AS venue_address,
               v.latitude AS venue_latitude, v.longitude AS venue_longitude
        FROM event_occurrences o
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE o.occurrence_id = ?
        """,
        (occurrence_id,),
    )[0]


def apply_change(conn, now):
    target = target_occurrence(conn)
    old_venue_id = target["venue_id"]
    new_venue_id, venue_created = ensure_new_venue(conn, now)
    before = occurrence_state(conn, target["occurrence_id"])
    conn.execute(
        """
        UPDATE event_occurrences
        SET venue_id = ?,
            date_start = ?,
            date_end = ?,
            date_status = 'confirmed',
            confidence = 'high',
            source_kind = 'official_current_year',
            source_url = ?,
            updated_at = ?
        WHERE occurrence_id = ?
        """,
        (new_venue_id, DATE_START, DATE_END, SOURCE_URL, now, target["occurrence_id"]),
    )
    occurrence_date_id = stable_id("odate", target["occurrence_id"], DATE_START, DATE_END, SOURCE_URL)
    conn.execute(
        """
        INSERT OR REPLACE INTO occurrence_dates(
          occurrence_date_id, occurrence_id, date_start, date_end, date_type,
          confidence, basis, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            occurrence_date_id,
            target["occurrence_id"],
            DATE_START,
            DATE_END,
            "confirmed",
            "high",
            SOURCE_URL,
            now,
        ),
    )
    after = occurrence_state(conn, target["occurrence_id"])
    return {
        "occurrence_id": target["occurrence_id"],
        "old_venue_id": old_venue_id,
        "new_venue_id": new_venue_id,
        "venue_created": venue_created,
        "before": before,
        "after": after,
        "inserted_occurrence_date_id": occurrence_date_id,
    }


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
    venue_count = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM venues
        WHERE normalized_name = ?
          AND address = ?
        """,
        (normalize_text(NEW_VENUE_NAME), NEW_VENUE_ADDRESS),
    )
    if venue_count != 1:
        issues.append({"severity": "high", "issue_type": "new_venue_count_invalid", "count": venue_count})
    old_count = scalar(conn, "SELECT COUNT(*) FROM venues WHERE venue_id = ?", (applied["old_venue_id"],))
    if old_count != 1:
        issues.append({"severity": "high", "issue_type": "old_venue_not_preserved"})
    after = applied["after"]
    expected = {
        "venue_id": applied["new_venue_id"],
        "date_start": DATE_START,
        "date_end": DATE_END,
        "date_status": "confirmed",
        "confidence": "high",
        "source_kind": "official_current_year",
    }
    for key, value in expected.items():
        if (after.get(key) or "") != value:
            issues.append(
                {
                    "severity": "high",
                    "issue_type": "target_occurrence_value_mismatch",
                    "field": key,
                    "actual": after.get(key),
                    "expected": value,
                }
            )
    duplicate_dates = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM (
          SELECT occurrence_id, date_start, COALESCE(date_end, ''), date_type, COUNT(*) c
          FROM occurrence_dates
          WHERE occurrence_id = ?
          GROUP BY occurrence_id, date_start, COALESCE(date_end, ''), date_type
          HAVING c > 1
        )
        """,
        (applied["occurrence_id"],),
    )
    if duplicate_dates:
        issues.append(
            {
                "severity": "medium",
                "issue_type": "duplicate_occurrence_date_after_apply",
                "count": duplicate_dates,
            }
        )
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
    applied = result["applied"]
    before = applied["before"]
    after = applied["after"]
    lines = [
        "# Ph2 Ebara fifth RDB apply report",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- target_db: `{result['outputs']['target_db']}`",
        f"- dry_run_db: `{result['outputs']['dry_run_db']}`",
        f"- backup_db: `{result['outputs']['backup_db']}`",
        f"- db_committed: {result['write_guard']['db_committed']}",
        f"- rolled_back: {result['write_guard']['rolled_back']}",
        f"- issues_by_severity: {result['summary']['issues_by_severity']}",
        f"- audit_issues_by_severity: {result['summary']['audit_issues_by_severity']}",
        "",
        "## Change",
        "",
        "| target | before | after |",
        "| --- | --- | --- |",
        f"| venue | {before.get('venue_name')} ({before.get('venue_address')}) | {after.get('venue_name')} ({after.get('venue_address')}) |",
        f"| date | {before.get('date_start') or ''} to {before.get('date_end') or ''} / {before.get('date_status')} | {after.get('date_start')} to {after.get('date_end')} / {after.get('date_status')} |",
        f"| confidence | {before.get('confidence')} | {after.get('confidence')} |",
        "",
        "## New Venue",
        "",
        f"- venue_id: `{applied['new_venue_id']}`",
        f"- created_this_run: {applied['venue_created']}",
        f"- name: {NEW_VENUE_NAME}",
        f"- address: {NEW_VENUE_ADDRESS}",
        f"- latitude/longitude: {LATITUDE}, {LONGITUDE}",
        f"- geocode source: {GEOCODE_SOURCE} ({GEOCODE_MATCHED_TITLE})",
        "- old venue is preserved; this is not an alias of 旧杜松小学校.",
        "",
        "## Scope",
        "",
        "- Notion write-back: skipped",
        "- public JSON write: skipped",
        "- next step: public export dry-run and collector/site diff review",
        "",
    ]
    if result["issues"]:
        lines.extend(["## Issues", ""])
        for issue in result["issues"]:
            lines.append(f"- {issue['severity']} {issue['issue_type']}: {issue}")
        lines.append("")
    return "\n".join(lines)


def run(args):
    validate_apply_request(args)
    now = datetime.now(timezone.utc).isoformat()
    target_db = Path(args.master_db if args.apply else args.out_db)
    backup_path = ""
    if args.apply:
        # Prove the mutation on a temporary copy first. This catches high audit
        # issues before the source DB is opened for a write transaction.
        preflight_db = DATA / "ph2_ebara_fifth_apply_preflight.sqlite"
        copy_db(args.master_db, preflight_db)
        with connect_existing(preflight_db) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            preflight_applied = apply_change(conn, now)
            preflight_issues = consistency_checks(conn, preflight_applied)
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
        applied = apply_change(conn, now)
        issues = consistency_checks(conn, applied)
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
        "sources": {
            "master_db": str(args.master_db),
            "official_source_url": SOURCE_URL,
        },
        "outputs": {
            "target_db": str(target_db),
            "dry_run_db": "" if args.apply else str(args.out_db),
            "backup_db": backup_path,
            "json": str(args.out_json),
            "markdown": str(args.out_md),
        },
        "options": {
            "apply": bool(args.apply),
        },
        "write_guard": {
            "db_committed": committed,
            "rolled_back": rolled_back,
            "rollback_reason": "high_severity_issue" if rolled_back else "",
        },
        "summary": {
            "issues_count": len(issues),
            "issues_by_severity": issue_summary(issues),
            "audit_issues_by_severity": audit_result["issues_by_severity"],
            "table_counts": counts,
        },
        "source_evidence": {
            "event_name": EVENT_NAME,
            "date_start": DATE_START,
            "date_end": DATE_END,
            "venue_name": NEW_VENUE_NAME,
            "venue_address": NEW_VENUE_ADDRESS,
            "source_url": SOURCE_URL,
        },
        "applied": applied,
        "issues": issues,
        "audit": {
            "issue_count": audit_result["issue_count"],
            "issues_by_severity": audit_result["issues_by_severity"],
            "issues_by_type": audit_result["issues_by_type"],
        },
        "notion_writeback": {
            "enabled": False,
            "policy": "RDB primary; no Notion sync jobs are created.",
        },
        "public_json_write": {
            "enabled": False,
            "policy": "Run a separate public export dry-run after RDB review.",
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
        "ph2 ebara fifth rdb apply: "
        f"mode={result['mode']} "
        f"committed={result['write_guard']['db_committed']} "
        f"issues={result['summary']['issues_by_severity']} "
        f"audit={result['summary']['audit_issues_by_severity']} "
        f"target_db={result['outputs']['target_db']}"
    )
    return 1 if result["summary"]["issues_by_severity"].get("high") else 0


if __name__ == "__main__":
    raise SystemExit(main())
