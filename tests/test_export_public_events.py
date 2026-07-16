import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from export_public_events import (
    apply_public_recurrence_metadata,
    apply_public_site_postprocessors,
    apply_public_event_overrides,
    apply_public_event_name_cleanup,
    build_public_events_from_master,
    clean_public_event_name,
    extract_public_source_urls,
    fill_youtube_evidence_defaults,
    fixed_date_rule_from_props,
    load_rdb_public_date_predictions,
    merge_prediction_payloads,
    merge_song_occurrence_hints,
    parse_youtube_evidence,
    public_export_today,
    public_event_source_map,
    public_detail_text,
    sanitize_public_event_details,
    strip_public_internal_event_fields,
    suppress_replaced_recurring_events,
    write_public_js,
)


class ExportPublicEventsTest(unittest.TestCase):
    def test_public_export_today_can_be_fixed_by_environment(self):
        with patch.dict("os.environ", {"BON_ODORI_PUBLIC_TODAY": "2026-07-16"}):
            self.assertEqual(public_export_today().isoformat(), "2026-07-16")

    def test_public_export_today_rejects_invalid_environment_date(self):
        with patch.dict("os.environ", {"BON_ODORI_PUBLIC_TODAY": "not-a-date"}):
            with self.assertRaises(ValueError):
                public_export_today()

    def test_site_postprocessors_use_export_today_for_historical_slide_expiry(self):
        events = [{
            "name": "西綾瀬町会 夏祭り盆踊り大会",
            "venue": "五反野コミュニティ公園",
            "public_category": "recurring_last_year",
            "public_status": "expected_medium",
            "recurrence_score": 0.67,
            "last_seen_year": 2025,
            "last_seen_dates": ["2025-06-21"],
            "date": "2025-06-21",
        }]

        result = apply_public_site_postprocessors(events, today="2026-06-26")

        self.assertEqual(result[0]["historical_display_tier"], "historical_reference")
        self.assertEqual(result[0]["display_tier"], "historical_reference")
        self.assertNotIn("historical_slide", result[0])
        self.assertNotIn("predicted_date", result[0])

    def test_load_rdb_public_date_predictions_matches_public_prediction_shape(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            conn = sqlite3.connect(db)
            try:
                conn.execute(
                    """
                    CREATE TABLE predicted_occurrence_dates (
                      predicted_date_id TEXT PRIMARY KEY,
                      historical_candidate_id TEXT,
                      target_series_id TEXT,
                      target_occurrence_id TEXT,
                      target_event_name TEXT,
                      predicted_year INTEGER,
                      date_start TEXT,
                      date_end TEXT,
                      date_status TEXT,
                      rule_type TEXT,
                      basis TEXT,
                      confidence TEXT,
                      score REAL,
                      application_status TEXT,
                      source TEXT,
                      source_payload_json TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO predicted_occurrence_dates VALUES (
                      'preddate_1', 'cand_1', 'ser_1', 'occ_1',
                      '丸の内de盆踊り', 2026, '2026-07-31', '2026-07-31',
                      'predicted', 'weekday_last', '7月の最終金曜',
                      'medium', 0.74, 'candidate_for_2026_occurrence',
                      'event_date_predictions',
                      '{"series_key":"s1","venue":"行幸通り","evidence_years":[2024,2025]}'
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

            payload = load_rdb_public_date_predictions(db, target_year=2026)

        self.assertEqual(payload["source"], "master_rdb.predicted_occurrence_dates")
        self.assertEqual(payload["summary"]["prediction_count"], 1)
        row = payload["predictions"][0]
        self.assertEqual(row["event_name"], "丸の内de盆踊り")
        self.assertEqual(row["venue"], "行幸通り")
        self.assertEqual(row["prediction"]["predicted_weekday_start"], "金")
        self.assertEqual(row["prediction"]["evidence_count"], 2)

    def test_merge_prediction_payloads_keeps_json_only_fallback_rows(self):
        primary = {
            "summary": {},
            "predictions": [{
                "event_name": "丸の内de盆踊り",
                "venue": "行幸通り",
                "prediction": {"predicted_date_start": "2026-07-31"},
            }],
        }
        fallback = {
            "predictions": [
                {
                    "event_name": "丸の内de盆踊り",
                    "venue": "行幸通り",
                    "prediction": {"predicted_date_start": "2026-07-31"},
                },
                {
                    "event_name": "東本願寺盆踊り",
                    "venue": "東本願寺（浅草）",
                    "prediction": {"predicted_date_start": "2026-08-19"},
                },
            ]
        }

        merged = merge_prediction_payloads(primary, fallback)

        self.assertEqual(len(merged["predictions"]), 2)
        self.assertEqual(merged["summary"]["json_fallback_count"], 1)
        self.assertEqual(merged["summary"]["json_fallback"][0]["event_name"], "東本願寺盆踊り")

    def test_master_export_does_not_mix_current_start_with_historical_end(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            conn = sqlite3.connect(db)
            try:
                self._create_minimal_master_export_schema(conn)
                conn.execute(
                    """
                    INSERT INTO event_series VALUES (
                      'ser_1', '森下二丁目納涼盆踊り大会', '[7]', NULL, 'active'
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO venues VALUES (
                      'ven_1', '森下公園', '江東区', '中', '', '', '', '', NULL, NULL, 'active'
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO event_occurrences VALUES (
                      'occ_1', 'ser_1', 'ven_1', '森下二丁目納涼盆踊り大会',
                      2026, '2026-07-19', NULL, 'confirmed', 'published',
                      'high', 'official_current_year', 'https://example.com', NULL, '',
                      'curated'
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO occurrence_dates VALUES (
                      'occ_1', 'historical_reference', '2025-07-19', '2025-07-20'
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

            events, _, _, _ = build_public_events_from_master(db)

        self.assertEqual(events[0]["date"], "2026-07-19")
        self.assertIsNone(events[0]["date_end"])

    def test_master_export_ignores_historical_references_before_previous_year(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            conn = sqlite3.connect(db)
            try:
                self._create_minimal_master_export_schema(conn)
                conn.execute(
                    """
                    INSERT INTO event_series VALUES (
                      'ser_1', '古い参考だけの盆踊り', '[8]', NULL, 'active'
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO venues VALUES (
                      'ven_1', '古い公園', '江東区', '小', '', '', '', '', NULL, NULL, 'active'
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO event_occurrences VALUES (
                      'occ_1', 'ser_1', 'ven_1', '古い参考だけの盆踊り',
                      2026, NULL, NULL, 'unknown', 'published',
                      'medium', '', '', NULL, '',
                      'curated'
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO occurrence_dates VALUES (
                      'occ_1', 'historical_reference', '2024-08-10', '2024-08-11'
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

            events, _, _, _ = build_public_events_from_master(db)

        self.assertIsNone(events[0]["date"])
        self.assertIsNone(events[0]["date_end"])

    def _create_minimal_master_export_schema(self, conn):
        conn.executescript(
            """
            CREATE TABLE event_series (
              series_id TEXT PRIMARY KEY,
              canonical_name TEXT,
              annual_months_json TEXT,
              public_intro TEXT,
              status TEXT
            );
            CREATE TABLE venues (
              venue_id TEXT PRIMARY KEY,
              canonical_name TEXT,
              area TEXT,
              scale TEXT,
              access TEXT,
              address TEXT,
              past_memo TEXT,
              public_intro TEXT,
              latitude REAL,
              longitude REAL,
              review_status TEXT
            );
            CREATE TABLE event_occurrences (
              occurrence_id TEXT PRIMARY KEY,
              series_id TEXT,
              venue_id TEXT,
              display_name TEXT,
              event_year INTEGER,
              date_start TEXT,
              date_end TEXT,
              date_status TEXT,
              lifecycle_status TEXT,
              confidence TEXT,
              source_kind TEXT,
              source_url TEXT,
              public_intro_override TEXT,
              detail TEXT,
              origin TEXT DEFAULT 'curated'
            );
            CREATE TABLE occurrence_dates (
              occurrence_id TEXT,
              date_type TEXT,
              date_start TEXT,
              date_end TEXT
            );
            CREATE TABLE occurrence_songs (
              occurrence_id TEXT,
              song_title_raw TEXT,
              evidence_status TEXT,
              probability REAL,
              confidence TEXT,
              source_count INTEGER,
              evidence_count INTEGER,
              inherited_from_year INTEGER
            );
            """
        )

    def test_fixed_date_rule_from_props_reads_machine_columns(self):
        rule = fixed_date_rule_from_props({
            "固定日開始月": {"type": "number", "number": 8},
            "固定日開始日": {"type": "number", "number": 1},
            "固定日終了月": {"type": "number", "number": 8},
            "固定日終了日": {"type": "number", "number": 2},
            "固定日根拠URL": {"type": "url", "url": "https://example.com/hanazono"},
        })

        self.assertEqual(rule, {
            "rule_type": "fixed_date_range",
            "month": 8,
            "day": 1,
            "end_month": 8,
            "end_day": 2,
            "source_url": "https://example.com/hanazono",
            "basis": "イベントDBの固定日カラムに記録",
        })

    def test_parse_youtube_evidence_block(self):
        detail = "\n".join([
            "2025-07-19〜2025-07-21 開催予定。",
            "",
            "[youtube_evidence] 2025実績証拠",
            "- 対象イベント: 自由が丘納涼盆踊り大会",
            "- 検出日付: 2025-07-21",
            "- 動画: https://www.youtube.com/watch?v=mvHqQY2ISJE",
            "- チャンネル: 和太鼓お祭りチャンネル",
            "- サムネイル: https://i.ytimg.com/vi/mvHqQY2ISJE/maxresdefault.jpg",
            "- 曲目候補: 北海盆唄, 炭坑節, 大東京音頭",
        ])

        rows = parse_youtube_evidence(detail)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["label"], "2025実績証拠")
        self.assertEqual(rows[0]["event_name"], "自由が丘納涼盆踊り大会")
        self.assertEqual(rows[0]["detected_date"], "2025-07-21")
        self.assertEqual(rows[0]["video_url"], "https://www.youtube.com/watch?v=mvHqQY2ISJE")
        self.assertEqual(rows[0]["channel"], "和太鼓お祭りチャンネル")
        self.assertEqual(rows[0]["thumbnail_url"], "https://i.ytimg.com/vi/mvHqQY2ISJE/maxresdefault.jpg")
        self.assertEqual(rows[0]["songs"], ["北海盆唄", "炭坑節", "大東京音頭"])

    def test_ignores_block_without_video_url(self):
        self.assertEqual(parse_youtube_evidence("[youtube_evidence]\n- 曲目候補: 東京音頭"), [])

    def test_fill_youtube_evidence_defaults(self):
        rows = [{"event_name": "", "detected_date": "", "video_url": "https://www.youtube.com/watch?v=abc"}]

        filled = fill_youtube_evidence_defaults(rows, "丸の内de盆踊り", "2025-07-25")

        self.assertEqual(filled[0]["event_name"], "丸の内de盆踊り")
        self.assertEqual(filled[0]["detected_date"], "2025-07-25")

    def test_public_detail_text_hides_internal_youtube_evidence(self):
        detail = "\n".join([
            "2026-07-29〜2026-08-01 開催予定。[B1] 公式発表を確認。",
            "",
            "[youtube_evidence] YouTube 2025公式URL確認済み証拠",
            "- 対象イベント: 築地本願寺納涼盆踊り大会",
            "- 公式確認URL: https://tokyofesta.com/23ku/23763/",
            "- 動画: https://www.youtube.com/watch?v=abc",
        ])

        public = public_detail_text(detail)

        self.assertIn("2026-07-29〜2026-08-01 開催予定。公式発表を確認。", public)
        self.assertNotIn("[B1]", public)
        self.assertNotIn("[youtube_evidence]", public)
        self.assertNotIn("YouTube", public)
        self.assertNotIn("https://", public)

    def test_public_detail_text_hides_internal_fixed_date_rule_note(self):
        detail = "\n".join([
            "毎年6/13〜15開催。曜日は年により変動",
            "",
            "[fixed_date_rule] おと（Codex）固定日ルール記録",
            "- 固定日: 毎年6/13〜6/15",
            "- 根拠: 公開データの詳細に明記",
        ])

        public = public_detail_text(detail)

        self.assertEqual(public, "毎年6/13〜15開催。曜日は年により変動")
        self.assertNotIn("おと（Codex）", public)
        self.assertNotIn("固定日ルール記録", public)

    def test_sanitize_public_event_details_hides_existing_internal_evidence(self):
        rows = sanitize_public_event_details([{
            "name": "郡上おどり in 青山 2026",
            "detail": "2026開催予定。公式URL: https://example.com\n\n[youtube_evidence] 内部ログ\n- 動画: https://www.youtube.com/watch?v=abc",
            "source_urls": [
                {"label": "公式告知あり", "url": "https://example.com/news/", "kind": "official"},
                {"label": "公式告知あり", "url": "https://example.com/news/20260610/", "kind": "official"},
            ],
            "songs": [
                {"name": "まつり", "confidence": "confirmed", "source_count": 2, "probability": 95, "basis": "current_hint", "basis_label": "今年ヒント", "evidence_count": 1},
                {"name": "LOVEマシーン", "confidence": "hint", "source_count": 1, "speaker_count": 1, "probability": 80, "basis": "current_hint", "basis_label": "今年ヒント", "evidence_count": 1},
            ],
        }])

        self.assertEqual(rows[0]["detail"], "2026開催予定。")
        self.assertEqual(rows[0]["source_urls"], [
            {"label": "公式告知あり", "url": "https://example.com/news/20260610/", "kind": "official"}
        ])
        self.assertEqual([song["name"] for song in rows[0]["songs"]], ["LOVEマシーン"])
        self.assertEqual(rows[0]["songs"][0], {
            "name": "LOVEマシーン",
            "confidence": "hint",
            "probability": 80,
            "basis": "current_hint",
            "basis_label": "今年ヒント",
        })

    def test_sanitize_public_event_details_hides_fixed_date_rule_field(self):
        rows = sanitize_public_event_details([{
            "name": "花園神社 盆踊り",
            "name_confirmed": True,
            "venue": "花園神社",
            "area": "新宿区",
            "months": [8],
            "hints": [],
            "jun": {},
            "detail": "毎年8月1日・2日開催。",
            "source_urls": [],
            "songs": [],
            "fixed_date_rule": {
                "rule_type": "fixed_date_range",
                "month": 8,
                "day": 1,
                "end_month": 8,
                "end_day": 2,
                "basis": "内部ルール",
            },
        }])

        self.assertNotIn("fixed_date_rule", rows[0])

    def test_merge_song_occurrence_hints_preserves_confirmed_observed_songs(self):
        songs = merge_song_occurrence_hints(
            [{"name": "東京音頭", "confidence": "hint"}],
            {
                "songs": [
                    {
                        "name": "東京音頭",
                        "confidence": "confirmed",
                        "basis": "current_observed",
                        "basis_label": "実測",
                    },
                    {
                        "name": "銀座カンカン娘",
                        "confidence": "confirmed",
                        "basis": "current_observed",
                        "basis_label": "実測",
                    },
                ]
            },
        )

        self.assertEqual([song["name"] for song in songs], ["東京音頭", "銀座カンカン娘"])
        self.assertEqual([song["confidence"] for song in songs], ["confirmed", "confirmed"])
        self.assertEqual([song["basis"] for song in songs], ["current_observed", "current_observed"])
        self.assertEqual([song["basis_label"] for song in songs], ["実測", "実測"])


    def test_extract_public_source_urls_keeps_official_urls_not_video_urls(self):
        detail = "\n".join([
            "2026発表 https://t.co/abc",
            "[youtube_evidence] YouTube 2025公式URL確認済み証拠",
            "- 公式確認URL: https://tokyofesta.com/23ku/23763/",
            "- YouTube検出元URL: https://www.nouryo-matsuri.com/pages/6314608/page_202208061239",
            "- 動画: https://www.youtube.com/watch?v=abc",
        ])

        sources = extract_public_source_urls(detail)

        self.assertEqual(
            sources,
            [
                {"label": "公式告知あり", "url": "https://www.nouryo-matsuri.com/pages/6314608/page_202208061239", "kind": "official"},
                {"label": "告知HPあり", "url": "", "kind": "web", "count": 1},
                {"label": "告知投稿あり", "url": "", "kind": "post", "count": 1},
            ],
        )

    def test_extract_public_source_urls_excludes_stale_official_urls(self):
        detail = "\n".join([
            "[youtube_evidence] YouTube 2025公式URL確認済み証拠",
            "- YouTube検出元URL: https://tsukijihongwanji.jp/news/10279/",
            "- 動画: https://www.youtube.com/watch?v=abc",
        ])

        self.assertEqual(extract_public_source_urls(detail), [])

    def test_extract_public_source_urls_collapses_multiple_notice_urls(self):
        detail = "\n".join([
            "発表 https://x.com/example/status/1",
            "続報 https://twitter.com/example/status/2",
            "短縮 https://t.co/abc",
        ])

        self.assertEqual(extract_public_source_urls(detail), [{"label": "告知投稿あり", "url": "", "kind": "post", "count": 3}])

    def test_clean_public_event_name_removes_schedule_tail(self):
        self.assertEqual(
            clean_public_event_name("大森南一丁目自治会「納涼盆踊り大会」7月21日(月)-22日(火) 18:30-20:00。"),
            "大森南一丁目自治会「納涼盆踊り大会」",
        )
        self.assertEqual(
            clean_public_event_name("下代田東町会 「下代田東子供祭り・納涼祭り』 7月19日(土)-20日(日) 16時-21時。"),
            "下代田東町会 「下代田東子供祭り・納涼祭り」",
        )
        self.assertEqual(
            clean_public_event_name("「喜多見盆踊り大会」 7月26日(土)-27日(日)。"),
            "喜多見盆踊り大会",
        )
        self.assertEqual(
            clean_public_event_name("第10回 すみだ輪おどり区民感謝デー"),
            "第10回 すみだ輪おどり区民感謝デー",
        )
        self.assertEqual(
            clean_public_event_name("盆踊 〜BONDO〜"),
            "盆踊 〜BONDO〜",
        )
        self.assertEqual(
            clean_public_event_name("「葛飾菖蒲まつり 水元公園会場 民踊パレード 5月31日(日)。"),
            "葛飾菖蒲まつり 水元公園会場 民踊パレード",
        )

    def test_apply_public_event_name_cleanup_disambiguates_same_name_different_venues(self):
        rows = apply_public_event_name_cleanup([
            {"name": "品川区民まつり 大崎第一地区", "venue": "第一日野小学校", "area": "品川区"},
            {"name": "品川区民まつり 大崎第一地区", "venue": "第四日野小学校", "area": "品川区"},
        ])

        self.assertEqual(rows[0]["display_name"], "品川区民まつり 大崎第一地区（第一日野小学校）")
        self.assertEqual(rows[1]["display_name"], "品川区民まつり 大崎第一地区（第四日野小学校）")

    def test_public_event_source_map_keeps_occurrence_id_out_of_public_json(self):
        rows = [
            {
                "name": "中央公園盆踊り",
                "venue": "中央公園",
                "date": "2026-07-20",
                "date_end": "",
                "_source": "master_rdb",
                "_occurrence_id": "occ1",
                "_series_id": "series1",
                "_event_year": 2026,
                "_venue_id": "venue1",
                "songs": [],
            }
        ]

        sidecar = public_event_source_map(rows)
        public_rows = strip_public_internal_event_fields(rows)

        self.assertEqual(sidecar["mapped_count"], 1)
        self.assertEqual(sidecar["rows"][0]["occurrence_id"], "occ1")
        self.assertEqual(sidecar["rows"][0]["public_event_key"], "中央公園盆踊り|中央公園|2026-07-20|")
        self.assertNotIn("_occurrence_id", public_rows[0])
        self.assertNotIn("_series_id", public_rows[0])

    def test_apply_public_recurrence_metadata_adds_production_fields(self):
        rows = apply_public_recurrence_metadata([{
            "name": "第70回 恵比寿駅前盆踊り大会",
            "venue": "JR恵比寿駅西口広場",
            "area": "渋谷区",
            "date": "2025-07-25",
            "date_end": "2025-07-26",
            "status": "開催終了",
        }])

        self.assertEqual(rows[0]["public_category"], "recurring_last_year")
        self.assertGreaterEqual(rows[0]["recurrence_score"], 0.55)
        self.assertEqual(rows[0]["edition_number"], 70)
        self.assertEqual(rows[0]["last_seen_year"], 2025)

    def test_suppress_replaced_recurring_events_keeps_2026_over_2025(self):
        rows = apply_public_recurrence_metadata([
            {
                "name": "西綾瀬町会 夏祭り盆踊り大会",
                "venue": "五反野コミュニティ公園",
                "area": "足立区",
                "date": "2026-06-20",
                "status": "確認済み",
            },
            {
                "name": "西綾瀬町会 夏祭り盆踊り大会",
                "venue": "五反野コミュニティ公園",
                "area": "足立区",
                "date": "2025-06-21",
                "status": "終了",
                "songs": [
                    {
                        "name": "まつり",
                        "confidence": "hint",
                        "source_count": 1,
                        "probability": 80,
                        "basis": "current_hint",
                        "evidence_count": 1,
                    },
                ],
            },
            {
                "name": "郡上おどり in 青山 2026",
                "venue": "秩父宮ラグビー場駐車場",
                "area": "港区",
                "date": "2026-06-26",
                "status": "確認済み",
                "songs": [{"name": "郡上おどり", "confidence": "confirmed", "source_count": 2, "probability": 95}],
            },
            {
                "name": "郡上おどり in 青山 2025",
                "venue": "秩父宮ラグビー場駐車場",
                "area": "港区",
                "date": "2025-06-20",
                "status": "終了",
                "songs": [
                    {"name": "郡上おどり", "confidence": "confirmed", "source_count": 2, "probability": 95},
                    {"name": "かわさき", "confidence": "hint", "source_count": 1, "probability": 80},
                    {"name": "春駒", "confidence": "hint", "source_count": 1, "probability": 80},
                ],
            },
        ])

        filtered = suppress_replaced_recurring_events(rows)

        self.assertEqual([row["name"] for row in filtered], [
            "西綾瀬町会 夏祭り盆踊り大会",
            "郡上おどり in 青山",
        ])
        self.assertEqual(filtered[0].get("songs"), [])
        self.assertEqual([song["name"] for song in filtered[1]["songs"]], ["かわさき", "春駒"])
        self.assertEqual(filtered[1]["songs"][0]["basis_label"], "2025年ヒント")
        self.assertNotIn("source_count", filtered[1]["songs"][0])

    def test_suppress_replaced_recurring_events_matches_numbered_bon_odori_variant(self):
        rows = apply_public_recurrence_metadata([
            {
                "name": "新橋こいち祭",
                "venue": "桜田公園",
                "area": "港区",
                "date": "2026-07-23",
                "date_end": "2026-07-24",
                "status": "確認済み",
            },
            {
                "name": "第28回新橋こいち祭 盆踊り",
                "venue": "桜田公園",
                "area": "港区",
                "date": "2025-07-24",
                "status": "終了",
                "songs": [
                    {"name": "東京音頭", "confidence": "hint", "source_count": 2, "probability": 80},
                    {"name": "新橋音頭", "confidence": "hint", "source_count": 2, "probability": 80},
                ],
            },
        ])

        filtered = suppress_replaced_recurring_events(rows)

        self.assertEqual([row["name"] for row in filtered], ["新橋こいち祭"])
        self.assertEqual([song["name"] for song in filtered[0]["songs"]], ["新橋音頭", "東京音頭"])
        self.assertEqual(filtered[0]["songs"][0]["basis_label"], "2025年ヒント")

    def test_sanitize_public_event_details_drops_empty_fallbacks(self):
        rows = sanitize_public_event_details([
            {
                "name": "あかつき公園の盆踊り",
                "name_confirmed": False,
                "area": "中央区",
                "months": [],
                "hints": [],
                "date": None,
                "status": None,
                "lat": None,
                "lng": None,
                "songs": [],
            },
            {
                "name": "築地本願寺納涼盆踊り大会",
                "name_confirmed": True,
                "area": "中央区",
                "date": "2026-07-29",
                "status": "確認済み",
            },
        ])

        self.assertEqual([row["name"] for row in rows], ["築地本願寺納涼盆踊り大会"])

    def test_apply_public_event_overrides_patches_reviewed_public_rows(self):
        rows = apply_public_event_overrides(
            [
                {
                    "name": "品川区民まつり 荏原第五地区",
                    "venue": "旧杜松小学校",
                    "area": "品川区",
                    "date": None,
                    "status": "未確認",
                    "season_hint": {"label": "8月下旬"},
                },
                {
                    "name": "品川区民まつり 品川第二地区",
                    "venue": "天妙国寺",
                    "area": "品川区",
                    "description": "城南小学校を会場に行われる品川区民まつりの地域イベント。",
                },
            ],
            {
                "overrides": [
                    {
                        "match": {"name": "品川区民まつり 荏原第五地区", "venue": "旧杜松小学校"},
                        "remove": ["season_hint"],
                        "set": {
                            "venue": "杜松ホーム",
                            "date": "2026-07-18",
                            "status": "確認済み",
                        },
                    },
                    {
                        "match": {"name": "品川区民まつり 品川第二地区", "venue": "天妙国寺"},
                        "set": {"description": "天妙国寺を会場に行われる品川区民まつりの地域イベント。"},
                    },
                ]
            },
        )

        self.assertEqual(rows[0]["venue"], "杜松ホーム")
        self.assertEqual(rows[0]["date"], "2026-07-18")
        self.assertNotIn("season_hint", rows[0])
        self.assertEqual(rows[1]["description"], "天妙国寺を会場に行われる品川区民まつりの地域イベント。")

    def test_apply_public_event_overrides_skips_reviewed_hold_rows(self):
        rows = apply_public_event_overrides(
            [
                {
                    "name": "銀座一丁目東町会・新富町会 納涼盆踊り大会",
                    "venue": "京橋プラザ区民館",
                    "area": "中央区",
                    "date": None,
                    "status": "未確認",
                },
                {
                    "name": "鉄砲洲納涼盆踊り",
                    "venue": "鉄砲洲公園",
                    "area": "中央区",
                    "date": "2026-08-03",
                    "status": "確認済み",
                },
            ],
            {
                "overrides": [
                    {
                        "match": {
                            "name": "銀座一丁目東町会・新富町会 納涼盆踊り大会",
                            "venue": "京橋プラザ区民館",
                        },
                        "skip": True,
                    }
                ]
            },
        )

        self.assertEqual([row["name"] for row in rows], ["鉄砲洲納涼盆踊り"])

    def test_master_export_uses_historical_reference_date_for_unknown_2026_occurrence(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "master.sqlite"
            with sqlite3.connect(db_path) as conn:
                conn.executescript(
                    """
                    CREATE TABLE venues (
                      venue_id TEXT PRIMARY KEY,
                      canonical_name TEXT,
                      area TEXT,
                      scale TEXT,
                      access TEXT,
                      address TEXT,
                      past_memo TEXT,
                      public_intro TEXT,
                      latitude REAL,
                      longitude REAL,
                      review_status TEXT
                    );
                    CREATE TABLE event_series (
                      series_id TEXT PRIMARY KEY,
                      canonical_name TEXT,
                      annual_months_json TEXT,
                      public_intro TEXT,
                      status TEXT
                    );
                    CREATE TABLE event_occurrences (
                      occurrence_id TEXT PRIMARY KEY,
                      origin TEXT,
                      series_id TEXT,
                      event_year INTEGER,
                      display_name TEXT,
                      venue_id TEXT,
                      date_start TEXT,
                      date_end TEXT,
                      date_status TEXT,
                      lifecycle_status TEXT,
                      confidence TEXT,
                      source_kind TEXT,
                      source_url TEXT,
                      public_intro_override TEXT,
                      detail TEXT
                    );
                    CREATE TABLE occurrence_dates (
                      occurrence_date_id TEXT PRIMARY KEY,
                      occurrence_id TEXT,
                      date_start TEXT,
                      date_end TEXT,
                      date_type TEXT,
                      confidence TEXT,
                      source_evidence_id TEXT,
                      basis TEXT,
                      created_at TEXT
                    );
                    CREATE TABLE occurrence_songs (
                      occurrence_id TEXT,
                      song_title_raw TEXT,
                      evidence_status TEXT,
                      probability REAL,
                      confidence TEXT,
                      source_count INTEGER,
                      evidence_count INTEGER,
                      inherited_from_year INTEGER
                    );
                    """
                )
                conn.execute(
                    "INSERT INTO venues VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "ven_test",
                        "京橋プラザ区民館",
                        "中央区",
                        "中",
                        "新富町駅徒歩2分",
                        "東京都中央区銀座一丁目25番3号",
                        "",
                        "京橋プラザ区民館の地域イベント。",
                        None,
                        None,
                        "active",
                    ),
                )
                conn.execute(
                    "INSERT INTO event_series VALUES (?, ?, ?, ?, ?)",
                    (
                        "ser_test",
                        "銀座一丁目東町会・新富町会 納涼盆踊り大会",
                        "[7]",
                        "銀座一丁目東町会・新富町会の納涼盆踊り大会。",
                        "active",
                    ),
                )
                conn.execute(
                    "INSERT INTO event_occurrences VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "occ_test",
                        "curated",
                        "ser_test",
                        2026,
                        "銀座一丁目東町会・新富町会 納涼盆踊り大会",
                        "ven_test",
                        "",
                        "",
                        "unknown",
                        "未確認",
                        "unknown",
                        "notion_events",
                        "",
                        "",
                        "2026年日程は未確認。",
                    ),
                )
                conn.execute(
                    "INSERT INTO occurrence_dates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "odate_test",
                        "occ_test",
                        "2025-07-19",
                        "",
                        "historical_reference",
                        "medium",
                        "",
                        "youtube evidence",
                        "2026-07-01T00:00:00+00:00",
                    ),
                )

            events, covered, fallback, skipped = build_public_events_from_master(db_path)

        self.assertEqual(covered, 1)
        self.assertEqual(fallback, 0)
        self.assertEqual(skipped, 0)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["date"], "2025-07-19")
        self.assertEqual(events[0]["date_confidence"]["level"], "unknown")
        self.assertEqual(events[0]["hints"], [[7, 19]])

    def test_write_public_js(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "events_public.js"

            write_public_js(path, [{"name": "自由が丘納涼盆踊り大会", "youtube_evidence": []}])

            text = path.read_text(encoding="utf-8")
            self.assertIn("const EVENTS = ", text)
            self.assertIn("自由が丘納涼盆踊り大会", text)
            self.assertTrue(text.endswith(";\n"))


if __name__ == "__main__":
    unittest.main()
