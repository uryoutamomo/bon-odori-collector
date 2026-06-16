import unittest

from export_youtube_2025_official_candidate_validation import classify, source_mentions_dates


class ExportYoutube2025OfficialCandidateValidationTest(unittest.TestCase):
    def test_date_only_match_is_new_event_review(self):
        status, _ = classify(
            {"detected_dates": ["2025-08-23"]},
            {"ok": True, "status": "200"},
            {"2025-08-23": ["8月23日"]},
            [{"score": 35, "reasons": ["date_overlap"]}],
        )

        self.assertEqual(status, "new_event_review")

    def test_source_mentions_japanese_date_with_spaces(self):
        matches = source_mentions_dates("令和7年 6月 13 日 山王音頭", ["2025-06-13"])

        self.assertIn("2025-06-13", matches)


if __name__ == "__main__":
    unittest.main()
