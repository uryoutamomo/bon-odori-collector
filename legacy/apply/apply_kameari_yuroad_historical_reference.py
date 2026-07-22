"""Register Kameari YOUROAD as a 2026 unknown event with 2024/2025 YouTube evidence."""

import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from master_rdb.master_db import MASTER_DB, normalize_text, refresh_manifest_database_state, stable_id, table_counts


DATA = Path("data")
OUT_DB = DATA / "kameari_yuroad_historical_reference_dry_run.sqlite"
DRY_RUN_JSON = DATA / "kameari_yuroad_historical_reference_dry_run_report.json"
DRY_RUN_MD = DATA / "kameari_yuroad_historical_reference_dry_run_report.md"
APPLY_JSON = DATA / "kameari_yuroad_historical_reference_apply_report.json"
APPLY_MD = DATA / "kameari_yuroad_historical_reference_apply_report.md"
BACKUP_DIR = DATA / "backups"
CONFIRM = "APPLY KAMEARI YUROAD HISTORICAL REFERENCE"

EVENT_NAME = "亀有銀座商店街納涼盆踊り大会"
SERIES_KEY_TEXT = "kameari-yuroad-bon-odori"
VENUE_NAME = "亀有ゆうろーど（亀有銀座商店街）"
AREA = "葛飾区"
ADDRESS = "東京都葛飾区亀有3丁目周辺"
ACCESS = "JR常磐線 亀有駅南口から徒歩圏内。亀有銀座商店街・ゆうろーど周辺"
SOURCE_URL = "https://www.youtube.com/watch?v=zYYG127xpVE"
HISTORICAL_DATE = "2025-08-31"

VIDEOS = [
    {
        "video_id": "zYYG127xpVE",
        "url": "https://www.youtube.com/watch?v=zYYG127xpVE",
        "title": "ゆうろーど納涼盆踊り大会 亀有銀座商店街 2025年8月31日（日）",
        "channel_id": "UC8djZNe8ynSlUmop8Jjt45A",
        "channel_title": "祭のきせき　MatsuriNoKiseki",
        "published_at": "2025-08-31T21:00:15Z",
        "detected_event_date": HISTORICAL_DATE,
        "evidence_type": "historical_occurrence_video",
        "text_excerpt": "説明欄で「ゆうろーど納涼盆踊り大会　亀有銀座商店街　2025年8月31日（日）」と確認。曲目タイムスタンプあり。",
    },
    {
        "video_id": "jm-i-AZtmUE",
        "url": "https://www.youtube.com/watch?v=jm-i-AZtmUE",
        "title": "【都内では珍しい踊り方】亀有ゆうろーど盆踊り2025",
        "channel_id": "UCN4tz92dmda1Z2nLF38FXkg",
        "channel_title": "祭しっぽ ch",
        "published_at": "2025-10-31T07:00:52Z",
        "detected_event_date": None,
        "evidence_type": "historical_occurrence_video",
        "text_excerpt": "タイトルで亀有ゆうろーど盆踊り2025を確認。説明欄に曲目タイムスタンプあり。",
    },
    {
        "video_id": "E3qiFabHeVc",
        "url": "https://www.youtube.com/watch?v=E3qiFabHeVc",
        "title": "亀有ゆうろーど盆踊りラスト曲【大東京音頭】2024年亀有銀座商店街納涼盆踊り大会26終",
        "channel_id": "UCNF_5e3ZvziJueTWvTPATGw",
        "channel_title": "和太鼓お祭りチャンネル",
        "published_at": "2024-09-01T11:30:07Z",
        "detected_event_date": None,
        "evidence_type": "historical_occurrence_video",
        "text_excerpt": "タイトルと説明欄で2024年の亀有ゆうろーど/亀有銀座商店街納涼盆踊り大会実績を確認。",
    },
]

