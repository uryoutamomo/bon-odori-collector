"""Register Irifune 3-chome as a 2026 unknown event with 2024 video evidence.

This intentionally does not create an occurrence_dates historical_reference row:
the YouTube evidence confirms a 2024 occurrence, but not an exact 2024 date.
"""

import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from master_db import MASTER_DB, normalize_text, refresh_manifest_database_state, stable_id, table_counts


DATA = Path("data")
OUT_DB = DATA / "irifune_third_historical_reference_dry_run.sqlite"
DRY_RUN_JSON = DATA / "irifune_third_historical_reference_dry_run_report.json"
DRY_RUN_MD = DATA / "irifune_third_historical_reference_dry_run_report.md"
APPLY_JSON = DATA / "irifune_third_historical_reference_apply_report.json"
APPLY_MD = DATA / "irifune_third_historical_reference_apply_report.md"
BACKUP_DIR = DATA / "backups"
CONFIRM = "APPLY IRIFUNE THIRD HISTORICAL REFERENCE"

EVENT_NAME = "入船三丁目町会納涼盆踊り"
VENUE_NAME = "入船三丁目町会周辺（会場未確認）"
AREA = "中央区"
ADDRESS = "東京都中央区入船三丁目付近"
ACCESS = "東京メトロ有楽町線 新富町駅、JR・東京メトロ日比谷線 八丁堀駅から徒歩圏内"
SOURCE_URL = "https://www.youtube.com/watch?v=_evno2EqsRQ"
VIDEO_URLS = [
    "https://www.youtube.com/watch?v=_evno2EqsRQ",
    "https://www.youtube.com/watch?v=XA9iSh1780U",
    "https://www.youtube.com/watch?v=U9QsOXUzkME",
    "https://www.youtube.com/watch?v=pWOznwJMBo0",
    "https://www.youtube.com/watch?v=JHxleSsM4F0",
    "https://www.youtube.com/watch?v=TTWwFe_oquA",
    "https://www.youtube.com/watch?v=Hrifq3kJGjg",
    "https://www.youtube.com/watch?v=-XVKsEtTdfs",
    "https://www.youtube.com/watch?v=HuRW_Pugx70",
    "https://www.youtube.com/watch?v=DNyK8XUcbMM",
    "https://www.youtube.com/watch?v=sIBzYIn_aXQ",
    "https://www.youtube.com/watch?v=nAt6OCzshJ0",
    "https://www.youtube.com/watch?v=uX51SN_cETs",
]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def copy_db(source, out_db):
    out_db.parent.mkdir(parents=True, exist_ok=True)
    if out_db.exists():
        out_db.unlink()
    shutil.copy2(source, out_db)


def backup_db(source, now):
    stamp = now.replace("-", "").replace(":", "").replace("+00:00", "Z")
    backup = BACKUP_DIR / f"{Path(source).stem}.{stamp}{Path(source).suffix}.bak"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup)
    return backup


