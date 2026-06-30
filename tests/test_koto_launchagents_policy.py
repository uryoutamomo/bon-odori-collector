import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KOTO_LABELS = [
    "com.koto.bon-odori-breaking-news",
    "com.koto.bon-odori-calendar-sync",
    "com.koto.bon-odori-evening-news",
    "com.koto.bon-odori-home-venue-watch",
    "com.koto.bon-odori-watchdog",
]


class KotoLaunchAgentsPolicyTest(unittest.TestCase):
    def test_koto_runbook_lists_all_launchagents_as_disabled(self):
        doc = (ROOT / "docs" / "koto-launchagents-operations.md").read_text(
            encoding="utf-8"
        )

        for label in KOTO_LABELS:
            self.assertIn(f"{label}.plist.disabled", doc)
        self.assertIn("Do not rename any `.plist.disabled` file back to `.plist`", doc)

    def test_inventory_does_not_list_active_koto_plist_rows(self):
        doc = (ROOT / "docs" / "manual-auto-operations-inventory.md").read_text(
            encoding="utf-8"
        )

        for label in KOTO_LABELS:
            self.assertIn(f"{label}.plist.disabled", doc)
            active_row = re.compile(rf"`{re.escape(label)}\.plist`\s*\|")
            self.assertIsNone(active_row.search(doc))

    def test_notion_policy_blocks_hidden_koto_write_paths(self):
        doc = (ROOT / "docs" / "notion-usage-policy.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("`com.koto.*` LaunchAgents are disabled", doc)
        self.assertIn("hidden Notion/GitHub write paths", doc)


if __name__ == "__main__":
    unittest.main()
