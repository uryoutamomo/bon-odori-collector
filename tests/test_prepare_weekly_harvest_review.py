import unittest

from prepare_weekly_harvest_review import build_summary, split_non_song_review_rows


class PrepareWeeklyHarvestReviewTest(unittest.TestCase):
    def test_splits_non_song_rows_for_human_review(self):
        rows = [
            {"category": "曲候補", "term": "東京音頭"},
            {"category": "用語候補", "term": "輪踊り"},
            {"category": "曲×会場共起", "term": "東京音頭 × 飛鳥山公園"},
        ]

        review_rows = split_non_song_review_rows(rows)

        self.assertEqual([row["term"] for row in review_rows], ["輪踊り", "東京音頭 × 飛鳥山公園"])

    def test_builds_summary_counts(self):
        source = {
            "days": 7,
            "voice_count": 12,
            "rows": [
                {"category": "曲候補", "term": "東京音頭"},
                {"category": "用語候補", "term": "輪踊り"},
            ],
        }
        song_triage = {
            "song_candidate_count": 1,
            "direct_count": 1,
            "rejected_noise_count": 0,
        }
        song_review = {"rows": [{"category": "曲候補", "term": "郡上おどり"}]}

        summary = build_summary(source, song_triage, [source["rows"][1]], song_review)

        self.assertEqual(summary["candidate_count"], 2)
        self.assertEqual(summary["category_counts"], {"曲候補": 1, "用語候補": 1})
        self.assertEqual(summary["non_song_review_count"], 1)
        self.assertEqual(summary["song_review_count"], 1)
        self.assertEqual(summary["song_direct_dry_run_count"], 1)


if __name__ == "__main__":
    unittest.main()
