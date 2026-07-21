import unittest

from rdb_builders.build_bon_odori_rdb import build_unified_rows


class BuildBonOdoriRdbTest(unittest.TestCase):
    def test_links_notion_youtube_evidence_and_setlist_songs(self):
        rows = build_unified_rows({
            "notion_events": [
                {
                    "page_id": "event1",
                    "event_name": "山王音頭と民踊大会",
                    "start_date": "2026-06-13",
                    "end_date": "2026-06-15",
                    "status": "確認済み",
                    "detail": "[youtube_evidence] 2026実績\n- 動画: https://www.youtube.com/watch?v=abc123\n- 曲目候補: 東京音頭",
                    "source_url": "",
                }
            ],
            "notion_venues": [
                {"page_id": "venue1", "venue_name": "山王パークタワー公開空地", "area": "千代田区", "address": "", "access": "", "scale": "中"}
            ],
            "notion_songs": [
                {"page_id": "song1", "song_name": "東京音頭", "category": "定番曲", "status": "候補", "evidence_count": 1, "source_url": ""}
            ],
            "notion_relations": [
                {"page_id": "event1", "property_name": "会場", "related_page_id": "venue1"}
            ],
            "source_posts": [],
            "x_candidate_reviews": [],
            "youtube_videos": [
                {
                    "video_id": "abc123",
                    "video_url": "https://www.youtube.com/watch?v=abc123",
                    "channel_id": "UC1",
                    "title": "山王音頭と民踊大会",
                    "description_excerpt": "盆踊り",
                    "published_at": "2026-06-14T00:00:00+00:00",
                    "detected_event_date": "2026-06-13",
                    "action": "append_existing_event",
                }
            ],
            "youtube_video_matches": [
                {
                    "video_id": "abc123",
                    "event_name": "山王音頭と民踊大会",
                    "venue": "山王パークタワー公開空地",
                    "event_date": "2026-06-13",
                    "reasons_json": "[]",
                }
            ],
            "youtube_occurrences": [
                {
                    "occurrence_key": "occ1",
                    "event_name_hint": "山王音頭と民踊大会",
                    "canonical_event_name": "",
                    "venue": "山王パークタワー公開空地",
                    "song_count": 1,
                    "event_date": "2026-06-13",
                    "confidence": "high",
                }
            ],
            "youtube_occurrence_videos": [],
            "youtube_setlist_songs": [
                {
                    "occurrence_key": "occ1",
                    "position": 1,
                    "title": "東京音頭",
                    "video_url": "https://www.youtube.com/watch?v=abc123",
                    "video_id": "abc123",
                }
            ],
        })

        self.assertEqual(len(rows["event_links"]), 2)
        statuses = {row["link_status"] for row in rows["event_links"]}
        self.assertIn("already_reflected", statuses)
        self.assertEqual(rows["song_links"][0]["link_status"], "matched_song")
        self.assertEqual(len(rows["event_song_links"]), 1)
        self.assertEqual(rows["event_song_links"][0]["event_id"], "event1")
        self.assertEqual(rows["event_song_links"][0]["song_id"], "song1")
        self.assertEqual(rows["event_song_links"][0]["dance_variant_id"], "")
        self.assertEqual(rows["dance_variants"], [])

    def test_unmatched_setlist_song_goes_to_review_queue(self):
        rows = build_unified_rows({
            "notion_events": [],
            "notion_venues": [],
            "notion_songs": [],
            "notion_relations": [],
            "source_posts": [],
            "x_candidate_reviews": [],
            "youtube_videos": [],
            "youtube_video_matches": [],
            "youtube_occurrences": [],
            "youtube_occurrence_videos": [],
            "youtube_setlist_songs": [
                {"occurrence_key": "occ1", "position": 1, "title": "未登録音頭", "video_url": "", "video_id": ""}
            ],
        })

        self.assertEqual(rows["song_links"][0]["link_status"], "unmatched_song")
        self.assertTrue(any(row["review_status"] == "song_not_in_master" for row in rows["review"]))


if __name__ == "__main__":
    unittest.main()
