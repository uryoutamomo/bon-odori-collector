import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LocalSiteServerPolicyTest(unittest.TestCase):
    def test_runbook_documents_manual_localhost_server(self):
        doc = (ROOT / "docs" / "local-site-server-operations.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("com.oto.bon-odori-site.plist.disabled", doc)
        self.assertIn("python3 -m http.server 8642 --bind 127.0.0.1", doc)
        self.assertIn("not part of the production deploy path", doc)

    def test_inventory_lists_site_launchagent_as_disabled(self):
        doc = (ROOT / "docs" / "manual-auto-operations-inventory.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("com.oto.bon-odori-site.plist.disabled", doc)
        self.assertIn("--bind 127.0.0.1", doc)
        active_row = re.compile(r"`com\.oto\.bon-odori-site\.plist`\s*\|")
        self.assertIsNone(active_row.search(doc))


if __name__ == "__main__":
    unittest.main()
