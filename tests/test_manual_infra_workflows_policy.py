import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ManualInfraWorkflowsPolicyTest(unittest.TestCase):
    def test_bootstrap_master_rdb_s3_requires_confirmation(self):
        workflow = (
            ROOT / ".github" / "workflows" / "bootstrap_master_rdb_s3.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertNotIn("push:", workflow)
        self.assertIn("confirm:", workflow)
        self.assertIn("BOOTSTRAP MASTER RDB S3", workflow)
        self.assertIn("Validate bootstrap confirmation", workflow)

    def test_verify_workflows_remain_manual_read_only_checks(self):
        for name, marker in (
            ("verify_master_rdb_s3.yml", "master_db_s3_artifact.py fetch"),
            ("verify-aws-queue.yml", "verify_aws_queues.py"),
        ):
            with self.subTest(name=name):
                workflow = (ROOT / ".github" / "workflows" / name).read_text(
                    encoding="utf-8"
                )
                self.assertIn("workflow_dispatch:", workflow)
                self.assertNotIn("schedule:", workflow)
                self.assertNotIn("push:", workflow)
                self.assertIn(marker, workflow)

    def test_manual_infra_runbook_and_inventory_are_updated(self):
        runbook = (ROOT / "docs" / "manual-infra-workflows.md").read_text(
            encoding="utf-8"
        )
        inventory = (
            ROOT / "docs" / "manual-auto-operations-inventory.md"
        ).read_text(encoding="utf-8")

        self.assertIn("自動化しない", runbook)
        self.assertIn("APPLY CUSTOM DOMAIN <domain>", runbook)
        self.assertIn("APPLY CONTACT FORM contact@bonsuke.jp", runbook)
        self.assertIn("APPLY WAF ERA76BJB7WLEN", runbook)
        self.assertIn("BOOTSTRAP MASTER RDB S3", runbook)
        self.assertIn("Manual infra workflows は手動維持に確定", inventory)
        self.assertIn("X candidate / social graph workflows", inventory)


if __name__ == "__main__":
    unittest.main()