def rows(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_md(path, result):
    lines = [
        "# 入船三丁目 過去実績カード登録",
        "",
        f"- mode: {result['mode']}",
        f"- status: {result['status']}",
        f"- db_path: `{result['db_path']}`",
        f"- venue_id: `{result['ids']['venue_id']}`",
        f"- series_id: `{result['ids']['series_id']}`",
        f"- occurrence_id: `{result['ids']['occurrence_id']}`",
        f"- event_name: {EVENT_NAME}",
        f"- venue_name: {VENUE_NAME}",
        f"- note: 2024年YouTube実績は確認。具体開催日は未確認のため historical_reference 日付は未挿入。",
    ]
    if result.get("backup"):
        lines.append(f"- backup: `{result['backup']}`")
    if result.get("issues"):
        lines.extend(["", "## Issues"])
        lines.extend(f"- {issue}" for issue in result["issues"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def existing_state(conn, ids):
    return {
        "venue": rows(conn, "SELECT * FROM venues WHERE venue_id = ?", (ids["venue_id"],)),
        "series": rows(conn, "SELECT * FROM event_series WHERE series_id = ?", (ids["series_id"],)),
        "occurrence": rows(conn, "SELECT * FROM event_occurrences WHERE occurrence_id = ?", (ids["occurrence_id"],)),
        "venue_name_matches": rows(
            conn,
            "SELECT venue_id, canonical_name, address FROM venues WHERE normalized_name = ?",
            (normalize_text(VENUE_NAME),),
        ),
        "series_key_matches": rows(
            conn,
            "SELECT series_id, canonical_name FROM event_series WHERE series_key = ?",
            (ids["series_key"],),
        ),
    }


def apply(conn, now, ids):
    venue_rows = rows(conn, "SELECT venue_id FROM venues WHERE venue_id = ?", (ids["venue_id"],))
    if not venue_rows:
        conn.execute(
            """
            INSERT INTO venues(
              venue_id, origin, canonical_name, normalized_name, area, address,
              access, scale, public_intro, past_memo, source_url, review_status,
              created_at, updated_at
            ) VALUES (?, 'curated', ?, ?, ?, ?, ?, NULL, ?, ?, NULL, 'active', ?, ?)
            """,
            (
                ids["venue_id"],
                VENUE_NAME,
                normalize_text(VENUE_NAME),
                AREA,
                ADDRESS,
                ACCESS,
                "入船三丁目町会周辺。会場名は未確認のため、町会エリアとして整理しています。",
                "2024年のYouTube動画群で入船三丁目町会納涼盆踊りの開催実績を確認。具体開催日は未確認。",
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO venue_aliases(
              venue_id, alias, normalized_alias, source, confidence
            ) VALUES (?, ?, ?, 'manual_historical_reference', 'manual')
            """,
            (ids["venue_id"], "入船三丁目町会", normalize_text("入船三丁目町会")),
        )

    series_rows = rows(conn, "SELECT series_id FROM event_series WHERE series_id = ?", (ids["series_id"],))
    if not series_rows:
        conn.execute(
            """
            INSERT INTO event_series(
              series_id, origin, series_key, canonical_name, normalized_name,
              usual_venue_id, area, program_type, annual_months_json,
              schedule_rule_type, schedule_rule_detail, public_intro, source_url,
              status, created_at, updated_at
            ) VALUES (?, 'curated', ?, ?, ?, ?, ?, 'bon_odori', ?, NULL, NULL, ?, NULL, 'active', ?, ?)
            """,
            (
                ids["series_id"],
                ids["series_key"],
                EVENT_NAME,
                normalize_text(EVENT_NAME),
                ids["venue_id"],
                AREA,
                json.dumps([8], ensure_ascii=False),
                "入船三丁目町会の納涼盆踊り。2024年のYouTube動画で開催実績が確認できるが、2026年日程と具体会場は未確認です。",
                now,
                now,
            ),
        )

    occurrence_rows = rows(conn, "SELECT occurrence_id FROM event_occurrences WHERE occurrence_id = ?", (ids["occurrence_id"],))
    detail = (
        "2024年に入船三丁目町会納涼盆踊りの開催実績あり。"
        "和太鼓お祭りチャンネルのYouTube動画群で、東京音頭、バハマ・ママ、これがお江戸の盆ダンス、"
        "チャンチキおけさ、大東京音頭、少年八木節、ダンシング・ヒーロー、炭坑節、"
        "きよしの数え唄、ベイサイドブギ、銀座カンカン娘、きよしのズンドコ節、どだればちサンバを確認。"
        "ただし動画から具体開催日と会場名は確認できないため、2026年日程は未確認。"
    )
    if not occurrence_rows:
        conn.execute(
            """
            INSERT INTO event_occurrences(
              occurrence_id, origin, series_id, event_year, occurrence_sequence,
              display_name, venue_id, date_start, date_end, date_status,
              lifecycle_status, confidence, source_kind, source_url,
              public_intro_override, detail, created_at, updated_at
            ) VALUES (?, 'curated', ?, 2026, 1, ?, ?, NULL, NULL, 'unknown',
              '未確認', 'medium', 'youtube_historical', ?, ?, ?, ?, ?)
            """,
            (
                ids["occurrence_id"],
                ids["series_id"],
                EVENT_NAME,
                ids["venue_id"],
                SOURCE_URL,
                "入船三丁目町会の納涼盆踊り。2024年の動画実績をもとに、今年未確認の候補として掲載しています。",
                detail,
                now,
                now,
            ),
        )

    evidence_id = ids["evidence_id"]
    evidence_rows = rows(conn, "SELECT evidence_id FROM evidence_items WHERE evidence_id = ?", (evidence_id,))
    if not evidence_rows:
        conn.execute(
            """
            INSERT INTO evidence_items(
              evidence_id, platform, evidence_type, source_key, source_id,
              account_key, title, text_excerpt, url, published_at, observed_at,
              detected_event_date, raw_status, raw_json
            ) VALUES (?, 'youtube', 'historical_occurrence_video', ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'historical_reference_support', ?)
            """,
            (
                evidence_id,
                "youtube:和太鼓お祭りチャンネル",
                "_evno2EqsRQ",
                "和太鼓お祭りチャンネル",
                "東京音頭 2024年入船三丁目町会納涼盆踊り1 東京都中央区",
                "2024年東京都中央区で行われた「入船三丁目町会納涼盆踊り」の動画。具体開催日は本文から未確認。",
                SOURCE_URL,
                "2025-01-04T11:00:43Z",
                now,
                json.dumps({"video_urls": VIDEO_URLS, "exact_event_date_confirmed": False}, ensure_ascii=False, sort_keys=True),
            ),
        )
    conn.execute(
        """
        INSERT OR IGNORE INTO occurrence_evidence_links(
          occurrence_id, evidence_id, target, link_status, confidence, notes
        ) VALUES (?, ?, 'historical_occurrence', 'supporting', 0.82, ?)
        """,
        (
            ids["occurrence_id"],
            evidence_id,
            "2024年開催実績の根拠。2026年開催日や2024年の具体開催日は確認しない。",
        ),
    )


def consistency_checks(conn, ids):
    issues = []
    fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_rows:
        issues.append(f"foreign_key_check_failed: {len(fk_rows)}")
    occurrences = rows(conn, "SELECT occurrence_id, date_start, date_status FROM event_occurrences WHERE occurrence_id = ?", (ids["occurrence_id"],))
    if not occurrences:
        issues.append("missing_occurrence_after_apply")
    elif occurrences[0]["date_start"] is not None:
        issues.append("unexpected_confirmed_date_on_unknown_occurrence")
    historical_dates = rows(
        conn,
        "SELECT * FROM occurrence_dates WHERE occurrence_id = ? AND date_type = 'historical_reference'",
        (ids["occurrence_id"],),
    )
    if historical_dates:
        issues.append("unexpected_historical_reference_date_inserted")
    return issues


def run(db_path, apply_mode):
    now = now_iso()
    ids = {
        "venue_id": stable_id("ven", VENUE_NAME, ADDRESS),
        "series_key": stable_id("serkey", EVENT_NAME, VENUE_NAME),
        "series_id": stable_id("ser", EVENT_NAME, VENUE_NAME),
        "occurrence_id": stable_id("occ", EVENT_NAME, VENUE_NAME, "2026"),
        "evidence_id": stable_id("evid", SOURCE_URL),
    }
    target_db = Path(db_path)
    backup = None
    if apply_mode:
        backup = backup_db(target_db, now)
    else:
        copy_db(target_db, OUT_DB)
        target_db = OUT_DB

    before_counts = {}
    after_counts = {}
    with sqlite3.connect(target_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        before_counts = table_counts(conn)
        before = existing_state(conn, ids)
        apply(conn, now, ids)
        issues = consistency_checks(conn, ids)
        after = existing_state(conn, ids)
        after_counts = table_counts(conn)
        if issues:
            conn.rollback()
        else:
            conn.commit()

    if apply_mode and not issues:
        refresh_manifest_database_state(target_db)

    return {
        "mode": "apply" if apply_mode else "dry_run",
        "status": "failed" if issues else "ok",
        "db_path": str(target_db),
        "backup": str(backup) if backup else "",
        "ids": ids,
        "before_counts": before_counts,
        "after_counts": after_counts,
        "before": before,
        "after": after,
        "issues": issues,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(MASTER_DB))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    if args.apply and args.confirm != CONFIRM:
        raise SystemExit(f"--apply requires --confirm '{CONFIRM}'")

    result = run(args.db, args.apply)
    json_path = APPLY_JSON if args.apply else DRY_RUN_JSON
    md_path = APPLY_MD if args.apply else DRY_RUN_MD
    write_json(json_path, result)
    write_md(md_path, result)
    if result["status"] != "ok":
        raise SystemExit(f"failed: {result['issues']}")
    print(f"{result['mode']} ok: {json_path}")


if __name__ == "__main__":
    main()
