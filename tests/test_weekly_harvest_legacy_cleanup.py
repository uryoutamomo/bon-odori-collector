import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/weekly_harvest.yml"


class WeeklyHarvestLegacyCleanupTest(unittest.TestCase):
    def test_workflow_keeps_harvest_but_has_no_legacy_review_writer(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("python build_weekly_harvest_candidates.py", workflow)
        self.assertIn("python prepare_weekly_harvest_review.py", workflow)
        self.assertIn("python export_public_events.py", workflow)
        self.assertNotIn("build_keyboard_review_ui.py", workflow)
        self.assertNotIn("apply_reviewed", workflow)
        self.assertNotIn("apply_weekly_song_review_decisions.py", workflow)
        self.assertNotIn("apply_weekly_harvest_human13_decisions.py", workflow)
        self.assertNotIn("git add data/weekly_harvest_review_candidates.json", workflow)
        self.assertNotIn("git add data/weekly_song_candidates_review.json", workflow)
        self.assertNotIn("weekly_harvest_review_ui.html", workflow)
        self.assertNotIn("weekly_song_candidates_review_ui.html", workflow)


if __name__ == "__main__":
    unittest.main()
