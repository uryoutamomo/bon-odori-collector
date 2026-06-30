import unittest
from pathlib import Path

from manual_apply_guards import LEGACY_YOUTUBE_NOTION_CONFIRMATION


ROOT = Path(__file__).resolve().parents[1]


class LegacyYoutubeNotionApplyPolicyTest(unittest.TestCase):
    def test_scripts_require_shared_confirmation_for_apply(self):
        scripts = [
            "apply_youtube_existing_event_updates.py",
            "apply_youtube_active_existing_event_updates.py",
            "apply_youtube_2025_official_candidate_existing_updates.py",
            "apply_youtube_review_video_evidence.py",
            "apply_youtube_official_confirmation.py",
            "apply_youtube_2025_date_backfill.py",
            "apply_youtube_2025_curated_official_candidates.py",
            "apply_youtube_2025_koto_ready_events.py",
            "apply_retrospective_ready_venue_events.py",
            "apply_retrospective_existing_event_updates.py",
            "apply_youtube_blocked_new_events.py",
            "apply_youtube_reviewed_new_events.py",
        ]

        for filename in scripts:
            with self.subTest(filename=filename):
                script = (ROOT / filename).read_text(encoding="utf-8")
                self.assertIn("--apply", script)
                self.assertIn('parser.add_argument("--confirm"', script)
                self.assertIn("require_confirmation", script)
                self.assertIn("LEGACY_YOUTUBE_NOTION_CONFIRMATION", script)

    def test_runbook_inventory_and_policy_document_boundary(self):
        runbook = (
            ROOT / "docs" / "legacy-youtube-notion-apply-operations.md"
        ).read_text(encoding="utf-8")
        inventory = (
            ROOT / "docs" / "manual-auto-operations-inventory.md"
        ).read_text(encoding="utf-8")
        notion_policy = (ROOT / "docs" / "notion-usage-policy.md").read_text(
            encoding="utf-8"
        )
        legacy_writeback = (
            ROOT / "docs" / "legacy-notion-writeback-operations.md"
        ).read_text(encoding="utf-8")

        self.assertIn("Do not automate these direct Notion apply scripts", runbook)
        self.assertIn(LEGACY_YOUTUBE_NOTION_CONFIRMATION, runbook)
        self.assertIn("Do not add cron, LaunchAgent, or scheduled GitHub Actions", runbook)
        self.assertIn("YouTube / retrospective direct Notion apply scripts", inventory)
        self.assertIn(LEGACY_YOUTUBE_NOTION_CONFIRMATION, inventory)
        self.assertIn("Schedule YouTube / retrospective direct Notion apply scripts", notion_policy)
        self.assertIn("legacy-youtube-notion-apply-operations.md", legacy_writeback)


if __name__ == "__main__":
    unittest.main()
