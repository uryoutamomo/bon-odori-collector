#!/usr/bin/env python3
"""Build a dry-run plan for the Ph2 Ebara fifth venue change.

This script is intentionally dry-run only. It copies the master RDB, inserts
the proposed new venue, updates the target occurrence in the copy, and writes
review material. Notion write-back is intentionally out of scope: the Ph2
direction is RDB-primary, with Notion treated as a legacy/read-only reference.
"""

import argparse
import json
import shutil
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from master_rdb.master_db import MASTER_DB, normalize_text, stable_id, table_counts


DATA = Path("data")
OUT_DB = DATA / "ph2_ebara_fifth_venue_plan.sqlite"
OUT_JSON = DATA / "ph2_ebara_fifth_venue_plan.json"
OUT_MD = DATA / "ph2_ebara_fifth_venue_plan.md"

SCRIPT_NAME = "build_ph2_ebara_fifth_venue_plan.py"
EVENT_NAME = "品川区民まつり 荏原第五地区"
SOURCE_URL = "https://www.city.shinagawa.tokyo.jp/PC/shisetsu/shisetsu-kuyakusyo/shisetsu-kuyakusyo-chiiki/hpg000017088.html"
NEW_VENUE_NAME = "杜松ホーム"
NEW_VENUE_ADDRESS = "東京都品川区豊町4-24-15"
NEW_VENUE_AREA = "品川区"
DATE_START = "2026-07-18"
DATE_END = "2026-07-19"
GEOCODE_SOURCE = "GSI AddressSearch"
GEOCODE_MATCHED_TITLE = "東京都品川区豊町四丁目２４番１５号"
LATITUDE = 35.605442
LONGITUDE = 139.722931


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


def target_occurrence(conn):
    result = rows(
        conn,
        """
        SELECT o.occurrence_id, o.series_id, o.event_year, o.display_name,
               o.venue_id, v.canonical_name AS venue_name, v.address AS venue_address,
               o.date_start, o.date_end, o.date_status, o.lifecycle_status,
               o.confidence, o.source_kind, o.source_url,
               l.external_id AS notion_page_id
        FROM event_occurrences o
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        LEFT JOIN external_record_links l
          ON l.system = 'notion'
         AND l.source_key = 'events'
         AND l.master_table = 'event_occurrences'
         AND l.master_id = o.occurrence_id
         AND l.relation_kind = 'primary'
        WHERE o.display_name = ?
          AND o.event_year = 2026
        """,
        (EVENT_NAME,),
    )
    if len(result) != 1:
        raise ValueError(f"expected exactly one target occurrence for {EVENT_NAME}, got {len(result)}")
    return result[0]


def venue_by_name(conn, name):
    return rows(
        conn,
        """
        SELECT venue_id, canonical_name, address, latitude, longitude
        FROM venues
        WHERE normalized_name = ?
        ORDER BY canonical_name
        """,
        (normalize_text(name),),
    )


