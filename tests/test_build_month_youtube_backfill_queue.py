import unittest

from youtube_backfill.build_month_youtube_backfill_queue import build_month_queue


class BuildMonthYoutubeBackfillQueueTest(unittest.TestCase):
    def test_build_month_queue_filters_month_and_skips_seen_rows(self):
        queue = {
            "rows": [
                {
                    "queue_id": "june",
                    "target_year": 2024,
                    "priority": "low",
                    "priority_score": 15,
                    "event_name": "6月盆踊り",
                    "venue": "公園",
                    "public_date": "2026-06-07",
                    "last_seen_dates": [],
                    "search_queries": ["a", "b", "c"],
                },
                {
                    "queue_id": "seen",
                    "target_year": 2024,
                    "priority": "high",
                    "priority_score": 90,
                    "event_name": "検索済み6月",
                    "venue": "広場",
                    "public_date": "2026-06-08",
                    "last_seen_dates": [],
                    "search_queries": ["a", "b"],
                },
                {
                    "queue_id": "july",
                    "target_year": 2024,
                    "priority": "high",
                    "priority_score": 90,
                    "event_name": "7月盆踊り",
                    "venue": "広場",
                    "public_date": "2026-07-08",
                    "last_seen_dates": [],
                    "search_queries": ["a", "b"],
                },
            ]
        }
        candidates = {"selected_queue_rows": [{"queue_id": "seen"}]}

        result = build_month_queue(queue, candidates, 6)

        self.assertEqual(result["summary"]["items"], 1)
        self.assertEqual(result["summary"]["estimated_search_calls"], 2)
        self.assertEqual(result["rows"][0]["queue_id"], "june")


if __name__ == "__main__":
    unittest.main()
