import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CollectYouTubeAggregateInboxWiringTest(unittest.TestCase):
    def test_wiring_is_default_off_and_keeps_fresh_uncommitted_adapter_input(self):
        workflow = (ROOT / ".github/workflows/collect.yml").read_text(encoding="utf-8")
        builder = "python build_youtube_active_video_review.py --max-per-channel 10000"
        year_builder = "python build_youtube_year_backfill_review_queue.py"
        runner = "python run_review_inbox_youtube_scheduled.py"

        self.assertIn("vars.REVIEW_INBOX_YOUTUBE_AGGREGATE_DUAL_WRITE_ENABLED == 'true'", workflow)
        self.assertIn(builder, workflow)
        self.assertIn(year_builder, workflow)
        self.assertNotIn("git add -f data/youtube_active_video_review.json", workflow)
        self.assertNotIn("git add -f data/youtube_active_video_review.md", workflow)
        self.assertNotIn("git add -f data/youtube_year_backfill_review_queue.json", workflow)
        self.assertNotIn("git add -f data/youtube_year_backfill_review_queue.md", workflow)
        self.assertIn("REVIEW_INBOX_YOUTUBE_AGGREGATE_SCHEDULED_ENABLED: 'true'", workflow)
        self.assertIn("REVIEW_INBOX_DUAL_WRITE_MODE: bulk", workflow)
        self.assertIn("REVIEW_INBOX_CAS_PUBLISH_ENABLED: 'true'", workflow)
        self.assertIn("REVIEW_INBOX_READER_MODE: inbox", workflow)
        self.assertIn("REVIEW_INBOX_LEGACY_WRITER_ENABLED: 'false'", workflow)
        self.assertIn(runner, workflow)
        self.assertNotIn("python run_review_inbox_youtube_active_scheduled.py", workflow)
        self.assertNotIn("vars.REVIEW_INBOX_YOUTUBE_ACTIVE_DUAL_WRITE_ENABLED", workflow)
        self.assertIn("--user-input data/youtube_user_confirmation_queue.json", workflow)
        self.assertLess(workflow.index(builder), workflow.index(runner))

    def test_main_collect_and_adapter_inputs_precede_dual_write(self):
        workflow = (ROOT / ".github/workflows/collect.yml").read_text(encoding="utf-8")
        main_commit = workflow.index("- name: Commit and Push changes")
        legacy_build = workflow.index("- name: Build YouTube review-inbox adapter inputs")
        dual_write = workflow.index("- name: Dual-write complete YouTube aggregate to review inbox")
        projection = workflow.index("- name: Commit YouTube aggregate inbox projection")
        evidence = workflow.index("- name: Upload YouTube aggregate inbox evidence")

        self.assertLess(main_commit, legacy_build)
        self.assertLess(legacy_build, dual_write)
        self.assertLess(dual_write, projection)
        self.assertLess(projection, evidence)
        self.assertIn("if: ${{ always()", workflow[evidence:])

    def test_wiring_exports_rend_without_force(self):
        workflow = (ROOT / ".github/workflows/collect.yml").read_text(encoding="utf-8")

        self.assertIn("python master_db_s3_artifact.py fetch --overwrite", workflow)
        self.assertIn("python review_inbox.py --out-json data/review_inbox.json", workflow)
        self.assertIn("steps.youtube_aggregate_inbox.outputs.ran == 'true'", workflow)
        self.assertNotIn("master_db_s3_artifact.py publish --force", workflow)
        self.assertIn("REVIEW_INBOX_LEGACY_WRITER_ENABLED: 'false'", workflow)


if __name__ == "__main__":
    unittest.main()
