import unittest
from pathlib import Path

from manual_apply_guards import require_confirmation


ROOT = Path(__file__).resolve().parents[1]
LEGACY_NOTION_WRITES = ROOT / "legacy" / "notion_writes"


class LegacyNotionWritebackPolicyTest(unittest.TestCase):
    def test_shared_confirmation_guard(self):
        require_confirmation(False, "", "PHRASE", "demo")

        with self.assertRaises(ValueError):
            require_confirmation(True, "", "PHRASE", "demo")

        require_confirmation(True, "PHRASE", "PHRASE", "demo")

    def test_sync_master_to_notion_is_frozen_break_glass_only(self):
        script = (LEGACY_NOTION_WRITES / "sync_master_to_notion.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("FROZEN_WRITEBACK_MESSAGE", script)
        self.assertIn("allow_frozen_notion_write", script)
        self.assertIn("APPLY RDB TO NOTION", script)
        self.assertIn("--apply refuses rdb_to_notion_dry_run jobs", script)

    def test_legacy_notion_apply_scripts_require_confirmation(self):
        expectations = {
            "sync_fixed_date_rules_to_notion.py": "APPLY FIXED DATE RULES TO NOTION",
            "promote_event_dates.py": "APPLY EVENT DATES TO NOTION",
            "classify_x_members.py": "APPLY X MEMBER CLASSIFICATION TO NOTION",
            "sync_x_display_names.py": "APPLY X DISPLAY NAMES TO NOTION",
        }

        for filename, phrase in expectations.items():
            with self.subTest(filename=filename):
                script = (LEGACY_NOTION_WRITES / filename).read_text(encoding="utf-8")
                self.assertIn("require_confirmation", script)
                self.assertIn('parser.add_argument("--confirm"', script)
                self.assertIn(phrase, script)

    def test_runbook_inventory_and_policy_document_boundary(self):
        runbook = (ROOT / "docs" / "legacy-notion-writeback-operations.md").read_text(
            encoding="utf-8"
        )
        inventory = (
            ROOT / "docs" / "manual-auto-operations-inventory.md"
        ).read_text(encoding="utf-8")
        notion_policy = (ROOT / "docs" / "notion-usage-policy.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("Do not automate Master RDB -> Notion write-back", runbook)
        self.assertIn("APPLY RDB TO NOTION", runbook)
        self.assertIn("APPLY EVENT DATES TO NOTION", runbook)
        self.assertIn("APPLY X DISPLAY NAMES TO NOTION", runbook)
        self.assertIn("Master RDB -> Notion sync scripts は手動維持に確定", inventory)
        self.assertIn("YouTube / retrospective direct Notion apply scripts", inventory)
        self.assertIn("Legacy Notion write-back boundary", notion_policy)


if __name__ == "__main__":
    unittest.main()
