import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WeeklyHarvestOperationsPolicyTest(unittest.TestCase):
    def test_weekly_cost_notion_apply_requires_manual_input(self):
        workflow = (ROOT / ".github" / "workflows" / "weekly_harvest.yml").read_text(encoding="utf-8")

        self.assertIn("sync_weekly_costs_to_notion", workflow)
        self.assertNotIn("run: python sync_weekly_costs.py --apply", workflow)
        self.assertIn('if [ "$SYNC_WEEKLY_COSTS_TO_NOTION" = "true" ]; then', workflow)
        self.assertIn('FLAGS="$FLAGS --apply"', workflow)

    def test_weekly_cost_markdown_report_is_committed(self):
        workflow = (ROOT / ".github" / "workflows" / "weekly_harvest.yml").read_text(encoding="utf-8")

        self.assertIn("python sync_weekly_costs.py $FLAGS", workflow)
        self.assertIn("git add data/weekly_cost_sync_result.json", workflow)
        self.assertIn("git add data/weekly_cost_sync_result.md", workflow)


if __name__ == "__main__":
    unittest.main()
