"""Register the official 2026 Marunouchi bon odori occurrence.

Default mode writes to a copied SQLite DB. Apply mode updates the master RDB
only; public JSON and site sync are separate follow-up steps.
"""

import argparse
import json
import shutil
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import audit_master_rdb
from master_db import MASTER_DB, refresh_manifest_database_state, stable_id, table_counts


DATA = Path("data")
OUT_DB = DATA / "marunouchi_2026_official_confirmation_dry_run.sqlite"
OUT_JSON = DATA / "marunouchi_2026_official_confirmation_apply_report.json"
OUT_MD = DATA / "marunouchi_2026_official_confirmation_apply_report.md"
BACKUP_DIR = DATA / "backups"
CONFIRM = "APPLY MARUNOUCHI 2026 OFFICIAL CONFIRMATION"
SCRIPT_NAME = "apply_marunouchi_2026_official_confirmation.py"

EVENT_NAME = "丸の内de盆踊り"
OFFICIAL_TITLE = "丸の内盆踊り2026"
VENUE_NAME = "行幸通り"
AREA = "千代田区"
ADDRESS = "東京都千代田区丸の内2-2"
SOURCE_URL = "https://www.marunouchi.com/pickup/event/9833/"
DATE_START = "2026-07-24"
DATE_END = "2026-07-24"
BON_ODORI_TIME = "19:00〜22:30"
PREDICTED_DATE_ID = "preddate_369836a93ec48b81"
PREDICTION_RESOLUTION = "superseded_by_official_2026_confirmation"


