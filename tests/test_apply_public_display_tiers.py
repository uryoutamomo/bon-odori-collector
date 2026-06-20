import unittest

from apply_public_display_tiers import apply_display_tiers, display_tier_for_event


class ApplyPublicDisplayTiersTest(unittest.TestCase):
    def test_priority_prefers_rule_prediction_over_historical_reference(self):
        event = {
            "public_category": "recurring_last_year",
            "date_prediction": {"date": "2026-07-31"},
            "historical_reference": {"label": "2025実績"},
        }

        self.assertEqual(display_tier_for_event(event), "rule_predicted")

    def test_sets_confirmed_and_ended_tiers(self):
        self.assertEqual(
            display_tier_for_event({"public_category": "upcoming", "date": "2026-07-01"}),
            "confirmed",
        )
        self.assertEqual(
            display_tier_for_event({"public_category": "ended", "date": "2026-06-01"}),
            "ended",
        )

    def test_date_unknown_without_hint_still_gets_top_level_tier(self):
        event = {"public_category": "date_unknown"}

        self.assertEqual(display_tier_for_event(event), "season_hint")

    def test_apply_display_tiers_mutates_all_events(self):
        rows = apply_display_tiers([
            {"public_category": "upcoming", "date": "2026-07-01"},
            {"public_category": "date_unknown"},
        ])

        self.assertEqual([row["display_tier"] for row in rows], ["confirmed", "season_hint"])


if __name__ == "__main__":
    unittest.main()
