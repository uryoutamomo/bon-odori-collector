import unittest
from pathlib import Path

from manual_apply_guards import NOTION_WORKLOG_MAINTENANCE_CONFIRMATION


ROOT = Path(__file__).resolve().parents[1]


class NotionWorklogMaintenancePolicyTest(unittest.TestCase):
    def test_task_and_page_maintenance_scripts_require_confirmation(self):
        scripts = [
            "close_youtube_notion_task_checkboxes.py",
            "update_youtube_notion_progress.py",
            "update_youtube_followup_progress.py",
            "create_current_work_index_notion.py",
            "add_current_work_to_first_look_notion.py",
            "rename_current_work_first_look_link_notion.py",
            "create_current_location_notion.py",
            "legacy/notion-notes/append_youtube_task_list_to_notion.py",
        ]

        for filename in scripts:
            with self.subTest(filename=filename):
                script = (ROOT / filename).read_text(encoding="utf-8")
                self.assertIn('parser.add_argument("--confirm"', script)
                self.assertIn("require_confirmation", script)
                self.assertIn("NOTION_WORKLOG_MAINTENANCE_CONFIRMATION", script)

    def test_append_notes_are_documented_as_lightweight_manual_logs(self):
        runbook = (
            ROOT / "docs" / "notion-worklog-maintenance-operations.md"
        ).read_text(encoding="utf-8")

        self.assertIn("Lightweight Work-Log Appenders", runbook)
        self.assertIn("append_*_note.py", runbook)
        self.assertIn(NOTION_WORKLOG_MAINTENANCE_CONFIRMATION, runbook)

    def test_inventory_and_policy_document_boundary(self):
        inventory = (
            ROOT / "docs" / "manual-auto-operations-inventory.md"
        ).read_text(encoding="utf-8")
        notion_policy = (ROOT / "docs" / "notion-usage-policy.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("Notion work-log / task-page maintenance scripts", inventory)
        self.assertIn("New automation proposal review", inventory)
        self.assertIn("Schedule Notion work-log / task-page maintenance scripts", notion_policy)


if __name__ == "__main__":
    unittest.main()
