import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/collect.yml"


class CollectEventStateAxesWiringTest(unittest.TestCase):
    def setUp(self):
        self.source = WORKFLOW.read_text(encoding="utf-8")
        self.step = self.source[
            self.source.index("- name: Sync canonical event-state axes"):
            self.source.index("- name: Upload event-state axes evidence")
        ]

    def test_is_default_off_and_runs_before_public_export(self):
        self.assertIn("vars.EVENT_STATE_AXES_ENABLED == 'true'", self.step)
        self.assertLess(
            self.source.index("- name: Sync canonical event-state axes"),
            self.source.index("- name: Refresh public event export"),
        )

    def test_uses_exact_gate_audit_and_checksum_cas_without_force(self):
        self.assertIn("--confirm 'MIGRATE EVENT STATE AXES'", self.step)
        self.assertIn("audit_master_rdb.py", self.step)
        self.assertIn("--expect-remote-checksum \"$RSTART\"", self.step)
        self.assertNotIn("--force", self.step)
        self.assertIn("master_db_s3_artifact.py fetch --overwrite", self.step)
        self.assertIn("event-state-axes-rend.json", self.step)


if __name__ == "__main__":
    unittest.main()