def rows(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def scalar(conn, query, params=()):
    row = conn.execute(query, params).fetchone()
    return row[0] if row else None


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def ids():
    return {
        "occurrence_id": stable_id("occ", EVENT_NAME, VENUE_NAME, "2026"),
        "date_id": stable_id("odate", EVENT_NAME, DATE_START, DATE_END, SOURCE_URL),
        "evidence_id": stable_id("evid", SOURCE_URL),
    }


def find_series(conn):
    matches = rows(
        conn,
        """
        SELECT series_id, canonical_name, source_url
        FROM event_series
        WHERE canonical_name = ?
        """,
        (EVENT_NAME,),
    )
    if len(matches) != 1:
        raise ValueError(f"expected one Marunouchi series, found {len(matches)}")
    return matches[0]


def find_venue(conn):
    matches = rows(
        conn,
        """
        SELECT venue_id, canonical_name, address, source_url
        FROM venues
        WHERE canonical_name = ? AND address = ?
        """,
        (VENUE_NAME, ADDRESS),
    )
    if len(matches) != 1:
        raise ValueError(f"expected one Gyoko-dori venue, found {len(matches)}")
    return matches[0]


def existing_state(conn, id_map, series_id):
    return {
        "series": rows(conn, "SELECT * FROM event_series WHERE series_id = ?", (series_id,)),
        "occurrences": rows(
            conn,
            """
            SELECT occurrence_id, event_year, display_name, date_start, date_end,
                   date_status, lifecycle_status, confidence, source_kind, source_url
            FROM event_occurrences
            WHERE series_id = ?
            ORDER BY event_year, occurrence_sequence
            """,
            (series_id,),
        ),
        "target_occurrence": rows(
            conn,
            "SELECT * FROM event_occurrences WHERE occurrence_id = ?",
            (id_map["occurrence_id"],),
        ),
        "prediction": rows(
            conn,
            "SELECT * FROM predicted_occurrence_dates WHERE predicted_date_id = ?",
            (PREDICTED_DATE_ID,),
        ),
    }


def detail_text():
    return (
        f"{DATE_START}、行幸通りで開催。公式ページ「{OFFICIAL_TITLE}」で開催日・会場・"
        f"盆踊り時間を確認。盆踊りは{BON_ODORI_TIME}、イベント全体は16:00〜22:30。"
        "\n\n[official_confirmation]"
        f"\n- 公式URL: {SOURCE_URL}"
        f"\n- 公式タイトル: 今年も開催！『{OFFICIAL_TITLE}』 in 行幸通り"
        f"\n- 会場: {VENUE_NAME}（{ADDRESS}）"
        f"\n- 盆踊り時間: {BON_ODORI_TIME}"
        "\n- 主催: 大手町・丸の内・有楽町夏祭り実行委員会"
    )


def apply_confirmation(conn, now, id_map, series, venue):
    occurrence_id = id_map["occurrence_id"]
    conn.execute(
        """
        UPDATE event_series
        SET source_url = ?,
            updated_at = ?
        WHERE series_id = ?
        """,
        (SOURCE_URL, now, series["series_id"]),
    )
    conn.execute(
        """
        INSERT INTO event_occurrences(
          occurrence_id, origin, series_id, event_year, occurrence_sequence,
          display_name, venue_id, date_start, date_end, date_status,
          lifecycle_status, confidence, source_kind, source_url,
          inherited_from_occurrence_id, public_intro_override, detail,
          created_at, updated_at
        ) VALUES (?, 'curated', ?, 2026, 1, ?, ?, ?, ?, 'confirmed',
          'published', 'high', 'official_current_year', ?, NULL, ?, ?, ?, ?)
        ON CONFLICT(series_id, event_year, occurrence_sequence) DO UPDATE SET
          display_name=excluded.display_name,
          venue_id=excluded.venue_id,
          date_start=excluded.date_start,
          date_end=excluded.date_end,
          date_status=excluded.date_status,
          lifecycle_status=excluded.lifecycle_status,
          confidence=excluded.confidence,
          source_kind=excluded.source_kind,
          source_url=excluded.source_url,
          public_intro_override=excluded.public_intro_override,
          detail=excluded.detail,
          updated_at=excluded.updated_at
        """,
        (
            occurrence_id,
            series["series_id"],
            EVENT_NAME,
            venue["venue_id"],
            DATE_START,
            DATE_END,
            SOURCE_URL,
            "東京駅と皇居を結ぶ行幸通りで開かれる、丸の内エリアの夏の盆踊り。",
            detail_text(),
            now,
            now,
        ),
    )
    actual_occurrence_id = scalar(
        conn,
        """
        SELECT occurrence_id
        FROM event_occurrences
        WHERE series_id = ? AND event_year = 2026 AND occurrence_sequence = 1
        """,
        (series["series_id"],),
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO occurrence_dates(
          occurrence_date_id, occurrence_id, date_start, date_end, date_type,
          confidence, source_evidence_id, basis, created_at
        ) VALUES (?, ?, ?, ?, 'confirmed', 'high', NULL, 'official_current_year', ?)
        """,
        (id_map["date_id"], actual_occurrence_id, DATE_START, DATE_END, now),
    )
    conn.execute(
        """
        INSERT INTO evidence_items(
          evidence_id, platform, evidence_type, source_key, source_id,
          account_key, title, text_excerpt, url, published_at, observed_at,
          detected_event_date, raw_status, raw_json
        ) VALUES (?, 'web', 'official_current_year', 'marunouchi.com', '9833',
          'Marunouchi.com', ?, ?, ?, '2026-07-01T13:39:10+09:00', ?,
          ?, 'official_confirmed', ?)
        ON CONFLICT(evidence_id) DO UPDATE SET
          evidence_type=excluded.evidence_type,
          title=excluded.title,
          text_excerpt=excluded.text_excerpt,
          url=excluded.url,
          published_at=excluded.published_at,
          observed_at=excluded.observed_at,
          detected_event_date=excluded.detected_event_date,
          raw_status=excluded.raw_status,
          raw_json=excluded.raw_json
        """,
        (
            id_map["evidence_id"],
            f"今年も開催！『{OFFICIAL_TITLE}』 in 行幸通り",
            f"2026年7月24日（金）開催。盆踊りは{BON_ODORI_TIME}、場所は行幸通り。",
            SOURCE_URL,
            now,
            DATE_START,
            json.dumps(
                {
                    "url": SOURCE_URL,
                    "date_start": DATE_START,
                    "date_end": DATE_END,
                    "place": VENUE_NAME,
                    "address": ADDRESS,
                    "bon_odori_time": BON_ODORI_TIME,
                    "checked_by": "おと（Codex）",
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        ),
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO occurrence_evidence_links(
          occurrence_id, evidence_id, target, link_status, confidence, notes
        ) VALUES (?, ?, 'date_and_venue', 'confirmed', 1.0, ?)
        """,
        (
            actual_occurrence_id,
            id_map["evidence_id"],
            "Marunouchi.com公式ページで2026年開催日・会場・盆踊り時間を確認。",
        ),
    )
    conn.execute(
        """
        UPDATE predicted_occurrence_dates
        SET target_occurrence_id = ?,
            application_status = ?,
            updated_at = ?
        WHERE predicted_date_id = ?
        """,
        (actual_occurrence_id, PREDICTION_RESOLUTION, now, PREDICTED_DATE_ID),
    )
    conn.execute(
        """
        UPDATE notion_sync_jobs
        SET status = ?,
            result_json = ?
        WHERE target_table = 'predicted_occurrence_dates'
          AND target_id = ?
          AND status = 'pending'
        """,
        (
            PREDICTION_RESOLUTION,
            json.dumps(
                {
                    "reviewed_by": SCRIPT_NAME,
                    "reviewed_at": now,
                    "reason": "marunouchi_2026_official_page_confirmed",
                    "target_occurrence_id": actual_occurrence_id,
                    "source_url": SOURCE_URL,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            PREDICTED_DATE_ID,
        ),
    )
    return actual_occurrence_id


def consistency_checks(conn, occurrence_id):
    issues = []
    fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_rows:
        issues.append(
            {
                "severity": "high",
                "issue_type": "foreign_key_check_failed",
                "sample": [tuple(row) for row in fk_rows[:10]],
            }
        )
    occurrence = rows(
        conn,
        """
        SELECT occurrence_id, event_year, display_name, date_start, date_end,
               date_status, lifecycle_status, confidence, source_url
        FROM event_occurrences
        WHERE occurrence_id = ?
        """,
        (occurrence_id,),
    )
    if not occurrence:
        issues.append({"severity": "high", "issue_type": "missing_2026_occurrence"})
        return issues
    row = occurrence[0]
    expected = {
        "event_year": 2026,
        "date_start": DATE_START,
        "date_end": DATE_END,
        "date_status": "confirmed",
        "lifecycle_status": "published",
        "confidence": "high",
        "source_url": SOURCE_URL,
    }
    for key, value in expected.items():
        if row.get(key) != value:
            issues.append(
                {
                    "severity": "high",
                    "issue_type": f"unexpected_{key}",
                    "actual": row.get(key),
                    "expected": value,
                }
            )
    return issues


def render_markdown(result):
    lines = [
        "# Marunouchi 2026 official confirmation apply report",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- db_committed: {result['write_guard']['db_committed']}",
        f"- rolled_back: {result['write_guard']['rolled_back']}",
        f"- target_db: `{result['outputs']['target_db']}`",
        f"- dry_run_db: `{result['outputs']['dry_run_db']}`",
        f"- backup_db: `{result['outputs']['backup_db']}`",
        f"- occurrence_id: `{result['ids']['occurrence_id']}`",
        f"- event: {EVENT_NAME}",
        f"- official_title: {OFFICIAL_TITLE}",
        f"- date: {DATE_START}",
        f"- venue: {VENUE_NAME}",
        f"- source_url: {SOURCE_URL}",
        f"- issues_by_severity: {result['summary']['issues_by_severity']}",
        "",
    ]
    if result["issues"]:
        lines.extend(["## Issues", ""])
        lines.extend(f"- {issue['severity']} {issue['issue_type']}: {issue}" for issue in result["issues"])
        lines.append("")
    return "\n".join(lines)


def validate_apply(args):
    if args.apply and args.confirm != CONFIRM:
        raise ValueError(f"--apply requires --confirm {CONFIRM!r}")
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

    id_map = ids()
    with sqlite3.connect(target_db) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        series = find_series(conn)
        venue = find_venue(conn)
        before = existing_state(conn, id_map, series["series_id"])
        occurrence_id = apply_confirmation(conn, now, id_map, series, venue)
        after = existing_state(conn, id_map, series["series_id"])
        issues = consistency_checks(conn, occurrence_id)
        has_high_issue = any(issue.get("severity") == "high" for issue in issues)
        if args.apply and has_high_issue:
            conn.rollback()
            committed = False
            rolled_back = True
        else:
            conn.commit()
            committed = True
            rolled_back = False
        summary = {
            "issues_by_severity": dict(Counter(issue["severity"] for issue in issues)),
            "table_counts": table_counts(conn),
            "confirmed_2026_occurrences": scalar(
                conn,
                "SELECT COUNT(*) FROM event_occurrences WHERE event_year = 2026 AND date_status = 'confirmed'",
            ),
        }

    audit = audit_master_rdb.audit(
        argparse.Namespace(
            db=target_db,
            notion_db=audit_master_rdb.NOTION_DB,
            song_occurrences=audit_master_rdb.SONG_OCCURRENCES,
            manifest=audit_master_rdb.MASTER_MANIFEST,
        )
    )
    result = {
        "generated_by": SCRIPT_NAME,
        "generated_at": now,
        "mode": "apply" if args.apply else "dry_run",
        "scope": "rdb_only_no_notion_no_public_json",
        "ids": id_map,
        "outputs": {
            "target_db": str(target_db),
            "dry_run_db": "" if args.apply else str(args.out_db),
            "backup_db": backup,
        },
        "write_guard": {
            "db_committed": committed,
            "rolled_back": rolled_back,
        },
        "summary": summary,
        "audit": {
            "issue_count": audit["issue_count"],
            "issues_by_severity": audit["issues_by_severity"],
        },
        "before": before,
        "after": after,
        "issues": issues,
    }
    write_json(args.out_json, result)
    Path(args.out_md).write_text(render_markdown(result), encoding="utf-8")
    if args.apply and not rolled_back:
        refresh_manifest_database_state(args.master_db)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-db", default=str(MASTER_DB))
    parser.add_argument("--out-db", default=str(OUT_DB))
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        result = run(args)
    except ValueError as exc:
        parser.error(str(exc))
    print(
        "marunouchi 2026 official confirmation: "
        f"mode={result['mode']} committed={result['write_guard']['db_committed']} "
        f"issues={result['summary']['issues_by_severity']} "
        f"occurrence={result['ids']['occurrence_id']}"
    )
    return 1 if result["summary"]["issues_by_severity"].get("high") else 0


if __name__ == "__main__":
    raise SystemExit(main())