SONGS = [
    "葛飾音頭",
    "アンパンマン音頭",
    "妖怪横丁ゲゲゲ節",
    "春駒ばやし",
    "亀有音頭",
    "涙そうそう",
    "南州おどり",
    "野球拳おどり",
    "葛飾ラプソディ音頭",
    "FUNK FUJIYAMA",
    "鹿児島小原節",
    "佐渡の石子法師",
    "河内おとこ節",
    "大東京音頭",
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
        "# 亀有ゆうろーど 過去実績カード登録",
        "",
        f"- mode: {result['mode']}",
        f"- status: {result['status']}",
        f"- db_path: `{result['db_path']}`",
        f"- venue_id: `{result['ids']['venue_id']}`",
        f"- series_id: `{result['ids']['series_id']}`",
        f"- occurrence_id: `{result['ids']['occurrence_id']}`",
        f"- event_name: {EVENT_NAME}",
        f"- venue_name: {VENUE_NAME}",
        f"- historical_reference_date: {HISTORICAL_DATE}",
        "- note: 2024/2025年YouTube実績は確認。2026年開催日は未確認。",
    ]
    if result.get("backup"):
        lines.append(f"- backup: `{result['backup']}`")
    if result.get("issues"):
        lines.extend(["", "## Issues"])
        lines.extend(f"- {issue}" for issue in result["issues"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ids():
    return {
        "venue_id": stable_id("ven", VENUE_NAME, ADDRESS),
        "series_key": SERIES_KEY_TEXT,
        "series_id": stable_id("ser", SERIES_KEY_TEXT),
        "occurrence_id": stable_id("occ", EVENT_NAME, VENUE_NAME, "2026"),
        "date_id": stable_id("date", EVENT_NAME, HISTORICAL_DATE, "historical_reference"),
        "historical_candidate_id": stable_id("histprom", EVENT_NAME, VENUE_NAME, "yuroad-2026-prediction"),
        "predicted_date_id": stable_id("preddate", EVENT_NAME, "2026-08-last-weekend"),
    }


def existing_state(conn, id_map):
    return {
        "venue": rows(conn, "SELECT * FROM venues WHERE venue_id = ?", (id_map["venue_id"],)),
        "series": rows(conn, "SELECT * FROM event_series WHERE series_id = ?", (id_map["series_id"],)),
        "occurrence": rows(conn, "SELECT * FROM event_occurrences WHERE occurrence_id = ?", (id_map["occurrence_id"],)),
        "historical_dates": rows(conn, "SELECT * FROM occurrence_dates WHERE occurrence_id = ?", (id_map["occurrence_id"],)),
        "historical_promotion": rows(
            conn,
            "SELECT * FROM historical_promotion_candidates WHERE candidate_id = ?",
            (id_map["historical_candidate_id"],),
        ),
        "predicted_dates": rows(
            conn,
            "SELECT * FROM predicted_occurrence_dates WHERE predicted_date_id = ?",
            (id_map["predicted_date_id"],),
        ),
        "event_name_matches": rows(
            conn,
            "SELECT occurrence_id, display_name, event_year FROM event_occurrences WHERE display_name LIKE '%亀有%' OR display_name LIKE '%ゆうろーど%'",
        ),
    }


def table_exists(conn, table_name):
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
    )


def insert_aliases(conn, venue_id, series_id):
    for alias in ["亀有ゆうろーど", "亀有YOUROAD", "亀有銀座商店街", "ゆうろーど商店街"]:
        conn.execute(
            """
            INSERT OR IGNORE INTO venue_aliases(
              venue_id, alias, normalized_alias, source, confidence
            ) VALUES (?, ?, ?, 'manual_yuroad_gap_review', 'manual')
            """,
            (venue_id, alias, normalize_text(alias)),
        )
    if not table_exists(conn, "event_aliases"):
        return
    for alias in ["亀有ゆうろーど盆踊り", "ゆうろーど納涼盆踊り大会", "亀有銀座商店街納涼盆踊り"]:
        conn.execute(
            """
            INSERT OR IGNORE INTO event_aliases(
              series_id, alias, normalized_alias, source, confidence
            ) VALUES (?, ?, ?, 'manual_yuroad_gap_review', 'manual')
            """,
            (series_id, alias, normalize_text(alias)),
        )


def apply(conn, now, id_map):
    venue_id = id_map["venue_id"]
    series_id = id_map["series_id"]
    occurrence_id = id_map["occurrence_id"]
    detail = (
        "亀有ゆうろーど（亀有銀座商店街）の納涼盆踊り。"
        "YouTube動画で2024年・2025年の開催実績を確認。"
        "2025年は祭のきせき MatsuriNoKiseki の説明欄で「2025年8月31日（日）」と確認。"
        "2026年開催日は未確認のため、過去実績候補として扱う。"
        "\n\n[youtube_evidence] 2024/2025実績証拠"
        "\n- 2025-08-31: https://www.youtube.com/watch?v=zYYG127xpVE"
        "\n- 2025実績: https://www.youtube.com/watch?v=jm-i-AZtmUE"
        "\n- 2024実績: https://www.youtube.com/watch?v=E3qiFabHeVc"
        "\n- 曲目候補: " + ", ".join(SONGS)
    )
    conn.execute(
        """
        INSERT INTO venues(
          venue_id, origin, canonical_name, normalized_name, area, address,
          access, scale, public_intro, past_memo, source_url, review_status,
          created_at, updated_at
        ) VALUES (?, 'curated', ?, ?, ?, ?, ?, '中', ?, ?, ?, 'active', ?, ?)
        ON CONFLICT(venue_id) DO UPDATE SET
          canonical_name=excluded.canonical_name,
          normalized_name=excluded.normalized_name,
          area=excluded.area,
          address=excluded.address,
          access=excluded.access,
          scale=excluded.scale,
          public_intro=excluded.public_intro,
          past_memo=excluded.past_memo,
          source_url=excluded.source_url,
          review_status='active',
          updated_at=excluded.updated_at
        """,
        (
            venue_id,
            VENUE_NAME,
            normalize_text(VENUE_NAME),
            AREA,
            ADDRESS,
            ACCESS,
            "亀有駅南口側の亀有銀座商店街・ゆうろーど周辺で開かれる街なかの盆踊り会場。",
            "2024年・2025年のYouTube動画で亀有ゆうろーど/亀有銀座商店街納涼盆踊り大会の開催実績を確認。",
            SOURCE_URL,
            now,
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO event_series(
          series_id, origin, series_key, canonical_name, normalized_name,
          usual_venue_id, area, program_type, annual_months_json,
          schedule_rule_type, schedule_rule_detail, public_intro, source_url,
          status, created_at, updated_at
        ) VALUES (?, 'curated', ?, ?, ?, ?, ?, 'bon_odori', ?, NULL, NULL, ?, ?, 'active', ?, ?)
        ON CONFLICT(series_id) DO UPDATE SET
          canonical_name=excluded.canonical_name,
          normalized_name=excluded.normalized_name,
          usual_venue_id=excluded.usual_venue_id,
          area=excluded.area,
          program_type=excluded.program_type,
          annual_months_json=excluded.annual_months_json,
          public_intro=excluded.public_intro,
          source_url=excluded.source_url,
          status='active',
          updated_at=excluded.updated_at
        """,
        (
            series_id,
            id_map["series_key"],
            EVENT_NAME,
            normalize_text(EVENT_NAME),
            venue_id,
            AREA,
            json.dumps([8], ensure_ascii=False),
            "亀有ゆうろーど（亀有銀座商店街）で開かれる納涼盆踊り大会。2024年・2025年の動画実績を確認済み。",
            SOURCE_URL,
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
          public_intro_override, detail, created_at, updated_at
        ) VALUES (?, 'curated', ?, 2026, 1, ?, ?, NULL, NULL, 'unknown',
          '未確認', 'medium', 'youtube_historical', ?, ?, ?, ?, ?)
        ON CONFLICT(occurrence_id) DO UPDATE SET
          series_id=excluded.series_id,
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
            series_id,
            EVENT_NAME,
            venue_id,
            SOURCE_URL,
            "亀有ゆうろーど（亀有銀座商店街）の納涼盆踊り。2025年の動画実績をもとに、今年未確認の候補として整理しています。",
            detail,
            now,
            now,
        ),
    )
    insert_aliases(conn, venue_id, series_id)

    evidence_ids = []
    for video in VIDEOS:
        evidence_id = stable_id("evid", video["url"])
        evidence_ids.append(evidence_id)
        conn.execute(
            """
            INSERT INTO evidence_items(
              evidence_id, platform, evidence_type, source_key, source_id,
              account_key, title, text_excerpt, url, published_at, observed_at,
              detected_event_date, raw_status, raw_json
            ) VALUES (?, 'youtube', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'historical_reference_support', ?)
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
                evidence_id,
                video["evidence_type"],
                f"youtube:{video['channel_id']}",
                video["video_id"],
                video["channel_title"],
                video["title"],
                video["text_excerpt"],
                video["url"],
                video["published_at"],
                now,
                video["detected_event_date"],
                json.dumps(video, ensure_ascii=False, sort_keys=True),
            ),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO occurrence_evidence_links(
              occurrence_id, evidence_id, target, link_status, confidence, notes
            ) VALUES (?, ?, 'historical_occurrence', 'supporting', 0.86, ?)
            """,
            (
                occurrence_id,
                evidence_id,
                "亀有ゆうろーど/亀有銀座商店街納涼盆踊り大会の過去開催実績の根拠。",
            ),
        )

    conn.execute(
        """
        INSERT INTO occurrence_dates(
          occurrence_date_id, occurrence_id, date_start, date_end, date_type,
          confidence, source_evidence_id, basis, created_at
        ) VALUES (?, ?, ?, ?, 'historical_reference', 'confirmed', ?, ?, ?)
        ON CONFLICT(occurrence_date_id) DO UPDATE SET
          date_start=excluded.date_start,
          date_end=excluded.date_end,
          confidence=excluded.confidence,
          source_evidence_id=excluded.source_evidence_id,
          basis=excluded.basis
        """,
        (
            id_map["date_id"],
            occurrence_id,
            HISTORICAL_DATE,
            HISTORICAL_DATE,
            evidence_ids[0],
            "YouTube説明欄で「ゆうろーど納涼盆踊り大会　亀有銀座商店街　2025年8月31日（日）」を確認。",
            now,
        ),
    )
    prediction_payload = {
        "basis": "2025年は8/31(日)確認。2024年も亀有銀座商店街納涼盆踊り大会の動画実績があり、8月最終週末開催の可能性が高い。2026年8/31は月曜のため直前週末を予測。",
        "evidence_years": [2024, 2025],
        "predicted_date_start": "2026-08-29",
        "predicted_date_end": "2026-08-30",
        "rule_type": "weekday_last",
        "source": "manual_yuroad_gap_review",
        "confidence": "medium",
        "score": 0.66,
    }
    conn.execute(
        """
        INSERT INTO historical_promotion_candidates(
          candidate_id, target_series_id, target_occurrence_id, target_event_name,
          source_types_json, historical_years_json, exact_dates_json,
          year_only_evidence_json, prediction_json, source_occurrence_ids_json,
          evidence_url_count, song_title_count, match_score, promotion_confidence,
          auto_promote_eligible, recommended_action, notes, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 3, ?, 6, 'medium', 0,
          'manual_predicted_date_review', ?, ?, ?)
        ON CONFLICT(candidate_id) DO UPDATE SET
          target_series_id=excluded.target_series_id,
          target_occurrence_id=excluded.target_occurrence_id,
          target_event_name=excluded.target_event_name,
          source_types_json=excluded.source_types_json,
          historical_years_json=excluded.historical_years_json,
          exact_dates_json=excluded.exact_dates_json,
          year_only_evidence_json=excluded.year_only_evidence_json,
          prediction_json=excluded.prediction_json,
          source_occurrence_ids_json=excluded.source_occurrence_ids_json,
          evidence_url_count=excluded.evidence_url_count,
          song_title_count=excluded.song_title_count,
          match_score=excluded.match_score,
          promotion_confidence=excluded.promotion_confidence,
          auto_promote_eligible=excluded.auto_promote_eligible,
          recommended_action=excluded.recommended_action,
          notes=excluded.notes,
          updated_at=excluded.updated_at
        """,
        (
            id_map["historical_candidate_id"],
            series_id,
            occurrence_id,
            EVENT_NAME,
            json.dumps(["youtube_historical", "manual_gap_review"], ensure_ascii=False),
            json.dumps([2024, 2025], ensure_ascii=False),
            json.dumps({"2025": [HISTORICAL_DATE]}, ensure_ascii=False),
            json.dumps({"2024": ["year_confirmed_by_youtube_title"]}, ensure_ascii=False),
            json.dumps([prediction_payload], ensure_ascii=False),
            json.dumps([f"youtube:{video['video_id']}" for video in VIDEOS], ensure_ascii=False),
            len(SONGS),
            "2025年は日付確認済み。2024年は年次実績確認に留め、2026年は8月最終週末レンジで予測。",
            now,
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO predicted_occurrence_dates(
          predicted_date_id, historical_candidate_id, target_series_id,
          target_occurrence_id, target_event_name, predicted_year, date_start,
          date_end, date_status, basis_type, basis_type_label, rule_type, basis,
          confidence, score, application_status, source, source_payload_json,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 2026, '2026-08-29', '2026-08-30',
          'predicted', 'weekday_based', '過去実績からの曜日予測',
          'weekday_last', ?, 'medium', 0.66, 'candidate_for_2026_occurrence',
          'manual_yuroad_gap_review', ?, ?, ?)
        ON CONFLICT(predicted_date_id) DO UPDATE SET
          historical_candidate_id=excluded.historical_candidate_id,
          target_series_id=excluded.target_series_id,
          target_occurrence_id=excluded.target_occurrence_id,
          target_event_name=excluded.target_event_name,
          date_start=excluded.date_start,
          date_end=excluded.date_end,
          date_status=excluded.date_status,
          basis_type=excluded.basis_type,
          basis_type_label=excluded.basis_type_label,
          rule_type=excluded.rule_type,
          basis=excluded.basis,
          confidence=excluded.confidence,
          score=excluded.score,
          application_status=excluded.application_status,
          source=excluded.source,
          source_payload_json=excluded.source_payload_json,
          updated_at=excluded.updated_at
        """,
        (
            id_map["predicted_date_id"],
            id_map["historical_candidate_id"],
            series_id,
            occurrence_id,
            EVENT_NAME,
            prediction_payload["basis"],
            json.dumps(prediction_payload, ensure_ascii=False, sort_keys=True),
            now,
            now,
        ),
    )


def consistency_checks(conn, id_map):
    issues = []
    if conn.execute("PRAGMA foreign_key_check").fetchall():
        issues.append("foreign_key_check_failed")
    occurrence = rows(
        conn,
        "SELECT occurrence_id, date_start, date_status FROM event_occurrences WHERE occurrence_id = ?",
        (id_map["occurrence_id"],),
    )
    if not occurrence:
        issues.append("missing_occurrence_after_apply")
    elif occurrence[0]["date_start"] is not None or occurrence[0]["date_status"] != "unknown":
        issues.append("unexpected_current_year_confirmed_date")
    historical_dates = rows(
        conn,
        "SELECT date_start FROM occurrence_dates WHERE occurrence_id = ? AND date_type = 'historical_reference'",
        (id_map["occurrence_id"],),
    )
    if not historical_dates:
        issues.append("missing_historical_reference_date")
    predicted_dates = rows(
        conn,
        "SELECT date_start, date_end FROM predicted_occurrence_dates WHERE predicted_date_id = ?",
        (id_map["predicted_date_id"],),
    )
    if not predicted_dates:
        issues.append("missing_predicted_occurrence_date")
    return issues


def run(db_path, apply_mode):
    now = now_iso()
    id_map = ids()
    target_db = Path(db_path)
    backup = None
    if apply_mode:
        backup = backup_db(target_db, now)
    else:
        copy_db(target_db, OUT_DB)
        target_db = OUT_DB

    with sqlite3.connect(target_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        before_counts = table_counts(conn)
        before = existing_state(conn, id_map)
        apply(conn, now, id_map)
        issues = consistency_checks(conn, id_map)
        after = existing_state(conn, id_map)
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
        "ids": id_map,
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
