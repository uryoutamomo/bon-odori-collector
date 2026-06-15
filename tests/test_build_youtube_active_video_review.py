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
