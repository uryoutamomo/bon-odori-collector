import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "publish_public_data_flow.py"
SPEC = importlib.util.spec_from_file_location("publish_public_data_flow", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PublishPublicDataFlowTest(unittest.TestCase):
    def test_default_commands_stop_before_guard_and_deploy(self):
        commands = MODULE.build_commands("python3", with_guard=False)

        self.assertEqual(
            commands,
            [
                ["python3", "export_public_events.py"],
                ["python3", "build_publication_gap_review.py"],
                ["python3", "-m", "public_json_postprocessors.review_missing_occurrence_venues"],
                ["python3", "run_review_console.py", "--inventory"],
            ],
        )
        flattened = "\n".join(" ".join(command) for command in commands)
        self.assertNotIn("guard_public_events_sync", flattened)
        self.assertNotIn("sync_public_event_additions_to_site.py", flattened)
        self.assertNotIn("deploy", flattened)

    def test_guard_is_explicit_report_only_step(self):
        commands = MODULE.build_commands("python3", with_guard=True)

        self.assertEqual(
            commands[-1],
            ["python3", "-m", "public_json_postprocessors.guard_public_events_sync", "--report-only"],
        )

    def test_dry_run_does_not_execute_commands(self):
        with patch.object(MODULE.subprocess, "run") as run:
            MODULE.main(["--dry-run", "--python", "python3"])

        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
