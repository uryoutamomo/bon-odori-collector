import plistlib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class YouTubeDailyOperationsPolicyTest(unittest.TestCase):
    def test_local_launchagent_template_is_manual_only(self):
        plist_path = ROOT / "ops" / "com.ryotauchida.bon-odori.youtube-daily.plist"
        with plist_path.open("rb") as handle:
            plist = plistlib.load(handle)

        self.assertNotIn("StartCalendarInterval", plist)
        self.assertFalse(plist.get("RunAtLoad", False))

        args = plist.get("ProgramArguments") or []
        self.assertIn("--max-batches", args)
        self.assertEqual(args[args.index("--max-batches") + 1], "1")
        self.assertNotIn("--commit", args)
        self.assertNotIn("--push", args)
        self.assertNotIn("--open-dashboard", args)

    def test_runbook_names_github_actions_as_automatic_owner(self):
        text = (ROOT / "docs" / "youtube-daily-operations.md").read_text(encoding="utf-8")

        self.assertIn("GitHub Actions is the only automatic scheduler", text)
        self.assertIn("youtube_daily_backfill.yml", text)
        self.assertIn("plist.disabled", text)

    def test_workflow_surfaces_run_reports_in_summary_and_pr_body(self):
        text = (ROOT / ".github" / "workflows" / "youtube_daily_backfill.yml").read_text(encoding="utf-8")

        self.assertIn("data/youtube_daily_backfill_report.md", text)
        self.assertIn("data/ops_metrics_latest.md", text)
        self.assertIn("GITHUB_STEP_SUMMARY", text)
        self.assertIn("REPORT_SUMMARY", text)
        self.assertIn("OPS_SUMMARY", text)
        self.assertIn("Latest run summary", text)
        self.assertIn("Latest operations metrics", text)


if __name__ == "__main__":
    unittest.main()
