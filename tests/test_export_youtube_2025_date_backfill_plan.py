import unittest

from export_youtube_2025_date_backfill_plan import classify, source_mentions_dates


class ExportYoutube2025DateBackfillPlanTest(unittest.TestCase):
    def test_matches_japanese_date_with_spaces(self):
        source_text = "令和7年の例大祭 8月 9 日（土） 盆踊り"

        matches = source_mentions_dates(source_text, ["2025-08-09"])

        self.assertIn("2025-08-09", matches)

    def test_classifies_single_confirmed_date_in_multi_date_group_as_ready(self):
        group = {
            "category": "date_backfill_candidate_multi_date",
            "detected_dates": ["2025-07-05", "2025-12-20"],
        }

        status, _ = classify(
            group,
            {"ok": True, "status": "200"},
            {"2025-07-05": ["2025.07.05"]},
        )

        self.assertEqual(status, "ready")


if __name__ == "__main__":
    unittest.main()
