import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LocalGlossaryManualPolicyTest(unittest.TestCase):
    def test_launchagent_template_has_no_schedule(self):
        plist = (
            ROOT
            / "ops"
            / "com.ryotauchida.bon-odori.glossary-manual.plist"
        ).read_text(encoding="utf-8")

        self.assertIn("<key>Disabled</key>", plist)
        self.assertIn("<true/>", plist)
        self.assertNotIn("StartCalendarInterval", plist)
        self.assertIn("<string>--manual</string>", plist)

    def test_local_runner_requires_manual_flag(self):
        result = subprocess.run(
            [sys.executable, "run_manual_glossary_review.py", "--days", "7"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--manual", result.stderr)

    def test_runbook_documents_daily_owner_and_manual_review(self):
        doc = (ROOT / "docs" / "local-glossary-manual-operations.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("daily `collect.yml` flow", doc)
        self.assertIn("Human review of generated song/glossary queues", doc)
        self.assertIn("python3 run_manual_glossary_review.py --manual --days 3", doc)
        self.assertIn("StartCalendarInterval` is absent", doc)


if __name__ == "__main__":
    unittest.main()
