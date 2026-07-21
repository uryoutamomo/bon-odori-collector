import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "compare_public_export_postprocessors.py"
SPEC = importlib.util.spec_from_file_location("compare_public_export_postprocessors", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ComparePublicExportPostprocessorsTest(unittest.TestCase):
    def test_canonical_digest_ignores_dict_order(self):
        left = {"b": [2, {"y": "z"}], "a": 1}
        right = {"a": 1, "b": [2, {"y": "z"}]}

        self.assertEqual(MODULE.canonical_json(left), MODULE.canonical_json(right))
        self.assertEqual(MODULE.digest(left), MODULE.digest(right))

    def test_first_diff_reports_nested_path(self):
        diff = MODULE.first_diff(
            [{"name": "A", "date": "2026-07-01"}],
            [{"name": "A", "date": "2026-07-02"}],
        )

        self.assertEqual(diff["path"], "$[0].date")
        self.assertEqual(diff["reason"], "value_mismatch")

    def test_legacy_overlay_uses_report_safe_output_paths(self):
        with patch.object(MODULE, "run") as run:
            MODULE.apply_legacy_overlay(
                "python3",
                Path("/tmp/events_public.json"),
                today="2026-07-16",
                quiet=True,
            )

        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0][1:3], ["-m", "public_json_postprocessors.apply_public_date_predictions"])
        self.assertEqual(commands[1][1:3], ["-m", "public_json_postprocessors.apply_public_historical_references"])
        self.assertIn("--today", commands[1])
        self.assertIn("2026-07-16", commands[1])
        self.assertEqual(commands[2][1:3], ["-m", "public_json_postprocessors.apply_public_season_hints"])
        flattened = "\n".join(" ".join(command) for command in commands)
        self.assertNotIn("deploy", flattened)
        self.assertNotIn("sync_public_event_additions_to_site.py", flattened)

    def test_prepared_master_db_copies_and_cleans_temporary_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            source = tmp / "source.sqlite"
            target = tmp / "data" / "bon_odori_master.sqlite"
            source.write_bytes(b"sqlite")

            with patch.object(MODULE, "MASTER_DB", target):
                with MODULE.prepared_master_db(str(source)):
                    self.assertEqual(target.read_bytes(), b"sqlite")

                self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
