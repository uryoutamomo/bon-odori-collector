import unittest

from public_json_postprocessors.compare_event_state_axes import compare_events


class CompareEventStateAxesTest(unittest.TestCase):
    def test_legacy_unconfirmed_value_normalizes_without_display_diff(self):
        report = compare_events([
            {
                "name": "例",
                "venue": "会場",
                "public_category": "recurring_last_year",
                "display_tier": "historical_reference",
                "current_event_state": "unconfirmed",
                "date_certainty_tier": "historical_reference",
                "historical_reference": {"date": "2025-08-01"},
            }
        ])
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["axis_pair_counts"][0]["current_event_state"], "predicted")

    def test_reports_legacy_projection_mismatch(self):
        report = compare_events([
            {
                "name": "例",
                "venue": "会場",
                "public_category": "upcoming",
                "display_tier": "season_hint",
                "current_event_state": "confirmed",
                "date_certainty_tier": "confirmed",
                "date": "2026-08-01",
            }
        ])
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["mismatch_count"], 1)

    def test_explicit_target_year_drives_legacy_axis_comparison(self):
        report = compare_events(
            [{
                "name": "例",
                "venue": "会場",
                "public_category": "upcoming",
                "display_tier": "confirmed",
                "current_event_state": "confirmed",
                "date_certainty_tier": "confirmed",
                "date": "2027-08-01",
            }],
            target_year=2027,
        )
        self.assertEqual(report["status"], "pass")


if __name__ == "__main__":
    unittest.main()
