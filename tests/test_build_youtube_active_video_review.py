import unittest

from build_youtube_active_video_review import build_review, video_id_from_url


class BuildYoutubeActiveVideoReviewTest(unittest.TestCase):
    def test_extracts_video_id_from_shorts_url(self):
        self.assertEqual(
            video_id_from_url("https://www.youtube.com/shorts/abc123"),
            "abc123",
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
