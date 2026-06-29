import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class XCandidateWorkflowsPolicyTest(unittest.TestCase):
    def workflow(self, name):
        return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")

    def test_x_candidate_workflows_are_manual_only(self):
        for name in (
            "review_x_candidate_posts.yml",
            "discover_x_social_graph.yml",
        ):
            with self.subTest(name=name):
                workflow = self.workflow(name)
                self.assertIn("workflow_dispatch:", workflow)
                self.assertNotIn("schedule:", workflow)
                self.assertNotIn("push:", workflow)

    def test_review_workflow_separates_x_api_review_and_notion_sync(self):
        workflow = self.workflow("review_x_candidate_posts.yml")

        self.assertIn("sync_only:", workflow)
        self.assertIn("confirm:", workflow)
        self.assertIn("REVIEW X CANDIDATES", workflow)
        self.assertIn("SYNC APPROVED X MEMBERS", workflow)
        self.assertIn("TWITTERAPI_IO_KEY", workflow)
        self.assertIn("python review_x_candidate_posts.py", workflow)
        self.assertIn("python sync_x_promoted_members.py", workflow)
        self.assertIn("spends X API quota or writes approved members to Notion", workflow)

    def test_social_graph_workflow_requires_quota_confirmation(self):
        workflow = self.workflow("discover_x_social_graph.yml")

        self.assertIn("confirm:", workflow)
        self.assertIn("DISCOVER X SOCIAL GRAPH", workflow)
        self.assertIn("TWITTERAPI_IO_KEY", workflow)
        self.assertIn("python discover_x_social_graph.py", workflow)
        self.assertIn("spends X API quota to explore follow graph candidates", workflow)

    def test_runbook_and_inventory_document_boundaries(self):
        runbook = (ROOT / "docs" / "x-candidate-workflows-operations.md").read_text(
            encoding="utf-8"
        )
        inventory = (
            ROOT / "docs" / "manual-auto-operations-inventory.md"
        ).read_text(encoding="utf-8")

        self.assertIn("Keep these workflows manual", runbook)
        self.assertIn("DISCOVER X SOCIAL GRAPH", runbook)
        self.assertIn("REVIEW X CANDIDATES", runbook)
        self.assertIn("SYNC APPROVED X MEMBERS", runbook)
        self.assertIn("Do not add `schedule` or `push` triggers", runbook)
        self.assertIn("X candidate / social graph workflows は手動維持に確定", inventory)
        self.assertIn("Notion queue migration", inventory)


if __name__ == "__main__":
    unittest.main()
