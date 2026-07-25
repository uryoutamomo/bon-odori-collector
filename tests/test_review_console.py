import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from review_console import data, server


class ReviewConsoleTests(unittest.TestCase):
    def test_reader_modes_do_not_mix_legacy_and_inbox_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            source_by_id = {source.id: source for source in data.SOURCES}
            for source_id in (
                *data.B1_LEGACY_SOURCE_IDS,
                "accepted_venue_song_missing_venue",
                "historical_reference_quality",
            ):
                source = source_by_id[source_id]
                (root / source.path).write_text(
                    json.dumps({source.rows_path: [{"fixture_id": source_id}]}),
                    encoding="utf-8",
                )

            inbox_rows = [
                {
                    "inbox_id": f"inbox_{source_id}",
                    "source_id": source_id,
                    "source_key": f"key_{source_id}",
                    "title": source_id,
                }
                for source_id in (
                    *data.B1_INBOX_SOURCE_IDS,
                    "accepted_venue_song_missing_venue",
                    "historical_reference_quality",
                )
            ]
            (root / "data/review_inbox.json").write_text(
                json.dumps({"items": inbox_rows}),
                encoding="utf-8",
            )
            decisions_path = root / "data/review_console/decisions.json"

            inventories = {
                mode: data.build_inventory(root, decisions_path, reader_mode=mode)
                for mode in data.REVIEW_CONSOLE_READER_MODES
            }

            for source_id in data.B1_LEGACY_SOURCE_IDS:
                self.assertEqual(
                    sum(item["source_id"] == source_id for item in inventories["legacy"]["items"]),
                    1,
                )
            self.assertTrue(
                data.review_inbox_row_enabled_for_reader_mode({"source_id": "missing_venue_extra"}, "inbox")
            )
            self.assertEqual(
                sum(item["source_id"] == "missing_occurrence_venue" for item in inventories["canary"]["items"]),
                0,
            )
            self.assertEqual(inventories["canary"]["review_inbox_source_group_counts"]["missing_venue"], 1)
            self.assertNotIn("official_source", inventories["canary"]["review_inbox_source_group_counts"])

            for mode in ("legacy", "canary"):
                source_ids = [item["source_id"] for item in inventories[mode]["items"]]
                self.assertIn("accepted_venue_song_missing_venue", source_ids, mode)
                self.assertIn("historical_reference_quality", source_ids, mode)
                self.assertNotIn(
                    "accepted_venue_song_missing_venue",
                    inventories[mode]["review_inbox_source_group_counts"],
                )

            inbox_source_ids = [item["source_id"] for item in inventories["inbox"]["items"]]
            self.assertNotIn("accepted_venue_song_missing_venue", inbox_source_ids)
            self.assertNotIn("historical_reference_quality", inbox_source_ids)
            self.assertEqual(
                inventories["inbox"]["review_inbox_source_group_counts"][
                    "accepted_venue_song_missing_venue"
                ],
                1,
            )
            self.assertEqual(
                inventories["inbox"]["review_inbox_source_group_counts"][
                    "historical_reference_quality"
                ],
                1,
            )

            self.assertTrue(
                all(
                    sum(item["source_id"] == source_id for item in inventories["inbox"]["items"]) == 0
                    for source_id in data.B1_LEGACY_SOURCE_IDS
                )
            )
            self.assertEqual(
                {key: inventories["inbox"]["review_inbox_source_group_counts"].get(key) for key in data.B1_INBOX_SOURCE_IDS},
                {key: 1 for key in data.B1_INBOX_SOURCE_IDS},
            )
            preview = data.build_reader_mode_preview(root, decisions_path)
            self.assertTrue(preview["ok"])

    def test_reader_mode_defaults_legacy_and_rejects_unknown_value(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(data.review_console_reader_mode(), "legacy")
        with self.assertRaisesRegex(ValueError, "REVIEW_CONSOLE_READER_MODE"):
            data.review_console_reader_mode("prefix-missing")

    def test_reader_preview_ignores_baseline_duplicates_but_rejects_new_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            source_by_id = {source.id: source for source in data.SOURCES}
            for source_id in data.B1_LEGACY_SOURCE_IDS:
                source = source_by_id[source_id]
                (root / source.path).write_text(
                    json.dumps({source.rows_path: [{"fixture_id": source_id}]}),
                    encoding="utf-8",
                )
            duplicate_source = source_by_id["youtube_active_video"]
            (root / duplicate_source.path).write_text(
                json.dumps(
                    {
                        duplicate_source.rows_path: [
                            {"video_id": "same"},
                            {"video_id": "same"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            inbox_rows = [
                {
                    "inbox_id": f"inbox_{source_id}",
                    "source_id": source_id,
                    "source_key": f"key_{source_id}",
                    "title": source_id,
                }
                for source_id in data.B1_INBOX_SOURCE_IDS
            ]
            inbox_path = root / "data/review_inbox.json"
            inbox_path.write_text(json.dumps({"items": inbox_rows}), encoding="utf-8")
            decisions_path = root / "data/review_console/decisions.json"

            preview = data.build_reader_mode_preview(root, decisions_path)
            self.assertTrue(preview["ok"])
            self.assertGreater(preview["modes"]["legacy"]["duplicate_item_ids"], 0)
            self.assertTrue(preview["checks"]["cutover_introduced_duplicate_item_ids_zero"])

            inbox_rows.append(dict(inbox_rows[0]))
            inbox_path.write_text(json.dumps({"items": inbox_rows}), encoding="utf-8")
            preview = data.build_reader_mode_preview(root, decisions_path)
            self.assertFalse(preview["ok"])
            self.assertGreater(preview["modes"]["inbox"]["cutover_introduced_duplicate_item_ids"], 0)

    def test_review_inbox_source_is_visible_in_console_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/review_inbox.json").write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "inbox_id": "inbox_1",
                                "kind": "current_year_confirmation",
                                "domain": "開催日",
                                "priority_label": "P0",
                                "priority_score": 100,
                                "title": "A盆踊り 2026日程確認",
                                "event_name": "A盆踊り",
                                "venue": "A公園",
                                "source_id": "official_monitor",
                                "source_key": "a-2026",
                                "recommended_action": "confirm_current_date",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            inventory = data.load_inventory(
                root=root,
                decisions_path=root / "data/review_console/decisions.json",
                reader_mode="inbox",
            )
            item = next(item for item in inventory["items"] if item["source_id"] == "review_inbox")

        self.assertEqual(item["title"], "A盆踊り 2026日程確認")
        self.assertEqual(item["domain"], "受信箱")
        self.assertEqual(item["action_group"], "current_date")

    def test_inventory_counts_console_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/registered_event_investigation_queue.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-06-26T00:00:00+00:00",
                        "tasks": [
                            {
                                "task_id": "one",
                                "event_name": "A盆踊り",
                                "recommended_action": "pre_cutover_quick_research",
                                "priority_label": "P0",
                                "observed_candidate": {
                                    "proposed_date_start": "2025-07-20",
                                    "proposed_date_values": ["2025-07-20"],
                                    "evidence_url_count": 1,
                                    "evidence_urls_sample": ["https://example.com/a"],
                                },
                            },
                            {
                                "task_id": "two",
                                "event_name": "B盆踊り",
                                "candidate_action": "already_decided",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            decisions_path = root / "data/review_console/decisions.json"
            data.save_decision(
                "registered_event_investigation:one",
                "accept",
                "OK",
                "promote_historical_reference",
                decisions_path=decisions_path,
            )

            inventory = data.load_inventory(root=root, decisions_path=decisions_path)
            source = next(item for item in inventory["sources"] if item["id"] == "registered_event_investigation")
            self.assertEqual(source["count"], 2)
            self.assertEqual(source["reviewed_count"], 1)
            self.assertEqual(source["closed_count"], 1)
            self.assertEqual(source["pending_count"], 0)
            self.assertIn("current_date", inventory["action_group_counts"])
            self.assertEqual(inventory["action_group_counts"]["current_date"]["reviewed"], 1)
            self.assertEqual(inventory["action_group_counts"]["current_date"]["closed"], 1)

    def test_historical_reference_quality_without_songs_returns_to_song_research_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/historical_reference_quality_review.json").write_text(
                json.dumps(
                    {
                        "review": [
                            {
                                "quality_review_id": "hist_1",
                                "event_name": "A盆踊り",
                                "venue": "A公園",
                                "historical_dates_label": "2025-07-20（日）",
                                "historical_weekdays_label": "日",
                                "song_count": 0,
                                "issue_codes": ["historical_songs_missing"],
                                "issue_summary": "曲候補なし",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            decisions_path = root / "data/review_console/decisions.json"

            inventory = data.load_inventory(root=root, decisions_path=decisions_path)
            item = next(item for item in inventory["items"] if item["source_id"] == "historical_reference_quality")

            self.assertEqual(item["action_group"], "song_research")
            self.assertEqual(item["action_group_label"], "曲・用語候補確認")
            self.assertIn("曲候補", item["action_group_reason"])
            self.assertEqual(inventory["action_group_counts"]["song_research"]["pending"], 1)

            filtered = server.filter_items(
                inventory,
                {"status": ["pending"], "action_group": ["song_research"]},
            )
            self.assertEqual(filtered["count"], 1)
            self.assertEqual(filtered["items"][0]["id"], item["id"])

    def test_daily_song_candidates_are_visible_as_song_research(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/weekly_song_candidates_review.json").write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "term": "盆ジョビ",
                                "canonical_song_name": "盆ジョビ",
                                "category": "曲候補",
                                "type": "曲名",
                                "triage_reason": "多義語・イベント名・ジャンル名の可能性がある",
                                "evidence_count": 1,
                                "evidence_url": "https://x.com/example/status/1",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            decisions_path = root / "data/review_console/decisions.json"

            inventory = data.load_inventory(root=root, decisions_path=decisions_path)
            item = next(item for item in inventory["items"] if item["source_id"] == "daily_song_candidate")

            self.assertEqual(item["action_group"], "song_research")
            self.assertEqual(item["action_group_label"], "曲・用語候補確認")
            self.assertEqual(inventory["action_group_counts"]["song_research"]["pending"], 1)
            self.assertEqual(item["title"], "盆ジョビ")

    def test_daily_term_candidates_are_visible_as_social_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/weekly_harvest_review_candidates.json").write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "term": "練習会",
                                "category": "用語候補",
                                "type": "準公式用語",
                                "interpretation": "盆踊りの曲や振りを練習する会",
                                "evidence_count": 3,
                                "evidence_url": "https://x.com/example/status/2",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            decisions_path = root / "data/review_console/decisions.json"

            inventory = data.load_inventory(root=root, decisions_path=decisions_path)
            item = next(item for item in inventory["items"] if item["source_id"] == "daily_term_candidate")

            self.assertEqual(item["action_group"], "social")
            self.assertEqual(item["action_group_label"], "X/RSS確認")
            self.assertEqual(item["title"], "練習会")

    def test_x_candidate_decision_writes_registration_decision_directly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            source_path = root / "data/x_candidate_post_review.json"
            source_path.write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "handle": "@bon_source",
                                "name": "盆踊り情報源",
                                "recommendation": "watch",
                                "promote_score": 7.5,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            decisions_path = root / "data/review_console/decisions.json"

            item = data.load_item(
                "x_candidate_post:@bon_source|盆踊り情報源",
                root=root,
                decisions_path=decisions_path,
            )
            option = next(option for option in item["apply_options"] if option["value"] == "promote")
            self.assertEqual(option["label"], "情報源にする")
            self.assertEqual(item["route_check_title"], "この判断で変わるもの")

            saved = data.save_decision(
                "x_candidate_post:@bon_source|盆踊り情報源",
                "accept",
                "投稿が有用",
                "promote",
                decisions_path=decisions_path,
                root=root,
            )

            self.assertEqual(saved["apply_value_label"], "情報源にする")
            payload = json.loads(source_path.read_text(encoding="utf-8"))
            row = payload["results"][0]
            self.assertEqual(row["registration_decision"], "登録")
            self.assertTrue(row["user_approved"])
            self.assertEqual(row["review_note"], "投稿が有用")

            data.undo_last_decision(decisions_path=decisions_path)
            restored = json.loads(source_path.read_text(encoding="utf-8"))["results"][0]
            self.assertNotIn("registration_decision", restored)
            self.assertNotIn("user_approved", restored)

    def test_collection_status_summarizes_youtube_and_x_lanes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data/public").mkdir(parents=True)
            (root / "data/youtube_daily_backfill_report.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-06-28T00:00:00+00:00",
                        "status": "harvested_until_quota_limited",
                        "selected_rows": 3,
                        "completed_batches": 2,
                        "remaining_rows_after": 1,
                        "candidates_after": 10,
                        "review_after": 2,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "data/youtube_year_backfill_candidates.json").write_text(
                json.dumps({"candidates": [{"id": 1}, {"id": 2}]}),
                encoding="utf-8",
            )
            (root / "data/voices.json").write_text(
                json.dumps([{"title": "voice"}]),
                encoding="utf-8",
            )
            (root / "data/x_news_digest_for_oto.json").write_text(
                json.dumps({"candidates": [{"candidate_id": "x1"}]}),
                encoding="utf-8",
            )
            (root / "data/weekly_song_candidates_review.json").write_text(
                json.dumps({"rows": [{"term": "盆ジョビ"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            decisions_path = root / "data/review_console/decisions.json"

            status = data.load_collection_status(root=root, decisions_path=decisions_path)

            self.assertEqual([lane["id"] for lane in status["lanes"]], ["youtube", "x"])
            youtube = status["lanes"][0]
            x_lane = status["lanes"][1]
            self.assertEqual(youtube["status"], "harvested_until_quota_limited")
            self.assertTrue(any(operation["id"] == "youtube_dry_run" for operation in youtube["operations"]))
            self.assertEqual(next(item for item in x_lane["summary"] if item["label"] == "digest")["value"], 1)
            self.assertTrue(any(operation["id"] == "x_digest" for operation in x_lane["operations"]))

    def test_publication_gap_review_is_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/publication_gap_review.json").write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "gap_id": "weekly_song_updated_unpublished:夜の踊り子",
                                "gap_type": "週次採用曲が公開辞書にない",
                                "term": "夜の踊り子",
                                "domain": "曲",
                                "recommended_action": "needs_research",
                                "priority_label": "P1",
                                "reason": "週次曲レビューで更新済みだが公開辞書にない。",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            decisions_path = root / "data/review_console/decisions.json"

            inventory = data.load_inventory(root=root, decisions_path=decisions_path)
            item = next(item for item in inventory["items"] if item["source_id"] == "publication_gap")

            self.assertEqual(item["action_group"], "other")
            self.assertEqual(item["domain"], "公開データ")
            self.assertEqual(item["title"], "夜の踊り子")
            self.assertEqual(item["subtitle"], "週次採用曲が公開辞書にない")

    def test_historical_promotion_candidate_shows_identity_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/historical_promotion_candidate_review.json").write_text(
                json.dumps(
                    {
                        "review": [
                            {
                                "candidate_id": "histprom_1",
                                "event_name": "東本願寺盆踊り",
                                "target_occurrence_id": "occ_1",
                                "target_year": 2025,
                                "target_date_start": "2025-08-20",
                                "target_date_status": "ended",
                                "venue": "東本願寺（浅草）",
                                "match_score": 1,
                                "promotion_confidence": "low",
                                "historical_years": [2024, 2025],
                                "insertable_historical_years": [2024],
                                "exact_dates": {"2024": ["2024-08-21"], "2025": ["2025-08-20"]},
                                "evidence_url_count": 456,
                                "song_title_count": 423,
                                "review_action": "manual_review",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            decisions_path = root / "data/review_console/decisions.json"

            inventory = data.load_inventory(root=root, decisions_path=decisions_path)
            item = next(item for item in inventory["items"] if item["source_id"] == "historical_promotion_candidate")

            self.assertEqual(item["action_group"], "identity")
            self.assertEqual(item["comparison"]["title"], "同一イベントとして扱うか")
            self.assertEqual(item["comparison"]["candidate"]["label"], "過去実績候補")
            self.assertIn("追加対象年: 2024", item["comparison"]["candidate"]["meta"])
            self.assertEqual(item["comparison"]["target"]["label"], "紐づけ先の既存開催回")
            self.assertIn("開催日: 2025-08-20", item["comparison"]["target"]["meta"])
            self.assertIn("会場: 東本願寺（浅草）", item["comparison"]["target"]["meta"])
            promote_option = next(
                option for option in item["apply_options"]
                if option["value"] == "promote_historical_reference"
            )
            self.assertEqual(promote_option["label"], "同一イベントとして採用")
            self.assertIn("既存開催回/イベント系列に紐づけ", promote_option["help"])

    def test_youtube_review_offers_parent_event_component_option(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/youtube_song_master.json").write_text(
                json.dumps(
                    {
                        "songs": [
                            {
                                "song_name": "ダンシングヒーロー",
                                "aliases": ["ダンシング・ヒーロー"],
                                "public_ready": True,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "data/youtube_active_video_review.json").write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "video_id": "gmo",
                                "video_url": "https://www.youtube.com/watch?v=gmo",
                                "title": "GMOシブヤエンタメ祭 × JAME盆踊り",
                                "channel_title": "Urban Walk",
                                "published_at": "2025-06-10T00:00:00Z",
                                "action": "bon_component_of_parent_event",
                                "parent_event_name": "GMOシブヤエンタメ祭",
                                "component_label": "JAME盆踊り",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "data/public").mkdir(exist_ok=True)
            (root / "data/public/events_public.json").write_text(
                json.dumps(
                    [
                        {
                            "id": "mitama_1",
                            "name": "みたままつり 納涼民踊のつどい",
                            "display_name": "みたままつり 納涼民踊のつどい",
                            "venue": "靖国神社",
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "data/public").mkdir(exist_ok=True)
            (root / "data/public/events_public.json").write_text(
                json.dumps(
                    [
                        {
                            "id": "mitama_1",
                            "name": "みたままつり 納涼民踊のつどい",
                            "display_name": "みたままつり 納涼民踊のつどい",
                            "venue": "靖国神社",
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            decisions_path = root / "data/review_console/decisions.json"

            item = data.load_item(
                "youtube_active_video:gmo|https://www.youtube.com/watch?v=gmo",
                root=root,
                decisions_path=decisions_path,
            )

            option = next(
                option for option in item["apply_options"]
                if option["value"] == "bon_component_of_parent_event"
            )
            self.assertEqual(option["label"], "親イベント内の盆踊り企画")
            self.assertEqual(option["decision"], "hold")
            self.assertEqual(item["status"], "pending")

    def test_youtube_parent_component_without_existing_event_disables_append(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/youtube_song_master.json").write_text(
                json.dumps(
                    {
                        "songs": [
                            {"song_name": "おジャ魔女カーニバル", "aliases": [], "public_ready": True},
                            {"song_name": "とっとこハム太郎", "aliases": [], "public_ready": True},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "data/youtube_active_video_review.json").write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "video_id": "niconico",
                                "video_url": "https://www.youtube.com/watch?v=niconico",
                                "title": "【4K】ニコニコ超会議 × 盆踊り 「おジャ魔女カーニバル / とっとこハム太郎」",
                                "channel_title": "Urban Walk",
                                "action": "bon_component_of_parent_event",
                                "auto_review_note": "parent_event_song_clip_fragment",
                                "parent_event_component": {
                                    "parent_event_name": "ニコニコ超会議",
                                    "component_label": "超ニコニコ盆踊り",
                                    "component_reason": "親イベント本体ではなく、年別の盆踊り要素として保持",
                                },
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            decisions_path = root / "data/review_console/decisions.json"

            item = data.load_item(
                "youtube_active_video:niconico|https://www.youtube.com/watch?v=niconico",
                root=root,
                decisions_path=decisions_path,
            )

            append = next(option for option in item["apply_options"] if option["value"] == "append_existing_event")
            component = next(option for option in item["apply_options"] if option["value"] == "bon_component_of_parent_event")
            self.assertTrue(append["disabled"])
            self.assertIn("親イベント内の盆踊り企画", append["disabled_reason"])
            self.assertFalse(component["disabled"])
            self.assertEqual(item["status"], "closed")
            self.assertEqual(item["title_event_name_candidate"], "")
            self.assertIn("1ではなく3", item["route_note"])
            checks = {check["label"]: check for check in item["route_checks"]}
            self.assertEqual(checks["親イベント"]["value"], "ニコニコ超会議")
            self.assertEqual(checks["盆踊り企画"]["value"], "超ニコニコ盆踊り")

    def test_youtube_target_event_prefers_aggregate_setlist_occurrence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/youtube_active_video_review.json").write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "video_id": "akiba",
                                "video_url": "https://www.youtube.com/watch?v=akiba",
                                "title": "【浅草夜祭・アキバ盆踊り】１ DJ秋葉原ササキチ",
                                "channel_title": "和太鼓お祭りチャンネル",
                                "action": "bon_component_of_parent_event",
                                "parent_event_name": "浅草夜祭",
                                "component_label": "アキバ盆踊り / 盆踊り企画",
                                "setlist_occurrences": [
                                    {
                                        "occurrence_key": "c10eef57e023cc8a",
                                        "event_name": "【浅草夜祭・アキバ盆踊り】1 DJ秋葉原ササキチ",
                                        "venue": "【浅草夜祭・アキバ盆踊り】1 DJ秋葉原ササキチ",
                                        "event_date": "2025-11-22",
                                        "song_count": 7,
                                        "confidence": "high",
                                    },
                                    {
                                        "occurrence_key": "ab5da725f0c96975",
                                        "event_name": "浅草夜祭・アキバ盆踊り",
                                        "venue": "浅草夜祭・アキバ盆踊り",
                                        "event_date": "2025-11-22",
                                        "song_count": 16,
                                        "confidence": "high",
                                        "matched_public_event": {
                                            "id": "public-akiba",
                                            "name": "浅草夜祭・アキバ盆踊り",
                                            "venue": "浅草夜祭",
                                            "date": "2025-11-22",
                                            "score": "high",
                                            "reasons": ["event_name_in_youtube"],
                                        },
                                    },
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            decisions_path = root / "data/review_console/decisions.json"

            item = data.load_item(
                "youtube_active_video:akiba|https://www.youtube.com/watch?v=akiba",
                root=root,
                decisions_path=decisions_path,
            )

            self.assertEqual(item["target_event"]["name"], "浅草夜祭・アキバ盆踊り")
            self.assertEqual(item["target_event"]["date"], "2025-11-22")
            append = next(option for option in item["apply_options"] if option["value"] == "append_existing_event")
            component = next(option for option in item["apply_options"] if option["value"] == "bon_component_of_parent_event")
            self.assertFalse(append["disabled"])
            self.assertTrue(component["disabled"])
            self.assertIn("1を選んでください", component["disabled_reason"])

            saved = data.save_decision(
                item["id"],
                "accept",
                "",
                "append_existing_event",
                target_event_name="浅草夜祭・アキバ盆踊り",
                target_song_names="アイドル",
                decisions_path=decisions_path,
                root=root,
            )
            self.assertEqual(saved["manual_target_event_name"], "浅草夜祭・アキバ盆踊り")
            self.assertEqual(saved["manual_target_event_match"]["source"], "setlist_matched_public_event")
            self.assertEqual(saved["manual_target_event_match"]["id"], "public-akiba")
            self.assertEqual(saved["manual_song_names"], ["アイドル"])

    def test_youtube_raw_setlist_occurrence_is_not_existing_event_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/youtube_active_video_review.json").write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "video_id": "yuroad",
                                "video_url": "https://www.youtube.com/watch?v=yuroad",
                                "title": "亀有ゆうろーど盆踊り2025",
                                "channel_title": "祭しっぽ ch",
                                "action": "review_video_evidence",
                                "setlist_occurrences": [
                                    {
                                        "occurrence_key": "occ-yuroad",
                                        "event_name": "亀有ゆうろーど盆踊り2025",
                                        "venue": "亀有ゆうろーど",
                                        "event_date": "2025-08-31",
                                        "song_count": 12,
                                        "confidence": "high",
                                    },
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            decisions_path = root / "data/review_console/decisions.json"

            item = data.load_item(
                "youtube_active_video:yuroad|https://www.youtube.com/watch?v=yuroad",
                root=root,
                decisions_path=decisions_path,
            )

            self.assertIsNone(item["target_event"])
            with self.assertRaisesRegex(ValueError, "追加先イベント名を入力してください"):
                data.save_decision(
                    item["id"],
                    "accept",
                    "",
                    "append_existing_event",
                    decisions_path=decisions_path,
                    root=root,
                )

    def test_youtube_append_existing_event_label_is_video_evidence_not_event_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/youtube_active_video_review.json").write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "video_id": "song_clip",
                                "video_url": "https://www.youtube.com/watch?v=songclip",
                                "title": "国立旭通りジューンフェスタ盆踊り 曲別動画",
                                "channel_title": "Tokyo Lonely Walker",
                                "published_at": "2025-06-09T00:00:00Z",
                                "action": "append_existing_event",
                                "matched_public_event": {
                                    "name": "国立旭通りジューンフェスタ盆踊り",
                                    "date": "2025-06-08",
                                },
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            decisions_path = root / "data/review_console/decisions.json"

            item = data.load_item(
                "youtube_active_video:song_clip|https://www.youtube.com/watch?v=songclip",
                root=root,
                decisions_path=decisions_path,
            )

            option = next(option for option in item["apply_options"] if option["value"] == "append_existing_event")
            self.assertEqual(option["label"], "既存イベントへ動画・曲を追加")
            self.assertIn("新規作成せず", option["help"])
            self.assertIn("曲名", option["help"])
            self.assertEqual(item["target_event"]["name"], "国立旭通りジューンフェスタ盆踊り")
            self.assertEqual(item["target_event"]["date"], "2025-06-08")
            self.assertEqual(item["route_check_title"], "追加先イベント確認")
            checks = {check["label"]: check for check in item["route_checks"]}
            self.assertEqual(checks["追加先イベント"]["value"], "国立旭通りジューンフェスタ盆踊り")
            self.assertEqual(checks["追加先日付"]["value"], "2025-06-08")

    def test_youtube_append_existing_event_accepts_manual_target_and_song(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/youtube_song_master.json").write_text(
                json.dumps(
                    {
                        "songs": [
                            {
                                "song_name": "ダンシングヒーロー",
                                "aliases": ["ダンシング・ヒーロー"],
                                "public_ready": True,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "data/youtube_active_video_review.json").write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "video_id": "unknown",
                                "video_url": "https://www.youtube.com/watch?v=unknown",
                                "title": "【4K】靖国神社 みたままつり 盆踊り|「ダンシングヒーロー」 荻野目洋子",
                                "channel_title": "祭のきせき",
                                "published_at": "2025-10-27T00:00:00Z",
                                "action": "review_video_evidence",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "data/public").mkdir(exist_ok=True)
            (root / "data/public/events_public.json").write_text(
                json.dumps(
                    [
                        {
                            "id": "mitama_1",
                            "name": "みたままつり 納涼民踊のつどい",
                            "display_name": "みたままつり 納涼民踊のつどい",
                            "venue": "靖国神社",
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            decisions_path = root / "data/review_console/decisions.json"

            item = data.load_item(
                "youtube_active_video:unknown|https://www.youtube.com/watch?v=unknown",
                root=root,
                decisions_path=decisions_path,
            )

            option = next(option for option in item["apply_options"] if option["value"] == "append_existing_event")
            self.assertFalse(option["disabled"])
            self.assertIsNone(item["target_event"])
            self.assertEqual(item["title_event_name_candidate"], "靖国神社 みたままつり 盆踊り")
            self.assertEqual(item["song_candidates"], ["ダンシングヒーロー"])

            with self.assertRaisesRegex(ValueError, "追加先イベント名"):
                data.save_decision(
                    item["id"],
                    "accept",
                    "",
                    "append_existing_event",
                    decisions_path=decisions_path,
                    root=root,
                )

            saved = data.save_decision(
                item["id"],
                "accept",
                "曲別動画",
                "append_existing_event",
                target_event_name="みたままつり 納涼民踊のつどい",
                target_song_names="ダンシングヒーロー",
                decisions_path=decisions_path,
                root=root,
            )
            self.assertEqual(saved["manual_target_event_name"], "みたままつり 納涼民踊のつどい")
            self.assertEqual(saved["manual_song_names"], ["ダンシングヒーロー"])

            reviewed = data.load_item(item["id"], root=root, decisions_path=decisions_path)
            self.assertEqual(reviewed["target_event"]["name"], "みたままつり 納涼民踊のつどい")

    def test_youtube_manual_target_event_must_exist_and_canonicalizes_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            data_dir.mkdir()
            db_path = data_dir / "bon_odori_master.sqlite"
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE event_series (
                  series_id TEXT PRIMARY KEY,
                  canonical_name TEXT,
                  normalized_name TEXT,
                  usual_venue_id TEXT,
                  status TEXT
                );
                CREATE TABLE venues (
                  venue_id TEXT PRIMARY KEY,
                  name TEXT
                );
                CREATE TABLE event_occurrences (
                  occurrence_id TEXT PRIMARY KEY,
                  series_id TEXT,
                  event_year INTEGER,
                  display_name TEXT,
                  venue_id TEXT,
                  date_start TEXT,
                  date_end TEXT,
                  lifecycle_status TEXT
                );
                """
            )
            conn.execute("INSERT INTO venues VALUES (?, ?)", ("venue_1", "雷門前"))
            conn.execute(
                "INSERT INTO event_series VALUES (?, ?, ?, ?, ?)",
                ("series_1", "雷門盆踊り（浅草）", "雷門盆踊り浅草", "venue_1", "active"),
            )
            conn.execute(
                "INSERT INTO event_occurrences VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("occ_1", "series_1", 2026, "雷門盆踊り（浅草）", "venue_1", "", "", "draft"),
            )
            conn.commit()
            conn.close()
            (data_dir / "youtube_active_video_review.json").write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "video_id": "kaminarimon",
                                "video_url": "https://www.youtube.com/watch?v=kaminarimon",
                                "title": "雷門盆踊り 夢灯篭 2025",
                                "channel_title": "Urban Walk",
                                "action": "review_video_evidence",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            decisions_path = data_dir / "review_console/decisions.json"
            item_id = "youtube_active_video:kaminarimon|https://www.youtube.com/watch?v=kaminarimon"

            saved = data.save_decision(
                item_id,
                "accept",
                "",
                "append_existing_event",
                target_event_name="雷門盆踊り",
                target_song_names="",
                decisions_path=decisions_path,
                root=root,
            )

            self.assertEqual(saved["manual_target_event_name"], "雷門盆踊り（浅草）")
            self.assertEqual(saved["manual_target_event_match"]["id"], "occ_1")

            with self.assertRaisesRegex(ValueError, "既存イベントが見つかりません"):
                data.save_decision(
                    item_id,
                    "accept",
                    "",
                    "append_existing_event",
                    target_event_name="存在しない盆踊り",
                    decisions_path=decisions_path,
                    root=root,
                )

    def test_rare_signal_backcheck_queue_is_source_url_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/rare_signal_backcheck_queue.json").write_text(
                json.dumps(
                    {
                        "queue": [
                            {
                                "candidate_id": "xoto_1",
                                "backcheck_status": "pending",
                                "source_policy": "x_discovery_only_non_x_confirmation_required",
                                "promotion_target": "event",
                                "novelty_assessment": "new",
                                "primary_name": "佐竹ゲバゲバ盆踊り",
                                "possible_event_name": "佐竹ゲバゲバ盆踊り",
                                "possible_venue": "佐竹商店街",
                                "possible_area": "台東区",
                                "possible_date_text": "2026年7月",
                                "oto_interpreted_summary": "佐竹商店街で佐竹ゲバゲバ盆踊りの開催情報がある。",
                                "search_queries": ["佐竹ゲバゲバ盆踊り 台東区"],
                                "internal_discovery_urls": ["https://x.com/example/status/1"],
                                "next_action": "find_non_x_confirmation",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            decisions_path = root / "data/review_console/decisions.json"

            inventory = data.load_inventory(root=root, decisions_path=decisions_path)
            item = next(item for item in inventory["items"] if item["source_id"] == "rare_signal_backcheck")

            self.assertEqual(item["status"], "pending")
            self.assertEqual(item["domain"], "根拠URL")
            self.assertEqual(item["action_group"], "source_url")
            self.assertEqual(item["research_advice_status"], "非X裏どり待ち")
            self.assertIn("非X", item["route_checks"][0]["label"])
            option = next(option for option in item["apply_options"] if option["value"] == "confirm_non_x_source")
            self.assertEqual(option["decision"], "accept")
            self.assertIn("X以外", option["help"])

    def test_registered_event_investigation_requires_explicit_route_and_blocks_date_confirmation_without_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/registered_event_investigation_queue.json").write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "task_id": "one",
                                "event_name": "A盆踊り",
                                "event_year": 2026,
                                "missing_date": True,
                                "recommended_action": "pre_cutover_quick_research",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            decisions_path = root / "data/review_console/decisions.json"

            with self.assertRaisesRegex(ValueError, "反映ルート"):
                data.save_decision(
                    "registered_event_investigation:one",
                    "accept",
                    decisions_path=decisions_path,
                    root=root,
                )

            with self.assertRaisesRegex(ValueError, "日程確認済みにはできません"):
                data.save_decision(
                    "registered_event_investigation:one",
                    "accept",
                    apply_value="confirm_current_date",
                    decisions_path=decisions_path,
                    root=root,
                )

            with self.assertRaisesRegex(ValueError, "過去実績の日付・曜日"):
                data.save_decision(
                    "registered_event_investigation:one",
                    "accept",
                    apply_value="promote_historical_reference",
                    decisions_path=decisions_path,
                    root=root,
                )

            item = data.load_item(
                "registered_event_investigation:one",
                root=root,
                decisions_path=decisions_path,
            )
            historical_option = next(option for option in item["apply_options"] if option["value"] == "promote_historical_reference")
            confirm_option = next(option for option in item["apply_options"] if option["value"] == "confirm_current_date")
            self.assertTrue(historical_option["disabled"])
            self.assertIn("過去実績の日付", historical_option["disabled_reason"])
            self.assertTrue(confirm_option["disabled"])
            self.assertIn("2026年日程", confirm_option["disabled_reason"])
            self.assertIn("過去実績の日付・曜日", item["route_note"])
            self.assertEqual(item["route_checks"][0]["kind"], "block")

            saved = data.save_decision(
                "registered_event_investigation:one",
                "hold",
                apply_value="hold",
                decisions_path=decisions_path,
                root=root,
            )
            self.assertEqual(saved["decision"], "hold")
            self.assertEqual(saved["decision_route"], "hold_candidate")

            research_option = next(option for option in item["apply_options"] if option["value"] == "needs_research")
            self.assertIn("日付補完apply待ち", research_option["help"])

    def test_registered_event_drive_source_gets_ocr_research_advice_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/registered_event_investigation_queue.json").write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "task_id": "drive",
                                "event_name": "A町会盆踊り",
                                "event_year": 2026,
                                "missing_date": True,
                                "source_url": "https://drive.google.com/file/d/example/view",
                                "recommended_action": "pre_cutover_quick_research",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            decisions_path = root / "data/review_console/decisions.json"

            item = data.load_item(
                "registered_event_investigation:drive",
                root=root,
                decisions_path=decisions_path,
            )
            self.assertEqual(item["research_advice_status"], "OCR待ち")
            self.assertIn("本文OCR", item["research_advice"]["message"])

            data.save_decision(
                "registered_event_investigation:drive",
                "needs_research",
                "画像本文確認へ",
                "needs_research",
                decisions_path=decisions_path,
                root=root,
            )
            exported = data.build_export_payload(root=root, decisions_path=decisions_path)
            self.assertEqual(exported["rows"][0]["research_advice_status"], "OCR待ち")
            self.assertIn("本文OCR", exported["rows"][0]["research_advice"]["message"])

    def test_concurrent_decision_saves_do_not_drop_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data/review_console").mkdir(parents=True)
            decisions_path = root / "data/review_console/decisions.json"

            item_ids = [f"missing_source_url:occ_{index}|根拠待ち{index}" for index in range(20)]

            def save(item_id: str) -> str:
                saved = data.save_decision(
                    item_id,
                    "needs_research",
                    "公式URLが必要",
                    "source_research_required",
                    decisions_path=decisions_path,
                    root=root,
                )
                return saved["item_id"]

            with ThreadPoolExecutor(max_workers=8) as executor:
                saved_ids = list(executor.map(save, item_ids))

            self.assertEqual(sorted(saved_ids), sorted(item_ids))
            decisions = data.load_decisions(decisions_path)["decisions"]
            self.assertEqual(set(decisions), set(item_ids))
            history = data.load_decision_history(decisions_path.with_name("decision_history.json"))["history"]
            self.assertEqual(len(history), len(item_ids))

    def test_registered_event_historical_checks_show_date_weekday_and_song_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/registered_event_investigation_queue.json").write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "task_id": "one",
                                "event_name": "A盆踊り",
                                "event_year": 2026,
                                "missing_date": True,
                                "recommended_action": "pre_cutover_quick_research",
                                "observed_candidate_confidence": "high",
                                "observed_candidate": {
                                    "promotion_confidence": "high",
                                    "proposed_date_start": "2025-07-20",
                                    "proposed_date_values": ["2025-07-20"],
                                    "source_occurrence_count": 2,
                                    "song_title_count": 2,
                                    "song_titles_sample": ["東京音頭", "炭坑節"],
                                    "evidence_url_count": 1,
                                    "evidence_urls_sample": ["https://example.com/a"],
                                },
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            decisions_path = root / "data/review_console/decisions.json"

            item = data.load_item(
                "registered_event_investigation:one",
                root=root,
                decisions_path=decisions_path,
            )
            historical_option = next(option for option in item["apply_options"] if option["value"] == "promote_historical_reference")
            self.assertFalse(historical_option["disabled"])
            self.assertIn("2026年日程未確認", item["route_note"])
            checks = {check["label"]: check for check in item["route_checks"]}
            self.assertEqual(checks["過去実績日"]["value"], "2025-07-20（日）")
            self.assertEqual(checks["曜日"]["value"], "日")
            self.assertEqual(checks["証拠URL"]["value"], "1件")
            self.assertIn("2曲", checks["曲候補"]["value"])
            self.assertIn("この採用操作だけでは曲を確定登録しません", checks["曲候補"]["message"])
            self.assertEqual(checks["曲収集ルート"]["value"], "別工程")

            saved = data.save_decision(
                "registered_event_investigation:one",
                "accept",
                apply_value="promote_historical_reference",
                decisions_path=decisions_path,
                root=root,
            )
            self.assertEqual(saved["apply_value_label"], "過去実績として採用")
            self.assertEqual(saved["decision_route"], "historical_reference_only")

    def test_registered_event_with_historical_date_and_missing_venue_asks_for_venue_not_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/registered_event_investigation_queue.json").write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "task_id": "ginza",
                                "event_name": "銀座一丁目東町会・新富町会 納涼盆踊り大会",
                                "event_year": 2026,
                                "missing_date": True,
                                "missing_venue": True,
                                "known_venue_names": [],
                                "recommended_action": "pre_cutover_quick_research",
                                "observed_candidate_confidence": "medium",
                                "observed_candidate": {
                                    "promotion_confidence": "medium",
                                    "proposed_date_start": "2025-07-19",
                                    "proposed_date_values": ["2025-07-19"],
                                    "proposed_venue": "京橋プラザ",
                                    "source_occurrence_count": 1,
                                    "song_title_count": 7,
                                    "evidence_url_count": 1,
                                    "evidence_urls_sample": ["https://example.com/video"],
                                },
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            decisions_path = root / "data/review_console/decisions.json"

            item = data.load_item(
                "registered_event_investigation:ginza",
                root=root,
                decisions_path=decisions_path,
            )

            self.assertEqual(item["action_group"], "venue")
            self.assertEqual(item["action_group_label"], "会場確認待ち")
            self.assertIn("確認してほしいのは会場", item["action_group_reason"])
            self.assertEqual(item["route_check_title"], "確認してほしいこと")
            self.assertEqual(item["route_checks"][0]["label"], "確認対象")
            self.assertEqual(item["route_checks"][0]["value"], "会場: 京橋プラザ")
            self.assertIn("過去実績日", item["route_checks"][1]["label"])

            historical_option = next(option for option in item["apply_options"] if option["value"] == "promote_historical_reference")
            research_option = next(option for option in item["apply_options"] if option["value"] == "needs_research")
            hold_option = next(option for option in item["apply_options"] if option["value"] == "hold")
            self.assertFalse(historical_option["disabled"])
            self.assertEqual(historical_option["label"], "過去実績＋会場を採用")
            self.assertEqual(research_option["label"], "会場を要調査")
            self.assertIn("会場「京橋プラザ」", historical_option["help"])
            self.assertIn("調査リスト", research_option["help"])
            self.assertIn("次回以降", hold_option["help"])

    def test_confident_registered_event_venue_is_auto_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/registered_event_investigation_queue.json").write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "task_id": "ginza",
                                "event_name": "銀座一丁目東町会・新富町会 納涼盆踊り大会",
                                "event_year": 2026,
                                "missing_date": True,
                                "missing_venue": True,
                                "recommended_action": "pre_cutover_quick_research",
                                "observed_candidate_confidence": "medium",
                                "observed_candidate": {
                                    "promotion_confidence": "medium",
                                    "proposed_event_name": "京橋公園納涼盆踊り大会 (銀座一丁目東町会 新富町会)中央区京橋プラザ",
                                    "proposed_date_start": "2025-07-19",
                                    "proposed_date_values": ["2025-07-19"],
                                    "proposed_venue": "京橋プラザ",
                                    "organizers": ["銀座一丁目東町会 新富町会"],
                                    "matched_tokens": ["銀座一丁目東町会", "新富町会"],
                                    "source_occurrence_count": 3,
                                    "source_occurrence_ids": ["a", "b", "c"],
                                    "evidence_url_count": 7,
                                    "evidence_urls_sample": [
                                        "https://example.com/1",
                                        "https://example.com/2",
                                        "https://example.com/3",
                                    ],
                                },
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            decisions_path = root / "data/review_console/decisions.json"

            inventory = data.load_inventory(root=root, decisions_path=decisions_path)
            source = next(item for item in inventory["sources"] if item["id"] == "registered_event_investigation")
            item = next(item for item in inventory["items"] if item["source_id"] == "registered_event_investigation")

            self.assertEqual(source["pending_count"], 0)
            self.assertEqual(source["closed_count"], 1)
            self.assertEqual(item["status"], "closed")
            self.assertEqual(item["auto_resolution"]["canonical_venue"], "京橋プラザ区民館")
            self.assertIn("人間レビューには出しません", item["route_note"])

    def test_registered_event_with_existing_historical_reference_is_stale_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            occurrence_id = "occ_stale"
            (root / "data/registered_event_investigation_queue.json").write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "task_id": "stale",
                                "occurrence_id": occurrence_id,
                                "event_name": "ゐの市盆踊り～不忍夢～",
                                "event_year": 2026,
                                "missing_date": True,
                                "missing_venue": False,
                                "known_venue_names": ["上野恩賜公園"],
                                "source_url": "https://www.uenopark.info/2025/inoichi-bonodori-2025/",
                                "recommended_action": "pre_cutover_quick_research",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            conn = sqlite3.connect(root / "data/bon_odori_master.sqlite")
            conn.execute(
                """
                CREATE TABLE occurrence_dates (
                  occurrence_date_id TEXT PRIMARY KEY,
                  occurrence_id TEXT NOT NULL,
                  date_start TEXT NOT NULL,
                  date_end TEXT,
                  date_type TEXT NOT NULL,
                  confidence TEXT NOT NULL,
                  source_evidence_id TEXT,
                  basis TEXT,
                  created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO occurrence_dates(
                  occurrence_date_id, occurrence_id, date_start, date_end,
                  date_type, confidence, source_evidence_id, basis, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "odate_stale",
                    occurrence_id,
                    "2025-08-09",
                    "2025-08-11",
                    "historical_reference",
                    "medium",
                    None,
                    json.dumps({"historical_venue_name": "上野恩賜公園"}, ensure_ascii=False),
                    "2026-06-27T00:00:00+00:00",
                ),
            )
            conn.commit()
            conn.close()
            decisions_path = root / "data/review_console/decisions.json"

            inventory = data.load_inventory(root=root, decisions_path=decisions_path)
            source = next(item for item in inventory["sources"] if item["id"] == "registered_event_investigation")
            item = next(item for item in inventory["items"] if item["source_id"] == "registered_event_investigation")

            self.assertEqual(source["pending_count"], 0)
            self.assertEqual(source["closed_count"], 1)
            self.assertEqual(item["status"], "closed")
            self.assertEqual(item["auto_resolution"]["decision"], "auto_stale_queue_historical_reference_already_recorded")
            self.assertEqual(item["route_check_title"], "自動解決したこと")
            self.assertIn("2025-08-09（土）", item["auto_resolution"]["historical_date"])

    def test_export_and_stage_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/missing_source_url_review.json").write_text(
                json.dumps(
                    {
                        "review": [
                            {
                                "occurrence_id": "occ_1",
                                "event_name": "根拠待ち",
                                "review_action": "ready_source_url_candidate",
                                "candidate_source_url": "https://example.com/source",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            decisions_path = root / "data/review_console/decisions.json"
            data.save_decision(
                "missing_source_url:occ_1|根拠待ち",
                "needs_research",
                "公式URLが必要",
                "source_research_required",
                decisions_path=decisions_path,
            )

            exported = data.export_decisions(
                root=root,
                decisions_path=decisions_path,
                out_path=root / "data/review_console/exported_decisions.json",
            )
            self.assertEqual(exported["decision_count"], 1)
            self.assertEqual(exported["rows"][0]["apply_value"], "source_research_required")

            staged = data.stage_apply(root=root, decisions_path=decisions_path, write=False)
            self.assertEqual(staged["decision_count"], 1)
            self.assertEqual(staged["staged_files"][0]["source_id"], "missing_source_url")

    def test_undo_restores_previous_decision_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            decisions_path = root / "data/review_console/decisions.json"
            item_id = "missing_source_url:occ_1|根拠待ち"

            data.save_decision(
                item_id,
                "hold",
                "あとで見る",
                "hold",
                decisions_path=decisions_path,
            )
            data.save_decision(
                item_id,
                "needs_research",
                "公式確認",
                "source_research_required",
                decisions_path=decisions_path,
            )

            status = data.undo_status(decisions_path=decisions_path)
            self.assertEqual(status["undo_count"], 2)

            undone = data.undo_last_decision(decisions_path=decisions_path)
            self.assertEqual(undone["undo_count"], 1)
            decisions = data.load_decisions(decisions_path)["decisions"]
            self.assertEqual(decisions[item_id]["decision"], "hold")
            self.assertEqual(decisions[item_id]["note"], "あとで見る")

            data.undo_last_decision(decisions_path=decisions_path)
            decisions = data.load_decisions(decisions_path)["decisions"]
            self.assertNotIn(item_id, decisions)
            self.assertEqual(data.undo_status(decisions_path=decisions_path)["undo_count"], 0)

            with self.assertRaisesRegex(ValueError, "取り消せる操作"):
                data.undo_last_decision(decisions_path=decisions_path)

    def test_stage_status_reports_pending_and_outdated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/missing_source_url_review.json").write_text(
                json.dumps(
                    {
                        "review": [
                            {
                                "occurrence_id": "occ_1",
                                "event_name": "根拠待ち",
                                "review_action": "ready_source_url_candidate",
                            },
                            {
                                "occurrence_id": "occ_2",
                                "event_name": "追加候補",
                                "review_action": "ready_source_url_candidate",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            decisions_path = root / "data/review_console/decisions.json"
            data.save_decision(
                "missing_source_url:occ_1|根拠待ち",
                "accept",
                decisions_path=decisions_path,
            )
            data.stage_apply(root=root, decisions_path=decisions_path, write=True)

            status = data.stage_status(root=root, decisions_path=decisions_path)
            self.assertTrue(status["has_staged_decisions"])
            self.assertFalse(status["is_outdated"])
            self.assertTrue(status["needs_attention"])
            self.assertEqual(status["decision_count"], 1)

            ack = data.acknowledge_stage(root=root, decisions_path=decisions_path)
            self.assertEqual(ack["decision_count"], 1)
            status = data.stage_status(root=root, decisions_path=decisions_path)
            self.assertTrue(status["is_acknowledged"])
            self.assertFalse(status["needs_attention"])

            data.save_decision(
                "missing_source_url:occ_2|追加候補",
                "hold",
                decisions_path=decisions_path,
            )

            status = data.stage_status(root=root, decisions_path=decisions_path)
            self.assertTrue(status["has_staged_decisions"])
            self.assertTrue(status["is_outdated"])
            self.assertTrue(status["needs_attention"])

            data.stage_apply(root=root, decisions_path=decisions_path, write=True)
            status = data.stage_status(root=root, decisions_path=decisions_path)
            self.assertFalse(status["is_acknowledged"])
            self.assertTrue(status["needs_attention"])

    def test_stage_apply_write_removes_stale_source_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/missing_source_url_review.json").write_text(
                json.dumps(
                    {
                        "review": [
                            {
                                "occurrence_id": "occ_1",
                                "event_name": "根拠待ち",
                                "review_action": "ready_source_url_candidate",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            decisions_path = root / "data/review_console/decisions.json"
            data.save_decision(
                "missing_source_url:occ_1|根拠待ち",
                "reject",
                decisions_path=decisions_path,
            )
            data.stage_apply(root=root, decisions_path=decisions_path, write=True)
            staged_file = root / "data/review_console/staged/missing_source_url_decisions.json"
            self.assertTrue(staged_file.exists())

            data.save_decision(
                "missing_source_url:occ_1|根拠待ち",
                "clear",
                decisions_path=decisions_path,
            )
            data.stage_apply(root=root, decisions_path=decisions_path, write=True)

            self.assertFalse(staged_file.exists())
            status = data.stage_status(root=root, decisions_path=decisions_path)
            self.assertFalse(status["has_staged_decisions"])

    def test_admin_summary_combines_review_stage_and_ops_attention(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            data_dir.mkdir()
            (data_dir / "missing_source_url_review.json").write_text(
                json.dumps(
                    {
                        "review": [
                            {
                                "occurrence_id": "occ_1",
                                "event_name": "根拠待ち",
                                "review_action": "ready_source_url_candidate",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (data_dir / "youtube_year_backfill_review_queue.json").write_text(
                json.dumps(
                    {
                        "summary": {
                            "group_count": 1,
                            "undecided_group_count": 4,
                            "video_count": 2,
                            "undecided_video_count": 2,
                        },
                        "groups": [
                            {
                                "event_name": "YouTube候補",
                                "venue": "会場",
                                "target_year": 2025,
                                "review_action": "manual_review",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (data_dir / "missing_source_url_review_post_apply.json").write_text(
                json.dumps({"summary": {"missing_source_url_occurrence_count": 2}}, ensure_ascii=False),
                encoding="utf-8",
            )
            (data_dir / "missing_occurrence_venue_review_post_venue_fixes.json").write_text(
                json.dumps({"summary": {"missing_venue_occurrence_count": 1}}, ensure_ascii=False),
                encoding="utf-8",
            )
            (data_dir / "reviewed_shinagawa_date_fills_apply_report.json").write_text(
                json.dumps({"summary": {"missing_date_start_count": 3}}, ensure_ascii=False),
                encoding="utf-8",
            )
            (data_dir / "youtube_daily_backfill_report.json").write_text(
                json.dumps({"status": "quota_limited"}, ensure_ascii=False),
                encoding="utf-8",
            )

            decisions_path = data_dir / "review_console/decisions.json"
            data.save_decision(
                "missing_source_url:occ_1|根拠待ち",
                "accept",
                decisions_path=decisions_path,
            )
            data.stage_apply(root=root, decisions_path=decisions_path, write=True)

            summary = data.load_admin_summary(root=root, decisions_path=decisions_path)

        self.assertEqual(summary["schema_version"], 1)
        self.assertEqual(summary["review"]["reviewed"], 1)
        self.assertGreaterEqual(summary["review"]["pending"], 1)
        self.assertTrue(summary["stage"]["needs_attention"])
        self.assertEqual(summary["ops"]["missing_source_url_occurrences"], 2)
        self.assertEqual(summary["ops"]["missing_venue_occurrences"], 1)
        self.assertEqual(summary["ops"]["missing_date_start_count"], 3)
        self.assertEqual(summary["ops"]["youtube_review_queue_undecided_groups"], 4)

        titles = {item["title"] for item in summary["attention"]}
        self.assertIn("反映準備あり", titles)
        self.assertIn("根拠URL不足があります", titles)
        self.assertIn("会場不足レビューがあります", titles)
        self.assertIn("YouTube年次バックフィルに未判断があります", titles)
        self.assertIn("YouTube収集はquota条件で停止しました", titles)
        self.assertIn(
            {"view": "review", "source": "missing_source_url", "status": "pending"},
            [item["target"] for item in summary["attention"]],
        )

    def test_ops_metrics_reports_history_and_deltas(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            data_dir.mkdir()
            (data_dir / "ops_metrics_history.jsonl").write_text(
                json.dumps(
                    {
                        "snapshot_date": "2000-01-01",
                        "collected_at": "2000-01-01T00:00:00+00:00",
                        "youtube_candidates_total": 3,
                        "youtube_candidates_strong": 1,
                        "missing_source_url_occurrences": 5,
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (data_dir / "youtube_year_backfill_candidates.json").write_text(
                json.dumps(
                    {
                        "summary": {
                            "candidate_count": 5,
                            "strong_count": 2,
                            "review_count": 1,
                            "status_counts": {"weak": 2},
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (data_dir / "missing_source_url_review_post_apply.json").write_text(
                json.dumps({"summary": {"missing_source_url_occurrence_count": 4}}, ensure_ascii=False),
                encoding="utf-8",
            )

            payload = data.load_ops_metrics(root=root)

        self.assertEqual(payload["current"]["youtube_candidates_total"], 5)
        self.assertEqual(payload["previous"]["youtube_candidates_total"], 3)
        self.assertEqual(payload["deltas"]["youtube_candidates_total"], 2)
        self.assertEqual(payload["deltas"]["youtube_candidates_strong"], 1)
        self.assertEqual(payload["deltas"]["missing_source_url_occurrences"], -1)
        self.assertGreaterEqual(len(payload["history"]), 2)
        self.assertEqual(payload["history_path"], "data/ops_metrics_history.jsonl")


if __name__ == "__main__":
    unittest.main()
