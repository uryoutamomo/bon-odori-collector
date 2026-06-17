import unittest

from build_youtube_year_backfill_queue import build_queue, event_name_for_target_year
from build_event_occurrence_observations import series_key


class BuildYoutubeYearBackfillQueueTest(unittest.TestCase):
    def test_build_queue_prioritizes_observed_series_and_skips_observed_year(self):
        event = {
            "name": "自由が丘納涼盆踊り大会",
            "venue": "自由が丘駅前ロータリー 特設会場",
            "area": "目黒区",
            "recurrence_score": 0.9,
            "source_urls": [{"url": "https://example.com", "kind": "official"}],
            "songs": [{"name": "東京音頭"}],
        }
        observations = {
            "observations": [{
                "series_key": series_key(event["name"], event["venue"]),
                "event_name": event["name"],
                "venue": event["venue"],
                "year": 2025,
                "source_video_count": 22,
            }]
        }

        queue = build_queue([event], observations, [2025, 2024, 2023])

        self.assertEqual([row["target_year"] for row in queue["rows"]], [2024, 2023])
        self.assertEqual(queue["summary"]["items"], 2)
        self.assertEqual(queue["summary"]["observed_seed_items"], 2)
        self.assertEqual(queue["rows"][0]["priority"], "high")
        self.assertIn("youtube_observed_series", queue["rows"][0]["priority_reasons"])
        self.assertIn("自由が丘納涼盆踊り大会", queue["rows"][0]["search_queries"][0])

    def test_build_queue_keeps_low_priority_public_events(self):
        event = {
            "name": "町内盆踊り",
            "venue": "町内公園",
            "area": "港区",
        }

        queue = build_queue([event], {"observations": []}, [2024])

        self.assertEqual(queue["summary"]["items"], 1)
        self.assertEqual(queue["rows"][0]["priority"], "low")
        self.assertEqual(queue["rows"][0]["observed_years"], [])

    def test_event_name_for_target_year_replaces_existing_year(self):
        self.assertEqual(
            event_name_for_target_year("郡上おどり in 青山 2026", 2024),
            "郡上おどり in 青山 2024",
        )

    def test_build_queue_deduplicates_same_event_venue_year(self):
        events = [
            {
                "name": "SHIBUYA MIYASHITA PARK BON DANCE 2026",
                "venue": "宮下公園",
                "source_urls": [],
            },
            {
                "name": "SHIBUYA MIYASHITA PARK BON DANCE 2026",
                "venue": "宮下公園",
                "source_urls": [{"url": "https://example.com"}],
            },
        ]

        queue = build_queue(events, {"observations": []}, [2024])

        self.assertEqual(queue["summary"]["items"], 1)
        self.assertEqual(queue["rows"][0]["source_url_count"], 1)
        self.assertIn("2024", queue["rows"][0]["search_queries"][0])
        self.assertNotIn("2026", queue["rows"][0]["search_queries"][0])


if __name__ == "__main__":
    unittest.main()
