import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/collect.yml"


class CollectEventStateAxesWiringTest(unittest.TestCase):
    def setUp(self):
        self.source = WORKFLOW.read_text(encoding="utf-8")
        self.step = self.source[
            self.source.index("- name: Sync date predictions and canonical event-state axes"):
            self.source.index("- name: Upload event-state axes evidence")
        ]

    def test_is_default_off_and_runs_before_public_export(self):
        self.assertIn("EVENT_STATE_AXES_ENABLED: ${{ vars.EVENT_STATE_AXES_ENABLED }}", self.step)
        self.assertIn('if [ "$EVENT_STATE_AXES_ENABLED" = "true" ]; then', self.step)
        self.assertLess(
            self.source.index("- name: Sync date predictions and canonical event-state axes"),
            self.source.index("- name: Refresh public event export"),
        )

    def test_prediction_sync_does_not_depend_on_the_state_axes_feature_flag(self):
        step_header = self.source[
            self.source.index("- name: Sync date predictions and canonical event-state axes"):
            self.source.index("      run: |", self.source.index("- name: Sync date predictions and canonical event-state axes"))
        ]
        self.assertIn("if: ${{ vars.MASTER_DB_S3_BUCKET != '' }}", step_header)
        self.assertNotIn("EVENT_STATE_AXES_ENABLED == 'true'", step_header)

    def test_uses_exact_gate_audit_and_checksum_cas_without_force(self):
        prediction_dry_run = self.step.index(
            'event-date-predictions-dry-run.json'
        )
        prediction_apply = self.step.index(
            "--confirm 'SYNC EVENT DATE PREDICTIONS'"
        )
        axes_apply = self.step.index("--confirm 'MIGRATE EVENT STATE AXES'")
        self.assertLess(prediction_dry_run, prediction_apply)
        self.assertLess(prediction_apply, axes_apply)
        self.assertIn("sync_event_date_predictions_rdb.py", self.step)
        self.assertIn("--confirm 'MIGRATE EVENT STATE AXES'", self.step)
        self.assertIn("audit_master_rdb.py", self.step)
        self.assertIn("--expect-remote-checksum \"$RSTART\"", self.step)
        self.assertNotIn("--force", self.step)
        self.assertIn("master_db_s3_artifact.py fetch --overwrite", self.step)
        self.assertIn("event-date-predictions-rend.json", self.step)
        self.assertIn("--check", self.step)
        self.assertIn("event-state-axes-rend.json", self.step)

    def test_prediction_sync_evidence_is_uploaded_with_axes_evidence(self):
        upload = self.source[self.source.index("- name: Upload event-state axes evidence"):]
        self.assertIn("event-date-predictions-dry-run.json", upload)
        self.assertIn("event-date-predictions-apply.json", upload)
        self.assertIn("event-date-predictions-rend.json", upload)

    def test_transitions_ended_occurrences_before_public_export_with_cas(self):
        start = self.source.index("- name: Transition ended confirmed occurrences")
        end = self.source.index("- name: Upload event-state axes evidence")
        step = self.source[start:end]
        self.assertIn("transition_ended_occurrences.py", step)
        self.assertIn("vars.ENDED_TRANSITION_ENABLED == 'true'", step)
        self.assertIn("--as-of-date \"$TODAY\"", step)
        self.assertIn("--confirm 'TRANSITION ENDED OCCURRENCES'", step)
        self.assertIn('"count"', step)
        self.assertIn('if [ "$COUNT" -gt 0 ]; then', step)
        self.assertIn("--expect-remote-checksum \"$RSTART\"", step)
        self.assertNotIn("LOCAL_SHA", step)
        self.assertLess(start, self.source.index("- name: Refresh public event export"))


if __name__ == "__main__":
    unittest.main()
