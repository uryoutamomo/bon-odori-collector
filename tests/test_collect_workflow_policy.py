import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CollectWorkflowPolicyTest(unittest.TestCase):
    def test_collect_notion_writes_are_manual_opt_in(self):
        workflow = (ROOT / ".github" / "workflows" / "collect.yml").read_text(encoding="utf-8")

        self.assertIn("allow_notion_writes", workflow)
        self.assertIn("type: boolean", workflow)
        self.assertIn("default: false", workflow)
        self.assertIn(
            "COLLECT_ALLOW_NOTION_WRITES: ${{ inputs.allow_notion_writes || false }}",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
