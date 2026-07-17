"""Apply reviewed 2026 public event candidates and duplicate suppressions.

Default mode writes to a copied SQLite DB. Apply mode only performs the
explicit reviewed changes listed in this file; it does not write Notion or
deploy the public site.
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
OUT_DB = DATA / "reviewed_public_event_candidates_20260701_dry_run.sqlite"
OUT_JSON = DATA / "reviewed_public_event_candidates_20260701_apply_report.json"
OUT_MD = DATA / "reviewed_public_event_candidates_20260701_apply_report.md"
BACKUP_DIR = DATA / "backups"
CONFIRM = "APPLY REVIEWED PUBLIC EVENT CANDIDATES 20260701"


MERGES = [
    {
        "old_series_id": "ser_580faf087899af86",
        "old_occurrence_id": "occ_df78a1d188e68698",
        "new_series_id": "ser_75978db01c455e34",
        "new_occurrence_id": "occ_da7ddce69ae96791",
        "event_name": "品川第二地区 区民まつり・品川青年会 盆踊り大会（天妙国寺）",
        "merged_name": "品川第二地区 区民まつり・品川青年会 盆踊り大会（天妙国寺）（統合済み）",
        "reason": "same 2026 Shinagawa district event is already confirmed as 品川区民まつり 品川第二地区",
    },
    {
        "old_series_id": "ser_b3604da8bab18695",
        "old_occurrence_id": "occ_ef4845b7ed9ac900",
        "new_series_id": "ser_e763e24c3496cf82",
        "new_occurrence_id": "occ_07f775ba65031a6e",
        "event_name": "えどぐらん（江東区）",
        "merged_name": "えどぐらん（江東区）（統合済み: 京橋盆踊り）",
        "reason": "source URL is the 京橋盆踊り2025 page; the 江東区/えどぐらん row is a misnamed duplicate",
    },
]


NEW_EVENTS = [
    {
        "event_name": "木場二丁目 盆踊り大会",
        "venue_id": "ven_4841416eec0bedc4",
        "venue_name": "木場二丁目公園",
        "date_start": "2026-07-17",
        "date_end": "2026-07-18",
        "source_kind": "instagram_current_year",
        "source_url": "https://www.instagram.com/p/DZm2_6mytN3/",
        "series_source_url": "https://www.instagram.com/p/DZm2_6mytN3/",
        "public_intro": "木場二丁目公園で開かれる地域の盆踊り大会。",
        "detail": "\n".join(
            [
                "2026年告知確認。Instagram投稿本文で、会場: 木場二丁目公園、日時: 7月17日(金)18:00-21:00、7月18日(土)18:00-20:30を確認。",
                "- 出典URL: https://www.instagram.com/p/DZm2_6mytN3/",
            ]
        ),
        "confidence": "high",
        "reason": "current-year Instagram announcement gives date, time, and venue; venue already exists in master RDB",
    },
    {
        "event_name": "木場一・六町会 盆踊り大会",
        "venue": {
            "canonical_name": "深川ギャザリアセンタープラザ",
            "area": "江東区",
            "address": "東京都江東区木場1-5-10",
            "access": "東京メトロ東西線「木場」駅4a・b出口徒歩約2分",
            "source_url": "https://www.gatharia.jp/access/",
            "aliases": ["深川ギャザリア センタープラザ", "深川ギャザリア"],
        },
        "date_start": "2026-07-18",
        "date_end": "2026-07-19",
        "source_kind": "local_media_press_release_current_year",
        "source_url": "https://minamisuna1.com/38004/",
        "series_source_url": "https://minamisuna1.com/38004/",
        "public_intro": "深川ギャザリアセンタープラザで開かれる木場一・六町会主催の盆踊り大会。",
        "detail": "\n".join(
            [
                "2026年告知確認。掲載記事の開催概要で、開催日時: 2026年7月18日(土)・19日(日)18:00-20:30、会場: 深川ギャザリアセンタープラザ、主催: 木場一・六町会を確認。",
                "- 出典URL: https://minamisuna1.com/38004/",
            ]
        ),
        "confidence": "high",
        "reason": "current-year local article contains a press-release style event outline with organizer, date, time, and venue",
    },
    {
        "event_name": "東陽一丁目町会 盆踊り大会",
        "venue": {
            "canonical_name": "旧子供広場",
            "area": "江東区",
            "address": "東京都江東区東陽1-19-6",
            "access": "",
            "source_url": "https://minamisuna1.com/37573/",
            "aliases": ["東陽一丁目旧子供広場", "旧子供広場（東陽1-19-6）"],
        },
        "date_start": "2026-07-25",
        "date_end": "2026-07-26",
        "source_kind": "official_current_year",
        "source_url": "https://toyo1tyokai.1net.jp/schedule.html",
        "series_source_url": "https://toyo1tyokai.1net.jp/schedule.html",
        "public_intro": "東陽一丁目町会による地域の盆踊り大会。",
        "detail": "\n".join(
            [
                "2026年告知確認。東陽1丁目町会公式の活動予定で、令和8年7月25日-26日の盆踊り大会を確認。時刻・会場は地域情報記事で、7月25日18:00-20:30、7月26日18:00-20:00、旧子供広場（東陽1-19-6）を確認。",
                "- 公式URL: https://toyo1tyokai.1net.jp/schedule.html",
                "- 補足URL: https://minamisuna1.com/37573/",
            ]
        ),
        "confidence": "high",
        "reason": "official neighborhood association schedule confirms current-year dates; local listing supplies venue and times",
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
        SELECT o.*, s.status AS series_status, s.canonical_name AS series_name,
               v.canonical_name AS venue_name
        FROM event_occurrences o
        JOIN event_series s ON s.series_id = o.series_id
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE o.occurrence_id = ?
        """,
        (occurrence_id,),
    )
    return result[0] if result else None


