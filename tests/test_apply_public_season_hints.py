import unittest

from public_json_postprocessors.apply_public_season_hints import apply_season_hints


class ApplyPublicSeasonHintsTest(unittest.TestCase):
    def test_applies_low_confidence_hint_to_date_unknown_event(self):
        events = [{
            "name": "京橋盆踊り",
            "venue": "京橋エドグラン",
            "public_category": "date_unknown",
            "months": [8],
            "jun": {"8": "下旬"},
            "hints": [[8, 27]],
        }]

        result = apply_season_hints(events)

        self.assertEqual(result["report"]["target_count"], 1)
        self.assertEqual(result["report"]["applied_count"], 1)
        self.assertEqual(result["report"]["skipped_count"], 0)
        self.assertEqual(result["events"][0]["season_hint_label"], "8月下旬")
        self.assertEqual(result["events"][0]["season_confidence"], "lowest")
        self.assertEqual(result["events"][0]["season_hint"]["display_tier"], "season_hint")
        self.assertEqual(result["events"][0]["display_tier"], "season_hint")

    def test_skips_date_unknown_event_without_month_hint(self):
        events = [{
            "name": "日本橋小学校の盆踊り",
            "venue": "日本橋小学校",
            "public_category": "date_unknown",
            "months": [],
            "jun": {},
            "hints": [],
        }]

        result = apply_season_hints(events)

        self.assertEqual(result["report"]["target_count"], 1)
        self.assertEqual(result["report"]["applied_count"], 0)
        self.assertEqual(result["report"]["skipped_count"], 1)
        self.assertEqual(result["report"]["skipped"][0]["reason"], "no_month_or_season_hint")
        self.assertNotIn("season_hint", result["events"][0])

    def test_clears_existing_hint_from_non_target_event(self):
        events = [{
            "name": "確定イベント",
            "public_category": "upcoming",
            "season_hint": {"old": True},
            "season_months": [7],
        }]

        result = apply_season_hints(events)

        self.assertEqual(result["report"]["target_count"], 0)
        self.assertNotIn("season_hint", result["events"][0])
        self.assertNotIn("season_months", result["events"][0])


if __name__ == "__main__":
    unittest.main()
