import unittest

from youtube_backfill.harvest_youtube_year_backfill import evidence_score, merge_harvests, queue_rows


class HarvestYoutubeYearBackfillTest(unittest.TestCase):
    def test_queue_rows_selects_priority_and_limit(self):
        queue = {
            "rows": [
                {"priority": "low", "priority_score": 100, "target_year": 2024, "event_name": "low"},
                {"priority": "high", "priority_score": 80, "target_year": 2024, "event_name": "b"},
                {"priority": "high", "priority_score": 90, "target_year": 2023, "event_name": "a"},
            ]
        }

        rows = queue_rows(queue, limit=1, priorities=["high"])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_name"], "a")

    def test_queue_rows_applies_offset(self):
        queue = {
            "rows": [
                {"priority": "high", "priority_score": 100, "target_year": 2024, "event_name": "a"},
                {"priority": "high", "priority_score": 90, "target_year": 2024, "event_name": "b"},
                {"priority": "high", "priority_score": 80, "target_year": 2024, "event_name": "c"},
            ]
        }

        rows = queue_rows(queue, limit=1, priorities=["high"], offset=1)

        self.assertEqual([row["event_name"] for row in rows], ["b"])

    def test_evidence_score_strong_when_event_venue_year_and_date_match(self):
        row = {
            "event_name": "丸の内de盆踊り",
            "venue": "行幸通り",
            "target_year": 2024,
        }
        video = {
            "title": "丸の内de盆踊り 行幸通り 2024年7月26日 東京音頭 #盆踊り",
            "description": "",
            "channel_title": "sample",
            "setlist_count": 2,
        }

        score, status, reasons, detected_date = evidence_score(row, video)

        self.assertEqual(status, "strong")
        self.assertGreaterEqual(score, 80)
        self.assertEqual(detected_date, "2024-07-26")
        self.assertIn("target_year_date_detected", reasons)

    def test_evidence_score_weak_for_other_event(self):
        row = {
            "event_name": "丸の内de盆踊り",
            "venue": "行幸通り",
            "target_year": 2024,
        }
        video = {
            "title": "別イベント 2024年8月1日 盆踊り",
            "description": "",
            "channel_title": "sample",
            "setlist_count": 0,
        }

        score, status, _reasons, detected_date = evidence_score(row, video)

        self.assertEqual(status, "weak")
        self.assertLess(score, 50)
        self.assertEqual(detected_date, "2024-08-01")

    def test_evidence_score_caps_other_year_match(self):
        row = {
            "event_name": "山王音頭と民踊大会",
            "venue": "山王パークタワー公開空地",
            "target_year": 2023,
        }
        video = {
            "title": "山王音頭と民踊大会 山王パークタワー公開空地 2024年6月13日 盆踊り",
            "description": "",
            "channel_title": "sample",
            "setlist_count": 2,
        }

        score, status, reasons, detected_date = evidence_score(row, video)

        self.assertEqual(status, "weak")
        self.assertLess(score, 50)
        self.assertEqual(detected_date, "2024-06-13")
        self.assertIn("other_year_date_detected", reasons)

    def test_merge_harvests_deduplicates_candidates(self):
        existing = {
            "generated_at": "old",
            "selected_queue_rows": [{"queue_id": "q1", "priority_score": 10, "target_year": 2024, "event_name": "a"}],
            "candidates": [{
                "queue_id": "q1",
                "video_id": "v1",
                "score": 80,
                "status": "strong",
                "target_year": 2024,
                "event_name": "a",
                "title": "old",
            }],
        }
        fresh = {
            "generated_at": "new",
            "selected_queue_rows": [{"queue_id": "q2", "priority_score": 9, "target_year": 2024, "event_name": "b"}],
            "candidates": [
                {
                    "queue_id": "q1",
                    "video_id": "v1",
                    "score": 90,
                    "status": "strong",
                    "target_year": 2024,
                    "event_name": "a",
                    "title": "new",
                },
                {
                    "queue_id": "q2",
                    "video_id": "v2",
                    "score": 55,
                    "status": "review",
                    "target_year": 2024,
                    "event_name": "b",
                    "title": "fresh",
                },
            ],
        }

        merged = merge_harvests(existing, fresh)

        self.assertEqual(merged["selected_queue_count"], 2)
        self.assertEqual(merged["summary"]["candidate_count"], 2)
        self.assertEqual(merged["summary"]["strong_count"], 1)
        self.assertEqual(merged["summary"]["review_count"], 1)
        self.assertEqual(merged["candidates"][0]["title"], "new")


if __name__ == "__main__":
    unittest.main()
