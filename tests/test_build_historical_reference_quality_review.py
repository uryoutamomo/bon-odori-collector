import unittest

import build_historical_reference_quality_review as builder


class BuildHistoricalReferenceQualityReviewTest(unittest.TestCase):
    def test_build_review_flags_missing_date_and_songs(self):
        payload = builder.build_review(
            [
                {
                    "name": "A盆踊り",
                    "venue": "A公園",
                    "public_category": "recurring_last_year",
                    "historical_last_seen_year": 2025,
                    "last_seen_dates": [],
                    "songs": [],
                },
                {
                    "name": "B盆踊り",
                    "venue": "B公園",
                    "public_category": "recurring_last_year",
                    "last_seen_dates": ["2025-07-20"],
                    "songs": [{"name": "東京音頭"}],
                },
                {
                    "name": "C盆踊り",
                    "venue": "C公園",
                    "public_category": "confirmed",
                    "songs": [],
                },
            ]
        )

        self.assertEqual(payload["summary"]["historical_reference_count"], 2)
        self.assertEqual(payload["summary"]["review_count"], 1)
        row = payload["review"][0]
        self.assertEqual(row["event_name"], "A盆踊り")
        self.assertIn("historical_date_missing", row["issue_codes"])
        self.assertIn("historical_songs_missing", row["issue_codes"])
        self.assertEqual(row["priority_label"], "P0")
        self.assertEqual(row["recommended_action"], "review_missing_historical_date")

    def test_build_review_flags_missing_songs_but_keeps_weekday_label(self):
        payload = builder.build_review(
            [
                {
                    "name": "A盆踊り",
                    "venue": "A公園",
                    "public_category": "recurring_last_year",
                    "last_seen_dates": ["2025-07-20"],
                    "songs": [],
                }
            ]
        )

        row = payload["review"][0]
        self.assertEqual(row["historical_dates_label"], "2025-07-20（日）")
        self.assertEqual(row["historical_weekdays_label"], "日")
        self.assertEqual(row["priority_label"], "P1")
        self.assertEqual(row["recommended_action"], "review_missing_historical_songs")


if __name__ == "__main__":
    unittest.main()