def series(conn, series_id):
    result = rows(conn, "SELECT * FROM event_series WHERE series_id = ?", (series_id,))
    return result[0] if result else None


def venue(conn, venue_id):
    result = rows(conn, "SELECT * FROM venues WHERE venue_id = ?", (venue_id,))
    return result[0] if result else None


def find_venue_by_name_address(conn, venue_data):
    result = rows(
        conn,
        """
        SELECT *
        FROM venues
        WHERE normalized_name = ?
          AND COALESCE(address, '') = ?
        """,
        (normalize_text(venue_data["canonical_name"]), venue_data.get("address") or ""),
    )
    return result[0] if result else None


def ensure_venue(conn, item, now):
    if item.get("venue_id"):
        candidate = venue(conn, item["venue_id"])
        if not candidate:
            raise ValueError(f"missing existing venue: {item['venue_id']}")
        return item["venue_id"], False

    venue_data = item["venue"]
    existing = find_venue_by_name_address(conn, venue_data)
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
                venue_data.get("area") or "",
                venue_data.get("access") or "",
                venue_data.get("source_url") or "",
                now,
                venue_id,
            ),
        )
        created = False
    else:
        venue_id = stable_id(
            "ven",
            venue_data["canonical_name"],
            venue_data.get("address") or "",
            venue_data.get("source_url") or "",
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
                venue_data["canonical_name"],
                normalize_text(venue_data["canonical_name"]),
                venue_data.get("area") or "",
                venue_data.get("address") or "",
                venue_data.get("access") or "",
                "",
                "",
                "",
                venue_data.get("source_url") or "",
                None,
                None,
                "active",
                now,
                now,
            ),
        )
        created = True
    for alias in [venue_data["canonical_name"], *(venue_data.get("aliases") or [])]:
        conn.execute(
            """
            INSERT OR IGNORE INTO venue_aliases(
              venue_id, alias, normalized_alias, source, confidence
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (venue_id, alias, normalize_text(alias), "reviewed_public_event_candidates_20260701", "manual"),
        )
    return venue_id, created


def insert_event(conn, item, now):
    existing = rows(
        conn,
        """
        SELECT o.occurrence_id, o.series_id, o.display_name, o.date_start, v.canonical_name AS venue_name
        FROM event_occurrences o
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE o.display_name = ?
          AND o.event_year = 2026
        """,
        (item["event_name"],),
    )
    if existing:
        venue_id, venue_created = ensure_venue(conn, item, now)
        existing_row = existing[0]
        occurrence_date_id = stable_id(
            "odate",
            existing_row["occurrence_id"],
            item["date_start"],
            item["date_end"],
            item["source_url"],
        )
        conn.execute(
            """
            UPDATE event_occurrences
            SET venue_id = ?,
                date_start = ?,
                date_end = ?,
                date_status = 'confirmed',
                lifecycle_status = 'published',
                confidence = ?,
                source_kind = ?,
                source_url = ?,
                detail = ?,
                updated_at = ?
            WHERE occurrence_id = ?
            """,
            (
                venue_id,
                item["date_start"],
                item["date_end"],
                item.get("confidence") or "high",
                item["source_kind"],
                item["source_url"],
                item.get("detail") or "",
                now,
                existing_row["occurrence_id"],
            ),
        )
        conn.execute(
            """
            UPDATE event_series
            SET usual_venue_id = ?,
                public_intro = ?,
                source_url = ?,
                status = 'active',
                updated_at = ?
            WHERE series_id = ?
            """,
            (
                venue_id,
                item.get("public_intro") or "",
                item["series_source_url"],
                now,
                existing_row["series_id"],
            ),
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
                existing_row["occurrence_id"],
                item["date_start"],
                item["date_end"],
                "confirmed",
                item.get("confidence") or "high",
                None,
                item["source_kind"],
                now,
            ),
        )
        return {
            "action": "update_existing_event",
            "event_name": item["event_name"],
            "series_id": existing_row["series_id"],
            "occurrence_id": existing_row["occurrence_id"],
            "occurrence_date_id": occurrence_date_id,
            "venue_id": venue_id,
            "venue_created": venue_created,
            "date_start": item["date_start"],
            "date_end": item["date_end"],
            "source_url": item["source_url"],
            "reason": item["reason"],
            "existing": existing,
        }

    venue_id, venue_created = ensure_venue(conn, item, now)
    series_id = stable_id("ser", item["event_name"], venue_id, item["series_source_url"])
    occurrence_id = stable_id("occ", series_id, 2026, item["event_name"], item["source_url"])
    series_key = stable_id("serkey", item["event_name"], venue_id, item["series_source_url"], length=12)
    occurrence_date_id = stable_id("odate", occurrence_id, item["date_start"], item["date_end"], item["source_url"])

    conn.execute(
        """
        INSERT INTO event_series(
          series_id, origin, series_key, canonical_name, normalized_name,
          usual_venue_id, area, program_type, annual_months_json,
          schedule_rule_type, schedule_rule_detail, public_intro, source_url,
          status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            series_id,
            "curated",
            series_key,
            item["event_name"],
            normalize_text(item["event_name"]),
            venue_id,
            "江東区",
            "盆踊り",
            json.dumps([int(item["date_start"][5:7])], ensure_ascii=False),
            "",
            "",
            item.get("public_intro") or "",
            item["series_source_url"],
            "active",
            now,
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO event_occurrences(
          occurrence_id, origin, series_id, event_year, occurrence_sequence,
          display_name, venue_id, date_start, date_end, date_status,
          lifecycle_status, confidence, source_kind, source_url,
          inherited_from_occurrence_id, public_intro_override, detail,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            occurrence_id,
            "curated",
            series_id,
            2026,
            1,
            item["event_name"],
            venue_id,
            item["date_start"],
            item["date_end"],
            "confirmed",
            "published",
            item.get("confidence") or "high",
            item["source_kind"],
            item["source_url"],
            None,
            "",
            item.get("detail") or "",
            now,
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO occurrence_dates(
          occurrence_date_id, occurrence_id, date_start, date_end, date_type,
          confidence, source_evidence_id, basis, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            occurrence_date_id,
            occurrence_id,
            item["date_start"],
            item["date_end"],
            "confirmed",
            item.get("confidence") or "high",
            None,
            item["source_kind"],
            now,
        ),
    )
    return {
        "action": "insert_event",
        "event_name": item["event_name"],
        "series_id": series_id,
        "occurrence_id": occurrence_id,
        "occurrence_date_id": occurrence_date_id,
        "venue_id": venue_id,
        "venue_created": venue_created,
        "date_start": item["date_start"],
        "date_end": item["date_end"],
        "source_url": item["source_url"],
        "reason": item["reason"],
    }


def apply_merge(conn, item, now):
    before = {
        "old_series": series(conn, item["old_series_id"]),
        "new_series": series(conn, item["new_series_id"]),
        "old_occurrence": occurrence(conn, item["old_occurrence_id"]),
        "new_occurrence": occurrence(conn, item["new_occurrence_id"]),
    }
    issues = []
    for key, value in before.items():
        if not value:
            issues.append({"severity": "high", "issue_type": f"missing_{key}", "item": item})
    if issues:
        return {"action": "merge_duplicate", "event_name": item["event_name"], "before": before, "after": before, "issues": issues}

    conn.execute(
        """
        UPDATE event_occurrences
        SET lifecycle_status = 'merged',
            confidence = 'superseded',
            updated_at = ?
        WHERE occurrence_id = ?
        """,
        (now, item["old_occurrence_id"]),
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
        (item["merged_name"], normalize_text(item["merged_name"]), now, item["old_series_id"]),
    )
    conn.execute(
        """
        UPDATE external_record_links
        SET master_id = ?
        WHERE master_table = 'event_series'
          AND master_id = ?
        """,
        (item["new_series_id"], item["old_series_id"]),
    )
    after = {
        "old_series": series(conn, item["old_series_id"]),
        "new_series": series(conn, item["new_series_id"]),
        "old_occurrence": occurrence(conn, item["old_occurrence_id"]),
        "new_occurrence": occurrence(conn, item["new_occurrence_id"]),
    }
    return {
        "action": "merge_duplicate",
        "event_name": item["event_name"],
        "old_occurrence_id": item["old_occurrence_id"],
        "old_series_id": item["old_series_id"],
        "new_occurrence_id": item["new_occurrence_id"],
        "new_series_id": item["new_series_id"],
        "reason": item["reason"],
        "before": before,
        "after": after,
        "issues": issues,
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
    for item in applied:
        if item.get("action") in {"insert_event", "update_existing_event"}:
            after = occurrence(conn, item["occurrence_id"])
            if not after:
                issues.append({"severity": "high", "issue_type": "inserted_occurrence_missing", "item": item})
            elif after.get("date_start") != item["date_start"] or after.get("venue_id") != item["venue_id"]:
                issues.append({"severity": "high", "issue_type": "inserted_occurrence_mismatch", "item": item})
        if item.get("action") == "merge_duplicate":
            after = occurrence(conn, item["old_occurrence_id"])
            old_series = series(conn, item["old_series_id"])
            if after and after.get("lifecycle_status") != "merged":
                issues.append({"severity": "high", "issue_type": "old_occurrence_not_merged", "item": item})
            if old_series and old_series.get("status") != "merged":
                issues.append({"severity": "high", "issue_type": "old_series_not_merged", "item": item})
        issues.extend(item.get("issues") or [])
    return issues


def render_markdown(result):
    lines = [
        "# Reviewed public event candidates 20260701 apply report",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- target_db: `{result['outputs']['target_db']}`",
        f"- dry_run_db: `{result['outputs']['dry_run_db']}`",
        f"- backup_db: `{result['outputs']['backup_db']}`",
        f"- db_committed: {result['write_guard']['db_committed']}",
        f"- rolled_back: {result['write_guard']['rolled_back']}",
        f"- applied_count: {result['summary']['applied_count']}",
        f"- issues_by_severity: {result['summary']['issues_by_severity']}",
        f"- missing_publication_blocker_count: {result['summary']['publication_blocker_count']}",
        "",
        "| action | event | result | reason |",
        "| --- | --- | --- | --- |",
    ]
    for item in result["applied"]:
        if item["action"] in {"insert_event", "update_existing_event"}:
            result_text = f"{item['date_start']} to {item['date_end']} at `{item['venue_id']}`"
        elif item["action"] == "skip_existing_event":
            result_text = "skipped existing event"
        else:
            result_text = f"merged `{item['old_occurrence_id']}` into `{item['new_occurrence_id']}`"
        lines.append(f"| {item['action']} | {item['event_name']} | {result_text} | {item.get('reason') or ''} |")
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
        applied = []
        for item in MERGES:
            applied.append(apply_merge(conn, item, now))
        for item in NEW_EVENTS:
            applied.append(insert_event(conn, item, now))

        issues = consistency_checks(conn, applied)
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
        publication_blocker_count = scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM event_occurrences o
            JOIN event_series s ON s.series_id = o.series_id
            LEFT JOIN venues v ON v.venue_id = o.venue_id
            WHERE o.origin = 'curated'
              AND o.event_year >= 2026
              AND s.status = 'active'
              AND o.lifecycle_status NOT IN ('merged', 'duplicate', 'rejected', 'superseded_by_curated')
              AND (
                COALESCE(o.source_url, '') != ''
                OR COALESCE(s.source_url, '') != ''
                OR COALESCE(o.detail, '') LIKE '%http%'
              )
              AND (o.venue_id IS NULL OR COALESCE(o.date_start, '') = '')
            """,
        )
    if args.apply and committed:
        refresh_manifest_database_state(args.master_db, updated_at=now)

    result = {
        "generated_by": "apply_reviewed_public_event_candidates_20260701.py",
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
            "applied_count": len(applied),
            "issues_count": len(issues),
            "issues_by_severity": dict(Counter(issue["severity"] for issue in issues)),
            "publication_blocker_count": publication_blocker_count,
            "table_counts": counts,
        },
        "applied": applied,
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
    result = run(args)
    print(
        "reviewed public event candidates 20260701: "
        f"mode={result['mode']} applied={result['summary']['applied_count']} "
        f"issues={result['summary']['issues_count']} rolled_back={result['write_guard']['rolled_back']}"
    )


if __name__ == "__main__":
    main()
