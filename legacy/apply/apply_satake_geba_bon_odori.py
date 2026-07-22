"""Add 2026 Satake Gebageba Bon Odori to the master RDB.

This is a small reviewed manual promotion from X/poster evidence so the event
appears in the public 23-ku information export.
"""

import json

from master_rdb.master_db import connect_existing, json_text, normalize_text, now_utc, refresh_manifest_database_state, stable_id


EVENT_NAME = "佐竹ゲバゲバ盆踊り"
SERIES_NAME = EVENT_NAME
VENUE_NAME = "佐竹商店街アーケード下"
PRIMARY_POST_URL = "https://x.com/pink_daiamond_/status/2068574443304309054"
SECONDARY_POST_URL = "https://x.com/natsutr_bon/status/2067854399612010802"
POSTER_IMAGE_URL = "https://pbs.twimg.com/media/HLUNe-KbsAAYbK_.jpg"
EVENT_DATE = "2026-07-18"


def upsert_one(conn, sql, params):
    conn.execute(sql, params)


def main():
    now = now_utc()
    venue_id = stable_id("venue", VENUE_NAME, "東京都台東区台東3-4丁目 佐竹商店街")
    series_id = stable_id("series", "satake-geba-bon-odori")
    occurrence_id = stable_id("occ", EVENT_NAME, EVENT_DATE, VENUE_NAME)

    conn = connect_existing()
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        with conn:
            upsert_one(
                conn,
                """
                INSERT INTO venues (
                  venue_id, origin, canonical_name, normalized_name, area, address,
                  access, scale, public_intro, past_memo, source_url, latitude,
                  longitude, review_status, created_at, updated_at
                ) VALUES (?, 'curated', ?, ?, '台東区', ?, ?, '中', ?, ?, ?, ?, ?, 'active', ?, ?)
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
                  latitude=excluded.latitude,
                  longitude=excluded.longitude,
                  review_status='active',
                  updated_at=excluded.updated_at
                """,
                (
                    venue_id,
                    VENUE_NAME,
                    normalize_text(VENUE_NAME),
                    "東京都台東区台東3-4丁目 佐竹商店街",
                    "都営大江戸線・つくばエクスプレス 新御徒町駅A2出口すぐ",
                    "新御徒町駅近くの佐竹商店街アーケード下で開かれる街なかの盆踊り会場。",
                    "2026年ポスターで「雨天決行」「駐車場はありません」と案内。",
                    None,
                    35.7062817,
                    139.7812630,
                    now,
                    now,
                ),
            )
            upsert_one(
                conn,
                """
                INSERT INTO event_series (
                  series_id, origin, series_key, canonical_name, normalized_name,
                  usual_venue_id, area, program_type, annual_months_json,
                  schedule_rule_type, schedule_rule_detail, public_intro, source_url,
                  status, created_at, updated_at
                ) VALUES (?, 'curated', ?, ?, ?, ?, '台東区', 'bon_odori', ?, NULL, NULL, ?, ?, 'active', ?, ?)
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
                    "satake-geba-bon-odori",
                    SERIES_NAME,
                    normalize_text(SERIES_NAME),
                    venue_id,
                    json_text([7]),
                    "佐竹商店街夏祭り「サタケオドリ」内で開かれる、第1回の佐竹ゲバゲバ盆踊り。",
                    None,
                    now,
                    now,
                ),
            )
            detail = "\n".join(
                [
                    "2026年ポスター画像で、佐竹商店街夏祭り「サタケオドリ」内の第1回佐竹ゲバゲバ盆踊りを確認。",
                    "開催日は2026年7月18日(土)。アートマーケットは13:00-19:00、佐竹ゲバゲバ盆踊りは15:00-19:00。会場は佐竹商店街アーケード下で、新御徒町駅A2出口すぐ。雨天決行、駐車場なし。",
                    "投稿では「40年ぶりの復活開催」とされ、練習会投稿では新ご当地曲「佐竹音頭」から定番曲、アニソンまで踊る旨が確認できる。",
                    "主催: 佐竹商店街振興組合。協力: 佐竹町会。後援: 台東区。ポスター作画・一部デザイン: 広井チムニー。",
                    "追加証拠",
                    f"- 出典URL: {PRIMARY_POST_URL}",
                    f"- 追加出典URL: {SECONDARY_POST_URL}",
                ]
            )
            upsert_one(
                conn,
                """
                INSERT INTO event_occurrences (
                  occurrence_id, origin, series_id, event_year, occurrence_sequence,
                  display_name, venue_id, date_start, date_end, date_status,
                  lifecycle_status, confidence, source_kind, source_url,
                  inherited_from_occurrence_id, public_intro_override, detail,
                  created_at, updated_at
                ) VALUES (?, 'curated', ?, 2026, 1, ?, ?, ?, ?, 'confirmed', 'published', 'confirmed',
                  'notion_events', ?, NULL, ?, ?, ?, ?)
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
                    EVENT_DATE,
                    EVENT_DATE,
                    None,
                    "佐竹商店街夏祭り「サタケオドリ」内で、2026年7月18日(土)15:00-19:00に開かれる第1回の盆踊り。",
                    detail,
                    now,
                    now,
                ),
            )
            date_id = stable_id("date", occurrence_id, EVENT_DATE, "confirmed")
            upsert_one(
                conn,
                """
                INSERT INTO occurrence_dates (
                  occurrence_date_id, occurrence_id, date_start, date_end, date_type,
                  confidence, source_evidence_id, basis, created_at
                ) VALUES (?, ?, ?, ?, 'confirmed', 'confirmed', NULL, ?, ?)
                ON CONFLICT(occurrence_date_id) DO UPDATE SET
                  date_start=excluded.date_start,
                  date_end=excluded.date_end,
                  confidence=excluded.confidence,
                  basis=excluded.basis
                """,
                (
                    date_id,
                    occurrence_id,
                    EVENT_DATE,
                    EVENT_DATE,
                    "ポスター画像で2026年7月18日(土)開催を確認。",
                    now,
                ),
            )

            evidence_rows = [
                (
                    stable_id("ev", "x", "2068574443304309054"),
                    "x",
                    "poster_post",
                    "pink_daiamond_",
                    "2068574443304309054",
                    "@pink_daiamond_",
                    "ゲバゲバ盆踊り7月18日＠新御徒町",
                    "ゲバゲバ盆踊り7月18日＠新御徒町。開催場所は日本2番目に古い佐竹商店街。40年ぶりの復活開催。雨でも安心、アーケード下。",
                    PRIMARY_POST_URL,
                    "2026-06-21T05:59:14+00:00",
                    {"media_url": POSTER_IMAGE_URL},
                ),
                (
                    stable_id("ev", "x", "2067854399612010802"),
                    "x",
                    "practice_post",
                    "natsutr_bon",
                    "2067854399612010802",
                    "@natsutr_bon",
                    "佐竹商店街ゲバゲバ盆踊り練習会",
                    "佐竹商店街ゲバゲバ盆踊りの練習会。新ご当地曲「佐竹音頭」から定番曲、アニソンまで。本番は7/18(土)。",
                    SECONDARY_POST_URL,
                    "2026-06-19T06:18:02+00:00",
                    {"media_url": "https://pbs.twimg.com/media/HLJWUOnagAA7yKC.jpg"},
                ),
            ]
            for evidence in evidence_rows:
                upsert_one(
                    conn,
                    """
                    INSERT INTO evidence_items (
                      evidence_id, platform, evidence_type, source_key, source_id,
                      account_key, title, text_excerpt, url, published_at, observed_at,
                      detected_event_date, raw_status, raw_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'reviewed', ?)
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
                    evidence[:10] + (now, EVENT_DATE, json.dumps(evidence[10], ensure_ascii=False, sort_keys=True)),
                )
                upsert_one(
                    conn,
                    """
                    INSERT INTO occurrence_evidence_links (
                      occurrence_id, evidence_id, target, link_status, confidence, notes
                    ) VALUES (?, ?, 'date_venue_program', 'accepted', 0.92, ?)
                    ON CONFLICT(occurrence_id, evidence_id, target) DO UPDATE SET
                      link_status=excluded.link_status,
                      confidence=excluded.confidence,
                      notes=excluded.notes
                    """,
                    (occurrence_id, evidence[0], "2026年開催日・会場・曲目ヒントの根拠として採用。"),
                )

            songs = [
                ("佐竹音頭", "ご当地曲", 95, "high", "練習会投稿で新ご当地曲として確認。"),
                ("電線マン音頭", "未分類", 85, "medium", "告知投稿の曲目例として確認。"),
                ("クックロビン音頭", "未分類", 85, "medium", "告知投稿の曲目例として確認。"),
                ("ダンシングヒーロー", "定番曲", 85, "medium", "練習会投稿の「ダンヒロ」を既存曲名へ正規化。"),
            ]
            for title, category, probability, confidence, notes in songs:
                normalized = normalize_text(title)
                song_id_row = conn.execute(
                    "SELECT song_id FROM songs WHERE normalized_title = ?",
                    (normalized,),
                ).fetchone()
                song_id = song_id_row[0] if song_id_row else stable_id("song", title)
                upsert_one(
                    conn,
                    """
                    INSERT INTO songs (
                      song_id, canonical_title, normalized_title, category, status,
                      prior_tier, target_area, evidence_count, source_url, memo,
                      created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'active', NULL, NULL, 1, ?, ?, ?, ?)
                    ON CONFLICT(song_id) DO UPDATE SET
                      canonical_title=excluded.canonical_title,
                      normalized_title=excluded.normalized_title,
                      category=COALESCE(songs.category, excluded.category),
                      status='active',
                      source_url=COALESCE(songs.source_url, excluded.source_url),
                      memo=COALESCE(songs.memo, excluded.memo),
                      updated_at=excluded.updated_at
                    """,
                    (
                        song_id,
                        title,
                        normalized,
                        category,
                        SECONDARY_POST_URL if title in {"佐竹音頭", "ダンシングヒーロー"} else PRIMARY_POST_URL,
                        notes,
                        now,
                        now,
                    ),
                )
                occurrence_song_id = stable_id("osong", occurrence_id, normalized, "setlist")
                upsert_one(
                    conn,
                    """
                    INSERT INTO occurrence_songs (
                      occurrence_song_id, origin, occurrence_id, song_id, song_title_raw,
                      normalized_title, role, evidence_status, probability, confidence,
                      source_count, evidence_count, inherited_from_year,
                      first_observed_at, last_observed_at, notes, created_at, updated_at
                    ) VALUES (?, 'curated', ?, ?, ?, ?, 'setlist', 'announced', ?, ?, 1, 1, NULL, ?, ?, ?, ?, ?)
                    ON CONFLICT(occurrence_id, normalized_title, role) DO UPDATE SET
                      song_id=excluded.song_id,
                      song_title_raw=excluded.song_title_raw,
                      evidence_status=excluded.evidence_status,
                      probability=excluded.probability,
                      confidence=excluded.confidence,
                      source_count=excluded.source_count,
                      evidence_count=excluded.evidence_count,
                      first_observed_at=excluded.first_observed_at,
                      last_observed_at=excluded.last_observed_at,
                      notes=excluded.notes,
                      updated_at=excluded.updated_at
                    """,
                    (
                        occurrence_song_id,
                        occurrence_id,
                        song_id,
                        title,
                        normalized,
                        probability,
                        confidence,
                        "2026-06-19T06:18:02+00:00",
                        "2026-06-21T05:59:14+00:00",
                        json_text({"basis": "current_announcement", "note": notes}),
                        now,
                        now,
                    ),
                )
        refresh_manifest_database_state()
    finally:
        conn.close()

    print(f"registered {EVENT_NAME}: occurrence_id={occurrence_id}, venue_id={venue_id}")


if __name__ == "__main__":
    main()
