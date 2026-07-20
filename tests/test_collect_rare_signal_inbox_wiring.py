import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CollectRareSignalInboxWiringTest(unittest.TestCase):
    def test_wiring_is_default_off_and_uses_uncommitted_adapter_input(self):
        workflow = (ROOT / ".github/workflows/collect.yml").read_text(encoding="utf-8")
        legacy = "python build_rare_signal_backcheck_queue.py"
        runner = "python run_review_inbox_rare_signal_scheduled.py"

        self.assertIn(legacy, workflow)
        self.assertIn("rare-signal-backcheck-built", workflow)
        self.assertIn("vars.REVIEW_INBOX_RARE_SIGNAL_DUAL_WRITE_ENABLED == 'true'", workflow)
        self.assertIn("REVIEW_INBOX_RARE_SIGNAL_SCHEDULED_ENABLED: 'true'", workflow)
        self.assertIn("REVIEW_INBOX_DUAL_WRITE_MODE: bulk", workflow)
        self.assertIn("REVIEW_INBOX_CAS_PUBLISH_ENABLED: 'true'", workflow)
        self.assertIn("REVIEW_INBOX_READER_MODE: inbox", workflow)
        self.assertIn("REVIEW_INBOX_LEGACY_WRITER_ENABLED: 'false'", workflow)
        self.assertNotIn("git add -f data/rare_signal_backcheck_queue.json", workflow)
        self.assertIn(runner, workflow)
        self.assertLess(workflow.index(legacy), workflow.index(runner))
        self.assertLess(workflow.index("- name: Commit and Push changes"), workflow.index(runner))

    def test_wiring_exports_rend_without_force(self):
        workflow = (ROOT / ".github/workflows/collect.yml").read_text(encoding="utf-8")

        self.assertIn("python master_db_s3_artifact.py fetch --overwrite", workflow)
        self.assertIn("python review_inbox.py --out-json data/review_inbox.json", workflow)
        self.assertIn("git add -f data/review_inbox.json", workflow)
        self.assertIn("steps.rare_signal_inbox.outputs.ran == 'true'", workflow)
        self.assertNotIn("master_db_s3_artifact.py publish --force", workflow)
        self.assertIn("REVIEW_INBOX_LEGACY_WRITER_ENABLED: 'false'", workflow)

    def test_dual_write_failure_does_not_block_the_main_collect_commit(self):
        workflow = (ROOT / ".github/workflows/collect.yml").read_text(encoding="utf-8")
        main_commit = workflow.index("- name: Commit and Push changes")
        dual_write = workflow.index("- name: Dual-write rare signal queue to review inbox")
        projection_commit = workflow.index("- name: Commit rare signal inbox projection")
        evidence_upload = workflow.index("- name: Upload rare signal inbox evidence")

        self.assertLess(main_commit, dual_write)
        self.assertLess(dual_write, projection_commit)
        self.assertLess(projection_commit, evidence_upload)
        self.assertIn("if: ${{ always()", workflow[evidence_upload:])


if __name__ == "__main__":
    unittest.main()
