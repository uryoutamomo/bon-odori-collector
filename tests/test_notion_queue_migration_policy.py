import unittest
from pathlib import Path

import migrate_notion_queue_to_dynamodb as migration


ROOT = Path(__file__).resolve().parents[1]


class NotionQueueMigrationPolicyTest(unittest.TestCase):
    def test_workflow_is_manual_dry_run_by_default(self):
        workflow = (
            ROOT / ".github" / "workflows" / "migrate_notion_queue_to_dynamodb.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertNotIn("push:", workflow)
        self.assertIn('default: "false"', workflow)
        self.assertIn("confirm:", workflow)
        self.assertIn("Dry-run mode; no confirmation required.", workflow)

    def test_workflow_requires_confirmation_for_apply(self):
        workflow = (
            ROOT / ".github" / "workflows" / "migrate_notion_queue_to_dynamodb.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("MIGRATE NOTION QUEUE TO DYNAMODB", workflow)
        self.assertIn("Validate migration confirmation", workflow)
        self.assertIn("--apply --confirm", workflow)
        self.assertIn("writes Notion queue rows into DynamoDB", workflow)

    def test_local_script_requires_confirmation_for_apply(self):
        migration.validate_apply_confirmation(False, "")

        with self.assertRaises(ValueError):
            migration.validate_apply_confirmation(True, "")

        migration.validate_apply_confirmation(
            True,
            "MIGRATE NOTION QUEUE TO DYNAMODB",
        )

    def test_runbook_inventory_and_policy_document_boundary(self):
        runbook = (ROOT / "docs" / "notion-queue-migration-operations.md").read_text(
            encoding="utf-8"
        )
        inventory = (
            ROOT / "docs" / "manual-auto-operations-inventory.md"
        ).read_text(encoding="utf-8")
        notion_policy = (ROOT / "docs" / "notion-usage-policy.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("Keep it manual and normally unused", runbook)
        self.assertIn("MIGRATE NOTION QUEUE TO DYNAMODB", runbook)
        self.assertIn("Do not schedule this workflow", runbook)
        self.assertIn("Notion queue migration は legacy one-off", inventory)
        self.assertIn("Master RDB -> Notion sync scripts", inventory)
        self.assertIn("Legacy Notion queue migration boundary", notion_policy)


if __name__ == "__main__":
    unittest.main()
