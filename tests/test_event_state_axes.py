import unittest

from event_state_axes import (
    EventStateAxesError,
    axes_from_legacy_public_event,
    legacy_public_fields_from_axes,
    validate_event_state_axes,
)


class EventStateAxesTest(unittest.TestCase):
    def test_rejects_non_orthogonal_combinations(self):
        with self.assertRaises(EventStateAxesError):
            validate_event_state_axes("predicted", "confirmed")
        with self.assertRaises(EventStateAxesError):
            validate_event_state_axes("confirmed", "season_hint")

    def test_normalizes_unconfirmed_historical_event_to_predicted(self):
        axes = axes_from_legacy_public_event({
            "public_category": "recurring_last_year",
            "historical_reference": {"date": "2025-07-20"},
        })
        self.assertEqual(axes["current_event_state"], "predicted")
        self.assertEqual(axes["date_certainty_tier"], "historical_reference")

    def test_round_trip_preserves_legacy_card_classification(self):
        cases = [
            ({"public_category": "upcoming", "date": "2026-08-01"}, ("upcoming", "confirmed")),
            ({"public_category": "ended", "date": "2026-06-01"}, ("ended", "ended")),
            ({"public_category": "recurring_last_year", "date_prediction": {"date": "2026-08-01"}}, ("recurring_last_year", "rule_predicted")),
            ({"public_category": "recurring_last_year", "historical_slide": {"date": "2026-08-01"}}, ("recurring_last_year", "historical_slide")),
            ({"public_category": "date_unknown", "season_hint": {"months": [8]}}, ("date_unknown", "season_hint")),
            ({"public_category": "recurring_last_year", "historical_reference": {"date": "2025-08-01"}}, ("recurring_last_year", "historical_reference")),
        ]
        for event, expected in cases:
            with self.subTest(event=event):
                axes = axes_from_legacy_public_event(event)
                legacy = legacy_public_fields_from_axes(
                    axes["current_event_state"], axes["date_certainty_tier"]
                )
                self.assertEqual((legacy["public_category"], legacy["display_tier"]), expected)

    def test_announced_without_confirmed_date_uses_date_unknown_compatibility(self):
        legacy = legacy_public_fields_from_axes("announced", "season_hint")
        self.assertEqual(legacy["public_category"], "date_unknown")
        self.assertEqual(legacy["display_tier"], "season_hint")

    def test_legacy_backfill_is_intentionally_lossy_for_non_target_year_upcoming(self):
        axes = axes_from_legacy_public_event({
            "public_category": "upcoming",
            "date": "2025-08-01",
        })
        self.assertEqual(axes, {
            "current_event_state": "announced",
            "date_certainty_tier": "season_hint",
        })
        self.assertEqual(
            legacy_public_fields_from_axes(
                axes["current_event_state"], axes["date_certainty_tier"]
            ),
            {"public_category": "date_unknown", "display_tier": "season_hint"},
        )


if __name__ == "__main__":
    unittest.main()
