import unittest
from datetime import date

from sync_weekly_costs import build_weekly_summary, format_week_label, week_start_for


class SyncWeeklyCostsTest(unittest.TestCase):
    def test_uses_monday_week_label(self):
        self.assertEqual(week_start_for(date(2026, 6, 11)), date(2026, 6, 8))
        self.assertEqual(format_week_label(date(2026, 6, 8)), "2026-06-08週")

    def test_builds_weekly_summary_with_zero_fixed_services(self):
        summary = build_weekly_summary(
            {
                "2026-06-08": 0.1,
                "2026-06-09": 0.2,
                "2026-06-11": 0.3,
                "2026-06-15": 9.0,
            },
            date(2026, 6, 8),
        )

        self.assertEqual(summary["period"], "2026-06-08週")
        self.assertEqual(summary["week_end"], "2026-06-14")
        self.assertEqual(summary["twitterapi_io"], 0.6)
        self.assertEqual(summary["github_actions"], 0.0)
        self.assertEqual(summary["notion"], 0.0)
        self.assertEqual(summary["gmail_smtp"], 0.0)
        self.assertEqual(summary["total"], 0.6)


if __name__ == "__main__":
    unittest.main()
