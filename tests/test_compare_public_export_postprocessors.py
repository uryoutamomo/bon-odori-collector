import importlib.util
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
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
                target_year=2026,
                today="2026-07-16",
                quiet=True,
            )

        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0][1:3], ["-m", "public_json_postprocessors.apply_public_date_predictions"])
        self.assertEqual(commands[1][1:3], ["-m", "public_json_postprocessors.apply_public_historical_references"])
        self.assertIn("--today", commands[1])
        self.assertIn("2026-07-16", commands[1])
        self.assertIn("--target-year", commands[1])
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

    def test_manifest_checksum_mismatch_refuses_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db = tmp / "master.sqlite"
            manifest = tmp / "manifest.json"
            db.write_bytes(b"not-the-manifest-db")
            manifest.write_text(json.dumps({"database_checksum": "0" * 64}), encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "checksum mismatch"):
                MODULE.validated_manifest(db, manifest)

    def test_missing_song_fallback_refuses_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "event_song_occurrences_public.json"
            with patch.object(MODULE, "SONG_OCCURRENCES_SNAPSHOT", missing):
                with self.assertRaisesRegex(SystemExit, "Required export input is missing"):
                    MODULE.fixed_input_provenance()

    def test_export_env_forces_master_rdb_over_notion_environment(self):
        env = MODULE.export_env(
            {"BON_ODORI_PUBLIC_SOURCE": "notion", "NOTION_API_TOKEN": "present"},
            Path("/tmp/current"),
            Path("/tmp/current/report.json"),
            "2026-07-16",
            Path("/tmp/input/event_song_occurrences_public.json"),
        )

        self.assertEqual(env["BON_ODORI_PUBLIC_SOURCE"], "master_rdb")
        self.assertEqual(
            env["BON_ODORI_SONG_OCCURRENCES_JSON"],
            "/tmp/input/event_song_occurrences_public.json",
        )

    def test_non_events_artifact_difference_fails_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            current = tmp / "current"
            legacy = tmp / "legacy"
            current.mkdir()
            legacy.mkdir()
            for name, kind in MODULE.ARTIFACTS.items():
                value = [] if kind == "json" else "window.BON_ODORI_EVENTS = [];\n"
                (current / name).write_text(json.dumps(value) if kind == "json" else value, encoding="utf-8")
                (legacy / name).write_text(json.dumps(value) if kind == "json" else value, encoding="utf-8")
            (legacy / "event_songs_public.json").write_text(json.dumps([{"name": "changed"}]), encoding="utf-8")

            comparisons = MODULE.compare_artifacts(current, legacy)

        self.assertFalse(comparisons["event_songs_public.json"]["equal"])
        self.assertIsNotNone(comparisons["event_songs_public.json"]["first_diff"])
        self.assertEqual(
            MODULE.first_comparison_diff(comparisons)["artifact"],
            "event_songs_public.json",
        )

    def test_export_once_routes_isolated_db_and_fallback_to_exporter(self):
        with patch.object(MODULE, "run") as run:
            MODULE.export_once(
                "python3",
                Path("/tmp/current"),
                2026,
                "2026-07-16",
                Path("/tmp/isolated/bon_odori_master.sqlite"),
                Path("/tmp/inputs/event_song_occurrences_public.json"),
                quiet=True,
            )

        command = run.call_args.args[0]
        env = run.call_args.kwargs["env"]
        self.assertEqual(command[command.index("--master-db") + 1], "/tmp/isolated/bon_odori_master.sqlite")
        self.assertEqual(
            env["BON_ODORI_SONG_OCCURRENCES_JSON"],
            "/tmp/inputs/event_song_occurrences_public.json",
        )

    def test_comparison_env_removes_github_step_summary(self):
        self.assertNotIn("GITHUB_STEP_SUMMARY", MODULE.comparison_env({"GITHUB_STEP_SUMMARY": "/tmp/summary"}))

    def test_sqlite_sidecar_refuses_isolated_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db = tmp / "master.sqlite"
            manifest = tmp / "manifest.json"
            db.write_bytes(b"sqlite")
            Path(f"{db}-wal").write_bytes(b"uncheckpointed")
            manifest.write_text(
                json.dumps({"database_checksum": MODULE.file_sha256(db)}), encoding="utf-8"
            )

            with self.assertRaisesRegex(SystemExit, "single-file artifact"):
                MODULE.copy_isolated_master_db(db, tmp / "copy.sqlite", manifest)

    def compare_fixture(self, changed_artifact=None, before_copy=None):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            source_db = tmp / "source.sqlite"
            manifest = tmp / "manifest.json"
            fallback = tmp / "event_song_occurrences_public.json"
            with closing(sqlite3.connect(source_db)) as connection:
                connection.execute("CREATE TABLE fixture(id INTEGER PRIMARY KEY)")
            manifest.write_text(
                json.dumps({"database_checksum": MODULE.file_sha256(source_db)}), encoding="utf-8"
            )
            source_sha256 = MODULE.file_sha256(source_db)
            fallback.write_text(json.dumps({"occurrences": []}), encoding="utf-8")
            fallback_key = str(fallback)
            fixed_inputs = {fallback_key: MODULE.file_sha256(fallback)}
            calls = []

            def fake_export(_python, out_dir, _year, _today, isolated_db, isolated_fallback, _quiet):
                calls.append((isolated_db, isolated_fallback))
                out_dir.mkdir(parents=True, exist_ok=True)
                for name, kind in MODULE.ARTIFACTS.items():
                    value = [] if kind == "json" else "window.BON_ODORI_EVENTS = [];\n"
                    (out_dir / name).write_text(
                        json.dumps(value) if kind == "json" else value,
                        encoding="utf-8",
                    )
                if len(calls) == 2 and changed_artifact:
                    kind = MODULE.ARTIFACTS[changed_artifact]
                    changed = [{"changed": changed_artifact}] if kind == "json" else "changed JS\n"
                    (out_dir / changed_artifact).write_text(
                        json.dumps(changed) if kind == "json" else changed,
                        encoding="utf-8",
                    )
                return out_dir / "events_public.json"

            original_copy = MODULE.copy_isolated_master_db

            def copy_with_optional_change(source, destination, manifest_path):
                if before_copy:
                    before_copy(source, manifest_path)
                return original_copy(source, destination, manifest_path)

            with patch.object(MODULE, "SONG_OCCURRENCES_SNAPSHOT", fallback), \
                 patch.object(MODULE, "fixed_input_provenance", return_value=fixed_inputs), \
                 patch.object(MODULE, "export_once", side_effect=fake_export), \
                 patch.object(MODULE, "apply_legacy_overlay"), \
                 patch.object(MODULE, "git_commit", return_value="f6d0be4"), \
                 patch.object(MODULE, "copy_isolated_master_db", side_effect=copy_with_optional_change):
                report = MODULE.compare(
                    target_year=2026,
                    today="2026-07-16",
                    python="python3",
                    quiet=True,
                    master_db=str(source_db),
                    master_manifest=str(manifest),
                )

            result = {
                "report": report,
                "calls": calls,
                "source_db": source_db,
                "source_sha256": source_sha256,
            }
        return result

    def test_compare_routes_one_isolated_db_and_two_isolated_fallbacks(self):
        result = self.compare_fixture()
        report = result["report"]
        calls = result["calls"]

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], calls[1][0])
        self.assertNotEqual(calls[0][0], result["source_db"])
        self.assertNotEqual(calls[0][1], calls[1][1])
        self.assertNotIn("event_song_occurrences_public.json", report["artifact_comparisons"])
        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["deep_equal"])
        self.assertEqual(report["provenance"]["isolated_master_db"]["sha256_after"], result["source_sha256"])

    def test_compare_fails_for_each_non_events_output_difference(self):
        for artifact in ("event_songs_public.json", "public_event_source_map.json", "events_public.js"):
            with self.subTest(artifact=artifact):
                report = self.compare_fixture(changed_artifact=artifact)["report"]
                self.assertEqual(report["status"], "fail")
                self.assertFalse(report["deep_equal"])
                self.assertEqual(report["first_diff"]["artifact"], artifact)

    def test_compare_refuses_db_and_manifest_changed_during_copy(self):
        def update_db_and_manifest(source, manifest_path):
            with closing(sqlite3.connect(source)) as connection:
                connection.execute("INSERT INTO fixture VALUES (1)")
                connection.commit()
            manifest_path.write_text(
                json.dumps({"database_checksum": MODULE.file_sha256(source)}), encoding="utf-8"
            )

        with self.assertRaisesRegex(SystemExit, "changed between manifest validation and isolated copy"):
            self.compare_fixture(before_copy=update_db_and_manifest)


if __name__ == "__main__":
    unittest.main()
