import unittest

from public_json_postprocessors.apply_public_display_tiers import (
    apply_display_tiers,
    apply_legacy_public_fields_from_axes,
    current_event_state_for_event,
    date_certainty_tier_for_event,
    display_tier_for_event,
)


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
        self.assertEqual([row["current_event_state"] for row in rows], ["confirmed", "predicted"])
        self.assertEqual([row["date_certainty_tier"] for row in rows], ["confirmed", "season_hint"])

    def test_state_axes_separate_current_state_from_certainty(self):
        self.assertEqual(
            current_event_state_for_event({"public_category": "recurring_last_year", "historical_reference": {}}),
            "predicted",
        )
        self.assertEqual(
            date_certainty_tier_for_event({"public_category": "recurring_last_year", "historical_reference": {}}),
            "historical_reference",
        )
        self.assertEqual(
            current_event_state_for_event({"public_category": "recurring_last_year", "date_prediction": {"date": "2026-07-31"}}),
            "predicted",
        )
        self.assertEqual(
            date_certainty_tier_for_event({"public_category": "recurring_last_year", "date_prediction": {"date": "2026-07-31"}}),
            "rule_predicted",
        )
        self.assertEqual(
            current_event_state_for_event({"public_category": "upcoming"}),
            "announced",
        )

    def test_legacy_fields_are_projected_from_axes(self):
        rows = apply_legacy_public_fields_from_axes([
            {"current_event_state": "confirmed", "date_certainty_tier": "confirmed"},
            {"current_event_state": "ended", "date_certainty_tier": "confirmed"},
            {"current_event_state": "predicted", "date_certainty_tier": "historical_slide"},
            {"current_event_state": "announced", "date_certainty_tier": "season_hint"},
        ])

        self.assertEqual(
            [(row["public_category"], row["display_tier"]) for row in rows],
            [
                ("upcoming", "confirmed"),
                ("ended", "ended"),
                ("recurring_last_year", "historical_slide"),
                ("date_unknown", "season_hint"),
            ],
        )

    def test_prefer_existing_axes_does_not_reverse_derive_from_legacy_fields(self):
        rows = apply_display_tiers([
            {
                "current_event_state": "ended",
                "date_certainty_tier": "confirmed",
                "public_category": "upcoming",
                "display_tier": "confirmed",
            }
        ], prefer_existing_axes=True)
        self.assertEqual(rows[0]["public_category"], "ended")
        self.assertEqual(rows[0]["display_tier"], "ended")

    def test_target_year_is_not_fixed_to_2026(self):
        rows = apply_display_tiers(
            [
                {"public_category": "upcoming", "date": "2027-07-01"},
                {"public_category": "upcoming", "date": "2026-07-01"},
            ],
            target_year=2027,
        )
        self.assertEqual(
            [row["current_event_state"] for row in rows],
            ["confirmed", "announced"],
        )
        self.assertEqual(
            [row["date_certainty_tier"] for row in rows],
            ["confirmed", "season_hint"],
        )


if __name__ == "__main__":
    unittest.main()
