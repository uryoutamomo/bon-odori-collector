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

    def test_workflow_surfaces_run_reports_in_step_summary(self):
        text = (ROOT / ".github" / "workflows" / "youtube_daily_backfill.yml").read_text(encoding="utf-8")

        self.assertIn("data/youtube_daily_backfill_report.md", text)
        self.assertIn("data/ops_metrics_latest.md", text)
        self.assertIn("GITHUB_STEP_SUMMARY", text)
        self.assertIn("YouTube日次バックフィル詳細", text)
        self.assertIn("運用メトリクス最新", text)

    def test_workflow_commits_results_to_main_without_pull_request(self):
        # 自動PR方式では、PRが閉じられた後も `gh pr view <branch>` が closed PR に
        # ヒットして本文を書き換え続けるため、日次の成果が main へ届かないまま
        # 約1か月捨てられていた(2026-06-30〜2026-07-24)。再発防止として
        # PR経由をやめ、collect.yml と同じく main へ直接コミットする。
        text = (ROOT / ".github" / "workflows" / "youtube_daily_backfill.yml").read_text(encoding="utf-8")

        self.assertIn("git push origin HEAD:main", text)
        self.assertNotIn("gh pr create", text)
        self.assertNotIn("gh pr edit", text)
        self.assertNotIn("git checkout -B automation/youtube-daily-backfill", text)

    def test_workflow_does_not_stage_public_event_json(self):
        # このジョブの export は observed 層の unmatched 行を公開JSONへ流し込むため、
        # main へ入れると sync-public-data の定時実行がそのまま本番公開してしまう。
        # 公開JSONは collect.yml が RDB(curated層)から生成するものを正本とする。
        text = (ROOT / ".github" / "workflows" / "youtube_daily_backfill.yml").read_text(encoding="utf-8")

        self.assertNotIn("git add data/public/events_public.json", text)
        self.assertNotIn("git add data/public/events_public.js", text)


if __name__ == "__main__":
    unittest.main()
