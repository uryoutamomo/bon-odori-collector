import unittest
from datetime import date

from sync_weekly_costs import (
    build_weekly_summary,
    format_week_label,
    render_markdown,
    week_start_for,
)


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

    def test_render_markdown_marks_dry_run_as_no_notion_write(self):
        summary = build_weekly_summary({"2026-06-08": 0.1}, date(2026, 6, 8))
        markdown = render_markdown(
            {
                **summary,
                "database_id": "cost-db",
                "database_source": "configured",
                "schema_changed": False,
                "title_property": "名前",
                "action": "update",
                "page_id": "page-id",
                "applied": False,
            }
        )

        self.assertIn("- mode: dry-run", markdown)
        self.assertIn("- notion_write: no", markdown)
        self.assertIn("sync_weekly_costs_to_notion=true", markdown)

    def test_render_markdown_marks_apply_as_notion_write(self):
        summary = build_weekly_summary({"2026-06-08": 0.1}, date(2026, 6, 8))
        markdown = render_markdown(
            {
                **summary,
                "database_id": "cost-db",
                "database_source": "configured",
                "schema_changed": False,
                "title_property": "名前",
                "action": "update",
                "page_id": "page-id",
                "applied": True,
            }
        )

        self.assertIn("- mode: applied", markdown)
        self.assertIn("- notion_write: yes", markdown)


if __name__ == "__main__":
    unittest.main()
