import unittest
from pathlib import Path

from manual_apply_guards import MASTER_RDB_ONE_OFF_CONFIRMATION


ROOT = Path(__file__).resolve().parents[1]


class BuildExportReportOperationsPolicyTest(unittest.TestCase):
    def test_derived_table_rebuilders_require_confirmation(self):
        scripts = [
            "promotion_candidates/build_historical_promotion_candidates.py",
            "promotion_candidates/build_registered_event_investigation_queue.py",
        ]

        for filename in scripts:
            with self.subTest(filename=filename):
                script = (ROOT / filename).read_text(encoding="utf-8")
                self.assertIn('parser.add_argument("--confirm"', script)
                self.assertIn("require_confirmation", script)
                self.assertIn("MASTER_RDB_ONE_OFF_CONFIRMATION", script)

    def test_scheduled_export_and_audit_steps_remain_automatic(self):
        collect = (ROOT / ".github" / "workflows" / "collect.yml").read_text(
            encoding="utf-8"
        )
        weekly = (ROOT / ".github" / "workflows" / "weekly_harvest.yml").read_text(
            encoding="utf-8"
        )
        youtube = (
            ROOT / ".github" / "workflows" / "youtube_daily_backfill.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("python audit_master_rdb.py", collect)
        self.assertIn("python export_public_events.py", collect)
        self.assertIn("python build_glossary_runtime.py", collect)
        self.assertIn("python audit_master_rdb.py", weekly)
        self.assertIn("python export_public_events.py", weekly)
        self.assertIn("python audit_master_rdb.py", youtube)

    def test_runbook_and_inventory_document_boundary(self):
        runbook = (ROOT / "docs" / "build-export-report-operations.md").read_text(
            encoding="utf-8"
        )
        inventory = (
            ROOT / "docs" / "manual-auto-operations-inventory.md"
        ).read_text(encoding="utf-8")

        self.assertIn("Automatic / Safe Generated Outputs", runbook)
        self.assertIn(MASTER_RDB_ONE_OFF_CONFIRMATION, runbook)
        self.assertIn("Do not add schedules around derived-table rebuilds", runbook)
        self.assertIn("Build / export / report scripts", inventory)
        self.assertIn("Notion work-log / task-page maintenance scripts", inventory)


if __name__ == "__main__":
    unittest.main()
