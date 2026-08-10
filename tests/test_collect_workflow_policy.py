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

    def test_x_health_gate_runs_last_after_collection_outputs_are_preserved(self):
        workflow = (ROOT / ".github" / "workflows" / "collect.yml").read_text(encoding="utf-8")

        collector = workflow.index("- name: Run collector")
        health_report_env = workflow.index(
            "X_COLLECTION_HEALTH_REPORT: ${{ runner.temp }}/x-collection-health.json",
            collector,
        )
        gate = workflow.index("- name: Enforce X collection health")

        self.assertLess(collector, health_report_env)
        self.assertGreater(gate, workflow.index("- name: Commit and Push changes"))
        self.assertGreater(gate, workflow.index("- name: Upload low-priority inbox evidence"))
        self.assertIn("if: ${{ always() }}", workflow[gate:])
        self.assertIn(
            'python collect.py --check-x-health "$X_COLLECTION_HEALTH_REPORT"',
            workflow[gate:],
        )


if __name__ == "__main__":
    unittest.main()