def insert_new_venue(conn, now):
    venue_id = stable_id("ven", NEW_VENUE_NAME, NEW_VENUE_ADDRESS)
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
    conn.execute(
        """
        INSERT INTO venue_aliases(
          venue_id, alias, normalized_alias, source, confidence
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (venue_id, NEW_VENUE_NAME, normalize_text(NEW_VENUE_NAME), "canonical", "manual"),
    )
    return venue_id


def update_occurrence(conn, occurrence_id, venue_id, now):
    before = rows(
        conn,
        """
        SELECT o.*, v.canonical_name AS venue_name, v.address AS venue_address
        FROM event_occurrences o
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE o.occurrence_id = ?
        """,
        (occurrence_id,),
    )[0]
    conn.execute(
        """
        UPDATE event_occurrences
        SET venue_id = ?,
            date_start = ?,
            date_end = ?,
            date_status = 'confirmed',
            lifecycle_status = '確認済み',
            confidence = 'high',
            source_kind = 'official_current_year',
            source_url = ?,
            updated_at = ?
        WHERE occurrence_id = ?
        """,
        (venue_id, DATE_START, DATE_END, SOURCE_URL, now, occurrence_id),
    )
    occurrence_date_id = stable_id("odate", occurrence_id, DATE_START, DATE_END, SOURCE_URL)
    conn.execute(
        """
        INSERT OR REPLACE INTO occurrence_dates(
          occurrence_date_id, occurrence_id, date_start, date_end, date_type,
          confidence, basis, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (occurrence_date_id, occurrence_id, DATE_START, DATE_END, "confirmed", "high", SOURCE_URL, now),
    )
    after = rows(
        conn,
        """
        SELECT o.*, v.canonical_name AS venue_name, v.address AS venue_address
        FROM event_occurrences o
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE o.occurrence_id = ?
        """,
        (occurrence_id,),
    )[0]
    return before, after, occurrence_date_id


def consistency_checks(conn, old_venue_id, new_venue_id, occurrence_id):
    issues = []
    fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_rows:
        issues.append({"severity": "high", "issue_type": "foreign_key_check_failed", "count": len(fk_rows)})
    duplicate_new_venue = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM venues
        WHERE normalized_name = ?
          AND address = ?
        """,
        (normalize_text(NEW_VENUE_NAME), NEW_VENUE_ADDRESS),
    )
    if duplicate_new_venue != 1:
        issues.append(
            {
                "severity": "high",
                "issue_type": "new_venue_duplicate_or_missing",
                "count": duplicate_new_venue,
            }
        )
    old_exists = scalar(conn, "SELECT COUNT(*) FROM venues WHERE venue_id = ?", (old_venue_id,))
    if old_exists != 1:
        issues.append({"severity": "high", "issue_type": "old_venue_not_preserved"})
    occurrence_venue = scalar(
        conn,
        "SELECT venue_id FROM event_occurrences WHERE occurrence_id = ?",
        (occurrence_id,),
    )
    if occurrence_venue != new_venue_id:
        issues.append(
            {
                "severity": "high",
                "issue_type": "occurrence_venue_not_changed",
                "actual": occurrence_venue,
                "expected": new_venue_id,
            }
        )
    return issues


def render_markdown(result):
    before = result["occurrence"]["before"]
    after = result["occurrence"]["after"]
    lines = [
        "# Ph2 Ebara fifth venue-change plan",
        "",
        f"- generated_at: {result['generated_at']}",
        "- mode: dry_run_copied_sqlite_only",
        f"- master_db: `{result['sources']['master_db']}`",
        f"- dry_run_db: `{result['outputs']['dry_run_db']}`",
        f"- issues_by_severity: {result['summary']['issues_by_severity']}",
        "",
        "## Source Evidence",
        "",
        f"- event: {EVENT_NAME}",
        f"- official date: {DATE_START} to {DATE_END}",
        f"- official venue: {NEW_VENUE_NAME} ({NEW_VENUE_ADDRESS})",
        f"- source: {SOURCE_URL}",
        "",
        "## RDB Dry-Run Changes",
        "",
        "| target | before | after |",
        "| --- | --- | --- |",
        f"| venue | {before.get('venue_name')} ({before.get('venue_address')}) | {after.get('venue_name')} ({after.get('venue_address')}) |",
        f"| date | {before.get('date_start') or ''} to {before.get('date_end') or ''} / {before.get('date_status')} | {after.get('date_start')} to {after.get('date_end')} / {after.get('date_status')} |",
        "",
        "## New Venue",
        "",
        f"- venue_id: `{result['new_venue']['venue_id']}`",
        f"- canonical_name: {NEW_VENUE_NAME}",
        f"- address: {NEW_VENUE_ADDRESS}",
        f"- latitude/longitude: {LATITUDE}, {LONGITUDE}",
        f"- geocode source: {GEOCODE_SOURCE} ({GEOCODE_MATCHED_TITLE})",
        "- old venue is preserved; this is not an alias of 旧杜松小学校.",
        "",
        "## Notion Write-Back",
        "",
        "- skipped: this plan is RDB-primary and does not create or update Notion pages.",
        "- Notion remains a legacy/read-only reference unless a separate manual migration decision is made.",
        "",
        "## Public Export Follow-Up",
        "",
        "- After RDB apply, regenerate local public JSON from the master RDB and review the site diff before deploy.",
        "- Public deploy remains a separate Uchida-san approval step.",
    ]
    lines.extend(
        [
            "",
            "## Apply Sequence Proposal",
            "",
            "1. Review this dry-run plan with こと and 内田さん.",
            "2. RDB apply only: add 杜松ホーム, preserve 旧杜松小学校, update 荏原第五地区 occurrence.",
            "3. Regenerate local public JSON from the master RDB and review collector/site diffs.",
            "4. Deploy only after a separate public-site approval.",
            "",
        ]
    )
    if result["issues"]:
        lines.extend(["## Issues", ""])
        for issue in result["issues"]:
            lines.append(f"- {issue['severity']} {issue['issue_type']}: {issue}")
        lines.append("")
    return "\n".join(lines)


def run(args):
    now = datetime.now(timezone.utc).isoformat()
    copy_db(args.master_db, args.out_db)
    with sqlite3.connect(args.out_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        occurrence = target_occurrence(conn)
        old_venue_id = occurrence["venue_id"]
        existing_new_venues = venue_by_name(conn, NEW_VENUE_NAME)
        if existing_new_venues:
            raise ValueError(f"{NEW_VENUE_NAME} already exists in master copy: {existing_new_venues}")
        new_venue_id = insert_new_venue(conn, now)
        before, after, occurrence_date_id = update_occurrence(
            conn, occurrence["occurrence_id"], new_venue_id, now
        )
        issues = consistency_checks(conn, old_venue_id, new_venue_id, occurrence["occurrence_id"])
        counts = table_counts(conn)
        conn.commit()
    result = {
        "generated_by": SCRIPT_NAME,
        "generated_at": now,
        "mode": "dry_run_copied_sqlite_only",
        "sources": {
            "master_db": str(args.master_db),
            "official_source_url": SOURCE_URL,
        },
        "outputs": {
            "dry_run_db": str(args.out_db),
            "json": str(args.out_json),
            "markdown": str(args.out_md),
        },
        "summary": {
            "issues_count": len(issues),
            "issues_by_severity": dict(Counter(row["severity"] for row in issues)),
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
        "new_venue": {
            "venue_id": new_venue_id,
            "canonical_name": NEW_VENUE_NAME,
            "area": NEW_VENUE_AREA,
            "address": NEW_VENUE_ADDRESS,
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "geocode_source": GEOCODE_SOURCE,
            "geocode_matched_title": GEOCODE_MATCHED_TITLE,
        },
        "old_venue": {
            "venue_id": old_venue_id,
            "canonical_name": before.get("venue_name"),
            "address": before.get("venue_address"),
            "preserved": True,
        },
        "occurrence": {
            "occurrence_id": occurrence["occurrence_id"],
            "notion_page_id": occurrence.get("notion_page_id") or "",
            "before": before,
            "after": after,
            "inserted_occurrence_date_id": occurrence_date_id,
        },
        "notion_writeback": {
            "enabled": False,
            "policy": "RDB primary; do not create or update Notion pages for this Ph2 path.",
        },
        "public_export_follow_up": {
            "required": True,
            "note": "Regenerate local public JSON from the master RDB and review diffs before any deploy.",
        },
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
    args = parser.parse_args()
    result = run(args)
    print(
        "ph2 ebara fifth venue plan: "
        f"issues={result['summary']['issues_count']} "
        f"new_venue={result['new_venue']['venue_id']} "
        f"dry_run_db={result['outputs']['dry_run_db']}"
    )
    return 1 if result["summary"]["issues_by_severity"].get("high") else 0


if __name__ == "__main__":
    raise SystemExit(main())
