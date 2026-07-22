import unittest

from youtube_channels.active_video_review import (
    DEFAULT_EXPORT_MAX_PER_CHANNEL,
    build_review,
    video_id_from_url,
)
from youtube_backfill.youtube_title_parts import split_youtube_title


class BuildYoutubeActiveVideoReviewTest(unittest.TestCase):
    def test_cli_default_keeps_canonical_export_full_size(self):
        self.assertEqual(DEFAULT_EXPORT_MAX_PER_CHANNEL, 10000)

    def test_extracts_video_id_from_shorts_url(self):
        self.assertEqual(
            video_id_from_url("https://www.youtube.com/shorts/abc123"),
            "abc123",
        )

    def test_splits_youtube_title_into_event_and_songs(self):
        self.assertEqual(
            split_youtube_title("【GMOシブヤエンタメ祭 盆踊り】「ダンシングヒーロー」荻野目洋子 / #盆踊り"),
            {
                "title_event_name_candidate": "GMOシブヤエンタメ祭 盆踊り",
                "title_song_candidates": ["ダンシングヒーロー"],
            },
        )
        self.assertEqual(
            split_youtube_title("[4K] 雷門盆踊り - 夢灯篭 - 2025 / 浅草 盆踊り Asakusa Kaminarimon Bon Odori 2025"),
            {
                "title_event_name_candidate": "雷門盆踊り",
                "title_song_candidates": ["夢灯篭"],
            },
        )
        self.assertEqual(
            split_youtube_title("【4K】靖国神社みたままつり盆踊り /「にっぽん花咲か音頭 / 四季の花踊り / 東京音頭 /〆太鼓」/ Yasukuni Shrine Mitama Festival 2025 #盆踊り"),
            {
                "title_event_name_candidate": "靖国神社みたままつり盆踊り",
                "title_song_candidates": ["にっぽん花咲か音頭", "四季の花踊り", "東京音頭", "〆太鼓"],
            },
        )
        self.assertEqual(
            split_youtube_title("[4K]🇯🇵 横浜開港祭 盆踊り ダンシングヒーロー ｜サザン｜よこはまアラメヤ音頭│セカオワ│野毛山節  他 2026.6.1 / Japanese Bon dance in Yokohama."),
            {
                "title_event_name_candidate": "横浜開港祭 盆踊り",
                "title_song_candidates": ["ダンシングヒーロー", "サザン", "よこはまアラメヤ音頭", "セカオワ", "野毛山節 他"],
            },
        )

    def test_marks_setlist_video_as_append_existing_event(self):
        review = build_review(
            [
                {
                    "source": "youtube",
                    "youtube_channel_id": "UC_ACTIVE",
                    "youtube_channel_title": "Active",
                    "name": "Active",
                    "title": "山王音頭と民踊大会 2026年6月13日",
                    "text": "盆踊り",
                    "url": "https://www.youtube.com/watch?v=aaa",
                    "date": "2026-06-14T00:00:00+00:00",
                }
            ],
            {"channels": [{"channel_id": "UC_ACTIVE", "status": "active", "collection_enabled": True}]},
            [{"name": "山王音頭と民踊大会", "venue": "山王パークタワー公開空地", "date": "2026-06-13"}],
            {
                "occurrences": [
                    {
                        "occurrence_key": "occ1",
                        "event_name_hint": "山王音頭と民踊大会",
                        "venue": "山王パークタワー公開空地",
                        "event_date": "2026-06-13",
                        "song_count": 3,
                        "confidence": "high",
                        "source_videos": [{"url": "https://www.youtube.com/watch?v=aaa"}],
                    }
                ]
            },
        )

        row = review["rows"][0]
        self.assertEqual(row["action"], "append_existing_event")
        self.assertEqual(row["priority"], "high")
        self.assertEqual(row["setlist_occurrences"][0]["occurrence_key"], "occ1")
        self.assertEqual(row["title_event_name_candidate"], "山王音頭と民踊大会")

    def test_marks_official_url_bon_video_for_confirmation(self):
        review = build_review(
            [
                {
                    "source": "youtube",
                    "youtube_channel_id": "UC_ACTIVE",
                    "youtube_channel_title": "Active",
                    "name": "Active",
                    "title": "Shibuya Bon Odori Dance festival 2025",
                    "text": "盆踊り\nhttps://example.com/official",
                    "media_urls": ["https://example.com/official"],
                    "url": "https://www.youtube.com/watch?v=bbb",
                    "date": "2025-08-04T00:00:00+00:00",
                }
            ],
            {"channels": [{"channel_id": "UC_ACTIVE", "status": "active", "collection_enabled": True}]},
            [],
            {"occurrences": []},
        )

        row = review["rows"][0]
        self.assertEqual(row["action"], "needs_official_confirmation")
        self.assertEqual(row["official_urls"], ["https://example.com/official"])

    def test_marks_parent_event_bon_component(self):
        review = build_review(
            [
                {
                    "source": "youtube",
                    "youtube_channel_id": "UC_ACTIVE",
                    "youtube_channel_title": "Urban Walk",
                    "name": "Urban Walk",
                    "title": "【GMOシブヤエンタメ祭 盆踊り】ダンシングヒーロー SHIBUYA MIYASHITA PARK BON DANCE",
                    "text": "JAME盆踊りとして実施された盆踊り企画です。",
                    "url": "https://www.youtube.com/watch?v=gmo",
                    "date": "2025-06-10T00:00:00+00:00",
                }
            ],
            {"channels": [{"channel_id": "UC_ACTIVE", "status": "active", "collection_enabled": True}]},
            [],
            {"occurrences": []},
        )

        row = review["rows"][0]
        self.assertEqual(row["action"], "bon_component_of_parent_event")
        self.assertEqual(row["parent_event_name"], "GMOシブヤエンタメ祭")
        self.assertEqual(row["component_label"], "JAME盆踊り / SHIBUYA MIYASHITA PARK BON DANCE")

    def test_parent_event_song_clip_fragment_is_auto_classified_as_component(self):
        review = build_review(
            [
                {
                    "source": "youtube",
                    "youtube_channel_id": "UC_ACTIVE",
                    "youtube_channel_title": "Urban Walk",
                    "name": "Urban Walk",
                    "title": "【GMOシブヤエンタメ祭 盆踊り】「ダンシングヒーロー」荻野目洋子",
                    "text": "JAME盆踊りとして実施された盆踊り企画です。",
                    "url": "https://www.youtube.com/watch?v=gmo-song",
                    "date": "2025-06-10T00:00:00+00:00",
                }
            ],
            {"channels": [{"channel_id": "UC_ACTIVE", "status": "active", "collection_enabled": True}]},
            [],
            {"occurrences": []},
        )

        row = review["rows"][0]
        self.assertEqual(row["action"], "bon_component_of_parent_event")
        self.assertEqual(row["auto_review_note"], "parent_event_song_clip_fragment")
        self.assertEqual(row["parent_event_name"], "GMOシブヤエンタメ祭")

    def test_shorts_song_clip_without_event_evidence_is_ignored(self):
        review = build_review(
            [
                {
                    "source": "youtube",
                    "youtube_channel_id": "UC_ACTIVE",
                    "youtube_channel_title": "Exploring Japan with Zen",
                    "name": "Exploring Japan with Zen",
                    "title": "Jiyugaoka Bon Dance 2025-04 自由が丘 盆踊り 2025 ダンシングヒーロー #shorts",
                    "text": "",
                    "url": "https://www.youtube.com/watch?v=short1",
                    "date": "2025-07-25T10:29:34Z",
                }
            ],
            {"channels": [{"channel_id": "UC_ACTIVE", "status": "active", "collection_enabled": True}]},
            [],
            {"occurrences": []},
        )

        row = review["rows"][0]
        self.assertEqual(row["action"], "ignore")
        self.assertEqual(row["auto_review_note"], "shorts_song_fragment")

    def test_noisy_channel_weak_video_evidence_is_ignored(self):
        review = build_review(
            [
                {
                    "source": "youtube",
                    "youtube_channel_id": "UC_ACTIVE",
                    "youtube_channel_title": "Tokyo Hz",
                    "name": "Tokyo Hz",
                    "title": "Pt.1 Full of Fun!! Kabukicho Bon Odori 2025 in Shinjuku, Tokyo 4K60",
                    "text": "",
                    "url": "https://www.youtube.com/watch?v=tokyohz1",
                    "date": "2025-08-17T04:36:57Z",
                }
            ],
            {"channels": [{"channel_id": "UC_ACTIVE", "status": "active", "collection_enabled": True}]},
            [],
            {"occurrences": []},
        )

        row = review["rows"][0]
        self.assertEqual(row["action"], "ignore")
        self.assertEqual(row["auto_review_note"], "noisy_channel_weak_video_evidence")

    def test_noisy_channel_with_official_url_still_needs_confirmation(self):
        review = build_review(
            [
                {
                    "source": "youtube",
                    "youtube_channel_id": "UC_ACTIVE",
                    "youtube_channel_title": "Tokyo Lonely Walker",
                    "name": "Tokyo Lonely Walker",
                    "title": "Nakano Bon Dance 2025",
                    "text": "盆踊り",
                    "media_urls": ["https://example.com/nakano-bon-dance"],
                    "url": "https://www.youtube.com/watch?v=tlw1",
                    "date": "2025-08-03T10:01:03Z",
                }
            ],
            {"channels": [{"channel_id": "UC_ACTIVE", "status": "active", "collection_enabled": True}]},
            [],
            {"occurrences": []},
        )

        row = review["rows"][0]
        self.assertEqual(row["action"], "needs_official_confirmation")

    def test_noisy_channel_with_public_event_match_still_appends_existing_event(self):
        review = build_review(
            [
                {
                    "source": "youtube",
                    "youtube_channel_id": "UC_ACTIVE",
                    "youtube_channel_title": "Tokyo Lonely Walker",
                    "name": "Tokyo Lonely Walker",
                    "title": "山王音頭と民踊大会 2026年6月13日",
                    "text": "盆踊り",
                    "url": "https://www.youtube.com/watch?v=tlw-match",
                    "date": "2026-06-14T00:00:00+00:00",
                }
            ],
            {"channels": [{"channel_id": "UC_ACTIVE", "status": "active", "collection_enabled": True}]},
            [{"name": "山王音頭と民踊大会", "venue": "山王パークタワー公開空地", "date": "2026-06-13"}],
            {"occurrences": []},
        )

        row = review["rows"][0]
        self.assertEqual(row["action"], "append_existing_event")

    def test_other_channel_weak_video_evidence_stays_reviewable(self):
        review = build_review(
            [
                {
                    "source": "youtube",
                    "youtube_channel_id": "UC_ACTIVE",
                    "youtube_channel_title": "Urban Walk",
                    "name": "Urban Walk",
                    "title": "Kabukicho Bon Odori 2025 in Shinjuku, Tokyo",
                    "text": "",
                    "url": "https://www.youtube.com/watch?v=urban1",
                    "date": "2025-08-17T04:36:57Z",
                }
            ],
            {"channels": [{"channel_id": "UC_ACTIVE", "status": "active", "collection_enabled": True}]},
            [],
            {"occurrences": []},
        )

        row = review["rows"][0]
        self.assertEqual(row["action"], "review_video_evidence")

    def test_filters_channel_maps_and_social_urls_from_official_urls(self):
        review = build_review(
            [
                {
                    "source": "youtube",
                    "youtube_channel_id": "UC_ACTIVE",
                    "youtube_channel_title": "Tokyo Lonely Walker",
                    "name": "Tokyo Lonely Walker",
                    "title": "盆踊り動画",
                    "text": "盆踊り",
                    "media_urls": [
                        "https://www.youtube.com/channel/UC_ACTIVE",
                        "https://goo.gl/maps/example",
                        "https://maps.app.goo.gl/example",
                        "https://x.com/walkingfilmlove",
                        "https://linktr.ee/tokyohertz",
                        "https://example.com/event",
                    ],
                    "url": "https://www.youtube.com/watch?v=maps",
                    "date": "2025-08-04T00:00:00+00:00",
                }
            ],
            {"channels": [{"channel_id": "UC_ACTIVE", "status": "active", "collection_enabled": True}]},
            [],
            {"occurrences": []},
        )

        row = review["rows"][0]
        self.assertEqual(row["official_urls"], ["https://example.com/event"])

    def test_related_video_bon_text_does_not_create_bon_context(self):
        review = build_review(
            [
                {
                    "source": "youtube",
                    "youtube_channel_id": "UC_ACTIVE",
                    "youtube_channel_title": "Tokyo Lonely Walker",
                    "name": "Tokyo Lonely Walker",
                    "title": "浅草寺 初詣 2025",
                    "text": "初詣に行きました。\n▽Related Videos\n密集度都内No.1 浅草 雷門盆踊り\nhttps://youtu.be/aaa",
                    "media_urls": ["https://goo.gl/maps/example", "https://x.com/walkingfilmlove"],
                    "url": "https://www.youtube.com/watch?v=hatsumode",
                    "date": "2025-01-01T00:00:00+00:00",
                }
            ],
            {"channels": [{"channel_id": "UC_ACTIVE", "status": "active", "collection_enabled": True}]},
            [],
            {"occurrences": []},
        )

        row = review["rows"][0]
        self.assertFalse(row["has_bon_context"])
        self.assertEqual(row["action"], "ignore")

    def test_playlist_sections_do_not_create_bon_context(self):
        review = build_review(
            [
                {
                    "source": "youtube",
                    "youtube_channel_id": "UC_ACTIVE",
                    "youtube_channel_title": "Tokyo Hz",
                    "name": "Tokyo Hz",
                    "title": "Shibuya Sky sunset walk",
                    "text": (
                        "4K footage of Shibuya Sky.\n"
                        "【4K Shibuya Sky】\n"
                        "Super Exciting!! Rooftop Bon Dance at Shibuya Sky\n"
                        "https://youtu.be/aaa"
                    ),
                    "url": "https://www.youtube.com/watch?v=sky",
                    "date": "2025-01-01T00:00:00+00:00",
                }
            ],
            {"channels": [{"channel_id": "UC_ACTIVE", "status": "active", "collection_enabled": True}]},
            [],
            {"occurrences": []},
        )

        row = review["rows"][0]
        self.assertFalse(row["has_bon_context"])
        self.assertEqual(row["action"], "ignore")

    def test_duplicate_review_video_evidence_is_auto_ignored(self):
        voices = [
            {
                "source": "youtube",
                "youtube_channel_id": "UC_ACTIVE",
                "youtube_channel_title": "Urban Walk",
                "name": "Urban Walk",
                "title": "【肉フェス 2025 アニメメメ盆踊り】「さんぽ」 お台場",
                "text": "盆踊り",
                "url": "https://www.youtube.com/watch?v=meat1",
                "date": "2025-05-07T00:00:00+00:00",
            },
            {
                "source": "youtube",
                "youtube_channel_id": "UC_ACTIVE",
                "youtube_channel_title": "Urban Walk",
                "name": "Urban Walk",
                "title": "【肉フェス 2025 アニメメメ盆踊り】「東京音頭」 お台場",
                "text": "盆踊り",
                "url": "https://www.youtube.com/watch?v=meat2",
                "date": "2025-05-08T00:00:00+00:00",
            },
        ]
        review = build_review(
            voices,
            {"channels": [{"channel_id": "UC_ACTIVE", "status": "active", "collection_enabled": True}]},
            [],
            {"occurrences": []},
            max_per_channel=10,
        )

        self.assertEqual([row["action"] for row in review["rows"]], ["bon_component_of_parent_event", "ignore"])
        self.assertEqual(
            {row["auto_review_note"] for row in review["rows"]},
            {"parent_event_song_clip_fragment", "duplicate_parent_event_component"},
        )

    def test_duplicate_official_confirmation_is_auto_ignored(self):
        voices = [
            {
                "source": "youtube",
                "youtube_channel_id": "UC_ACTIVE",
                "youtube_channel_title": "shu channel",
                "name": "shu channel",
                "title": "赤坂・日枝神社🏮盆踊り(1/6) 東京音頭",
                "text": "盆踊り",
                "media_urls": ["https://www.tenkamatsuri.jp/minyo/"],
                "url": "https://www.youtube.com/watch?v=sanno1",
                "date": "2025-06-13T00:00:00+00:00",
            },
            {
                "source": "youtube",
                "youtube_channel_id": "UC_ACTIVE",
                "youtube_channel_title": "shu channel",
                "name": "shu channel",
                "title": "赤坂・日枝神社🏮盆踊り(2/6) 炭坑節",
                "text": "盆踊り",
                "media_urls": ["https://www.tenkamatsuri.jp/minyo/"],
                "url": "https://www.youtube.com/watch?v=sanno2",
                "date": "2025-06-13T00:00:00+00:00",
            },
        ]
        review = build_review(
            voices,
            {"channels": [{"channel_id": "UC_ACTIVE", "status": "active", "collection_enabled": True}]},
            [],
            {"occurrences": []},
            max_per_channel=10,
        )

        actions = sorted(row["action"] for row in review["rows"])
        self.assertEqual(actions, ["ignore", "needs_official_confirmation"])
        ignored = next(row for row in review["rows"] if row["action"] == "ignore")
        self.assertEqual(ignored["auto_review_note"], "duplicate_official_confirmation")

    def test_does_not_match_public_event_when_detected_date_is_outside_event_range(self):
        review = build_review(
            [
                {
                    "source": "youtube",
                    "youtube_channel_id": "UC_ACTIVE",
                    "youtube_channel_title": "Active",
                    "name": "Active",
                    "title": "山王音頭と民踊大会 2025年6月13日",
                    "text": "盆踊り",
                    "url": "https://www.youtube.com/watch?v=date1",
                    "date": "2025-06-14T00:00:00+00:00",
                }
            ],
            {"channels": [{"channel_id": "UC_ACTIVE", "status": "active", "collection_enabled": True}]},
            [{"name": "山王音頭と民踊大会", "venue": "山王パークタワー公開空地", "date": "2026-06-13"}],
            {"occurrences": []},
        )

        row = review["rows"][0]
        self.assertEqual(row["matched_public_event"], None)
        self.assertEqual(row["action"], "review_video_evidence")

    def test_matches_hanazono_after_public_event_exists(self):
        review = build_review(
            [
                {
                    "source": "youtube",
                    "youtube_channel_id": "UC_ACTIVE",
                    "youtube_channel_title": "Urban Walk",
                    "name": "Urban Walk",
                    "title": "生歌「八木節」!!【新宿 花園神社 盆踊り 2025】",
                    "text": "開催日時：2025年8月2日(土)\n開催場所：新宿 花園神社",
                    "url": "https://www.youtube.com/watch?v=hanazono",
                    "date": "2025-08-02T15:37:37Z",
                }
            ],
            {"channels": [{"channel_id": "UC_ACTIVE", "status": "active", "collection_enabled": True}]},
            [{"name": "花園神社 盆踊り", "venue": "花園神社", "date": "2025-08-01", "date_end": "2025-08-02"}],
            {"occurrences": []},
        )

        row = review["rows"][0]
        self.assertEqual(row["action"], "append_existing_event")
        self.assertEqual(row["matched_public_event"]["name"], "花園神社 盆踊り")

    def test_does_not_match_weak_partial_without_detected_date(self):
        review = build_review(
            [
                {
                    "source": "youtube",
                    "youtube_channel_id": "UC_ACTIVE",
                    "youtube_channel_title": "Urban Walk",
                    "name": "Urban Walk",
                    "title": "【新宿 花園神社】酉の市 2025 一の酉",
                    "text": "屋台 とりのいち",
                    "url": "https://www.youtube.com/watch?v=tori",
                    "date": "2025-11-13T00:00:00+00:00",
                }
            ],
            {"channels": [{"channel_id": "UC_ACTIVE", "status": "active", "collection_enabled": True}]},
            [{"name": "花園神社 盆踊り", "venue": "花園神社", "date": "2025-08-01", "date_end": "2025-08-02"}],
            {"occurrences": []},
        )

        row = review["rows"][0]
        self.assertEqual(row["matched_public_event"], None)
        self.assertEqual(row["action"], "ignore")

    def test_marks_out_of_scope_setlist_video_as_out_of_scope(self):
        review = build_review(
            [
                {
                    "source": "youtube",
                    "youtube_channel_id": "UC_ACTIVE",
                    "youtube_channel_title": "Active",
                    "name": "Active",
                    "title": "横浜開港祭 BON ODORI 2026",
                    "text": "横浜で開催された盆踊り",
                    "url": "https://www.youtube.com/watch?v=ccc",
                    "date": "2026-06-02T00:00:00+00:00",
                }
            ],
            {"channels": [{"channel_id": "UC_ACTIVE", "status": "active", "collection_enabled": True}]},
            [],
            {
                "occurrences": [
                    {
                        "occurrence_key": "occ-out",
                        "event_name_hint": "横浜開港祭 BON ODORI",
                        "venue": "パシフィコ横浜プラザ広場",
                        "event_date": "2026-06-01",
                        "song_count": 3,
                        "source_videos": [{"url": "https://www.youtube.com/watch?v=ccc"}],
                    }
                ]
            },
        )

        self.assertEqual(review["rows"][0]["action"], "out_of_scope")


if __name__ == "__main__":
    unittest.main()
