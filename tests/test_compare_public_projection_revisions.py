import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "compare_public_projection_revisions.py"
SPEC = importlib.util.spec_from_file_location("compare_public_projection_revisions", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ComparePublicProjectionRevisionsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bundle_number = 0
        self.repository_number = 0

    def tearDown(self):
        self.temp.cleanup()

    def pair_bundle(self, bundle, revision):
        path = bundle / "bundle-metadata.json"
        metadata = json.loads(path.read_text())
        metadata["git_sha"] = revision
        path.write_text(json.dumps(metadata))

    def write_bundle(self):
        self.bundle_number += 1
        bundle = self.root / f"bundle-{self.bundle_number}"
        db = bundle / "master/bon_odori_master.sqlite"
        db.parent.mkdir(parents=True)
        connection = sqlite3.connect(db)
        try:
            connection.execute("CREATE TABLE fixture (id INTEGER PRIMARY KEY)")
            connection.commit()
        finally:
            connection.close()
        manifest = bundle / "master/bon_odori_master_manifest.json"
        manifest.write_text(json.dumps({"database_checksum": MODULE.sha256(db)}), encoding="utf-8")
        supplemental = []
        for relative in MODULE.REQUIRED_INPUTS:
            path = bundle / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")
            supplemental.append({"path": relative, "sha256": MODULE.sha256(path)})
        metadata = {
            "format": "bon-odori-public-projection-inputs-v1",
            "git_sha": "a" * 40,
            "today": "2026-09-09",
            "target_year": 2026,
            "inputs": {
                "database": {"path": "master/bon_odori_master.sqlite", "sha256": MODULE.sha256(db)},
                "manifest": {"path": "master/bon_odori_master_manifest.json", "sha256": MODULE.sha256(manifest)},
                "supplemental_json": supplemental,
            },
        }
        (bundle / "bundle-metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        return bundle

    def fixture_repository(self):
        self.repository_number += 1
        repository = self.root / f"repository-{self.repository_number}"
        repository.mkdir()
        subprocess.run(["git", "init", "-q", str(repository)], check=True)
        subprocess.run(["git", "-C", str(repository), "config", "user.email", "r2@example.test"], check=True)
        subprocess.run(["git", "-C", str(repository), "config", "user.name", "R2 Test"], check=True)
        exporter = """import argparse, json, os
p = argparse.ArgumentParser()
p.add_argument(\"--today\", required=True)
p.add_argument(\"--target-year\", required=True, type=int)
p.add_argument(\"--master-db\", required=True)
a = p.parse_args()
out = os.environ[\"BON_ODORI_PUBLIC_OUT_DIR\"]
os.makedirs(out, exist_ok=True)
events = [{\"date\": \"2026-08-10\", \"date_end\": \"2026-08-10\", \"historical_slide_date\": \"2026-07-01\", \"today\": a.today, \"target_year\": a.target_year}]
def drift(name, default):
    return json.dumps({\"changed\": name}) if os.path.exists(\"drift-\" + name) else default
if os.path.exists(\"mutate-input\"):
    open(\"data/event_date_predictions.json\", \"w\").write('{\"mutated\": true}')
open(os.path.join(out, \"events_public.json\"), \"w\").write(drift(\"events_public.json\", json.dumps(events, ensure_ascii=False)))
open(os.path.join(out, \"events_public.js\"), \"w\").write(\"const EVENTS = \" + (json.dumps([{\"changed\": \"events_public.js\"}]) if os.path.exists(\"drift-events_public.js\") else json.dumps(events, ensure_ascii=False)) + \";\\n\")
open(os.path.join(out, \"event_songs_public.json\"), \"w\").write(drift(\"event_songs_public.json\", \"[]\"))
open(os.path.join(out, \"public_event_source_map.json\"), \"w\").write(drift(\"public_event_source_map.json\", \"{}\"))
"""
        (repository / "export_public_events.py").write_text(exporter, encoding="utf-8")
        subprocess.run(["git", "-C", str(repository), "add", "export_public_events.py"], check=True)
        subprocess.run(["git", "-C", str(repository), "commit", "-qm", "baseline"], check=True)
        return repository, subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip()

    def test_verify_bundle_rejects_metadata_context_mismatch(self):
        bundle = self.write_bundle()
        with self.assertRaisesRegex(MODULE.ComparisonError, "must exactly match"):
            MODULE.verify_bundle(bundle, today="2026-09-08", target_year=2026)

    def test_verify_bundle_rejects_db_mismatch_missing_input_and_duplicate_metadata_path(self):
        bundle = self.write_bundle()
        database = bundle / "master/bon_odori_master.sqlite"
        database.write_bytes(database.read_bytes() + b"changed")
        with self.assertRaisesRegex(MODULE.ComparisonError, "hash mismatch"):
            MODULE.verify_bundle(bundle, today="2026-09-09", target_year=2026)

        bundle = self.write_bundle()
        (bundle / MODULE.REQUIRED_INPUTS[0]).unlink()
        with self.assertRaisesRegex(MODULE.ComparisonError, "is missing"):
            MODULE.verify_bundle(bundle, today="2026-09-09", target_year=2026)

        bundle = self.write_bundle()
        metadata_path = bundle / "bundle-metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["inputs"]["supplemental_json"].append(dict(metadata["inputs"]["supplemental_json"][0]))
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaisesRegex(MODULE.ComparisonError, "duplicate supplemental"):
            MODULE.verify_bundle(bundle, today="2026-09-09", target_year=2026)

    def test_date_matrix_uses_end_and_historical_start_boundaries(self):
        matrix = MODULE.date_matrix(
            [{"date": "2026-08-10", "date_end": "2026-08-12", "historical_slide_date": "2026-07-20"}],
            today="2026-09-09",
            target_year=2026,
        )
        rows = {(row["name"], row["today"], row["target_year"]) for row in matrix}
        self.assertIn(("event_end_previous_day", "2026-08-11", 2026), rows)
        self.assertIn(("event_end_day", "2026-08-12", 2026), rows)
        self.assertIn(("event_end_next_day", "2026-08-13", 2026), rows)
        self.assertIn(("historical_start_day", "2026-07-20", 2026), rows)
        self.assertIn(("historical_start_next_day", "2026-07-21", 2026), rows)
        self.assertIn(("year_start_target_year_fixed", "2027-01-01", 2026), rows)
        self.assertIn(("year_start_target_year_advanced", "2027-01-01", 2027), rows)

    def test_compare_reports_byte_and_semantic_differences(self):
        left, right = self.root / "left.json", self.root / "right.json"
        left.write_text('{"a": 1, "b": 2}\n', encoding="utf-8")
        right.write_text('{"b":2,"a":1}\n', encoding="utf-8")
        comparison = MODULE.compare_artifact(left, right, "json")
        self.assertFalse(comparison["byte_equal"])
        self.assertTrue(comparison["semantic_equal"])
        self.assertFalse(comparison["equal"])

    def test_semantic_comparison_does_not_treat_boolean_as_integer(self):
        left, right = self.root / "left.json", self.root / "right.json"
        left.write_text('{"value": 1}', encoding="utf-8")
        right.write_text('{"value": true}', encoding="utf-8")
        comparison = MODULE.compare_artifact(left, right, "json")
        self.assertFalse(comparison["semantic_equal"])
        self.assertEqual(comparison["first_semantic_diff"]["reason"], "type_mismatch")

    def test_bundle_sqlite_sidecar_is_rejected(self):
        bundle = self.write_bundle()
        database = bundle / "master/bon_odori_master.sqlite"
        Path(f"{database}-wal").write_bytes(b"sidecar")
        with self.assertRaisesRegex(MODULE.ComparisonError, "SQLite sidecar"):
            MODULE.verify_bundle(bundle, today="2026-09-09", target_year=2026)

    def test_compare_snapshots_revisions_and_keeps_bundle_unchanged(self):
        bundle = self.write_bundle()
        repository, baseline = self.fixture_repository()
        self.pair_bundle(bundle, baseline)
        before = {path.relative_to(bundle): hashlib.sha256(path.read_bytes()).hexdigest() for path in bundle.rglob("*") if path.is_file()}
        report = MODULE.compare(
            input_bundle=bundle, baseline_revision=baseline, candidate_repo=repository,
            today="2026-09-09", target_year=2026, python=sys.executable, quiet=True,
        )
        after = {path.relative_to(bundle): hashlib.sha256(path.read_bytes()).hexdigest() for path in bundle.rglob("*") if path.is_file()}
        self.assertEqual(report["status"], "pass")
        self.assertEqual(len(report["matrix"]), 9)
        self.assertEqual(before, after)
        self.assertTrue(all(set(case["artifacts"]) == set(MODULE.ARTIFACTS) for case in report["matrix"]))
        self.assertIn("files", report["source_snapshots"]["candidate"])

    def test_dirty_candidate_snapshot_has_its_own_digest(self):
        bundle = self.write_bundle()
        repository, baseline = self.fixture_repository()
        self.pair_bundle(bundle, baseline)
        exporter = repository / "export_public_events.py"
        exporter.write_text(exporter.read_text(encoding="utf-8") + "\n# dirty candidate\n", encoding="utf-8")
        report = MODULE.compare(input_bundle=bundle, baseline_revision=baseline, candidate_repo=repository, today="2026-09-09", target_year=2026, python=sys.executable, quiet=True)
        self.assertNotEqual(report["source_snapshots"]["baseline"]["sha256"], report["source_snapshots"]["candidate"]["sha256"])
        self.assertEqual(report["candidate_revision"], baseline)

    def test_each_artifact_drift_fails_its_case(self):
        for artifact in MODULE.ARTIFACTS:
            with self.subTest(artifact=artifact):
                bundle = self.write_bundle()
                repository, baseline = self.fixture_repository()
                self.pair_bundle(bundle, baseline)
                (repository / f"drift-{artifact}").write_text("1\n", encoding="utf-8")
                report = MODULE.compare(input_bundle=bundle, baseline_revision=baseline, candidate_repo=repository, today="2026-09-09", target_year=2026, python=sys.executable, quiet=True)
                self.assertEqual(report["status"], "fail")
                self.assertTrue(any(not row["artifacts"][artifact]["equal"] for row in report["matrix"]))

    def test_input_mutation_is_rejected_at_the_export_boundary(self):
        bundle = self.write_bundle()
        repository, baseline = self.fixture_repository()
        self.pair_bundle(bundle, baseline)
        (repository / "mutate-input").write_text("1\n", encoding="utf-8")
        with self.assertRaisesRegex(MODULE.ComparisonError, "isolated input changed"):
            MODULE.compare(input_bundle=bundle, baseline_revision=baseline, candidate_repo=repository, today="2026-09-09", target_year=2026, python=sys.executable, quiet=True)

    def test_baseline_must_match_the_bundle_collector_commit(self):
        bundle = self.write_bundle()
        repository, baseline = self.fixture_repository()
        with self.assertRaisesRegex(MODULE.ComparisonError, "baseline revision must match"):
            MODULE.compare(input_bundle=bundle, baseline_revision=baseline, candidate_repo=repository, today="2026-09-09", target_year=2026, python=sys.executable, quiet=True)

    def test_shared_python_fix_applies_to_both_snapshots_and_is_reported(self):
        bundle = self.write_bundle()
        repository, baseline = self.fixture_repository()
        self.pair_bundle(bundle, baseline)
        exporter = repository / "export_public_events.py"
        exporter.write_text(
            exporter.read_text(encoding="utf-8").replace(
                '"target_year": a.target_year}]',
                '"target_year": a.target_year, "shared_fix": "applied"}]',
            ),
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(repository), "commit", "-am", "shared Python fix"], check=True)
        fix = MODULE.git_revision(repository, "HEAD")
        subprocess.run(["git", "-C", str(repository), "checkout", "-q", baseline], check=True)
        before = {path.relative_to(bundle): hashlib.sha256(path.read_bytes()).hexdigest() for path in bundle.rglob("*") if path.is_file()}
        report = MODULE.compare(input_bundle=bundle, baseline_revision=baseline, candidate_repo=repository, today="2026-09-09", target_year=2026, python=sys.executable, quiet=True, shared_code_fix_revision=fix)
        after = {path.relative_to(bundle): hashlib.sha256(path.read_bytes()).hexdigest() for path in bundle.rglob("*") if path.is_file()}
        self.assertEqual(report["comparison_mode"], "shared_code_fix_parity")
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["shared_code_fix"]["commit"], fix)
        self.assertNotEqual(report["shared_code_fix"]["snapshots"]["baseline"]["source_sha256_before"], report["shared_code_fix"]["snapshots"]["baseline"]["source_sha256_after"])
        self.assertNotEqual(report["shared_code_fix"]["snapshots"]["candidate"]["source_sha256_before"], report["shared_code_fix"]["snapshots"]["candidate"]["source_sha256_after"])
        self.assertEqual(before, after)

    def test_shared_fix_applied_to_only_one_snapshot_fails_output_parity(self):
        bundle = self.write_bundle()
        repository, baseline = self.fixture_repository()
        self.pair_bundle(bundle, baseline)
        exporter = repository / "export_public_events.py"
        exporter.write_text(
            exporter.read_text(encoding="utf-8").replace(
                '"target_year": a.target_year}]',
                '"target_year": a.target_year, "shared_fix": "applied"}]',
            ),
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(repository), "commit", "-am", "shared Python fix"], check=True)
        fix = MODULE.git_revision(repository, "HEAD")
        subprocess.run(["git", "-C", str(repository), "checkout", "-q", baseline], check=True)
        original_apply = MODULE.apply_shared_code_fix

        def apply_to_baseline_only(root, patch_path, label):
            if label == "baseline":
                original_apply(root, patch_path, label)

        with patch.object(MODULE, "apply_shared_code_fix", side_effect=apply_to_baseline_only):
            report = MODULE.compare(input_bundle=bundle, baseline_revision=baseline, candidate_repo=repository, today="2026-09-09", target_year=2026, python=sys.executable, quiet=True, shared_code_fix_revision=fix)
        self.assertEqual(report["comparison_mode"], "shared_code_fix_parity")
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any(not row["artifacts"]["events_public.json"]["equal"] for row in report["matrix"]))

    def test_shared_fix_rejects_preapplied_or_non_python_commit(self):
        bundle = self.write_bundle()
        repository, baseline = self.fixture_repository()
        self.pair_bundle(bundle, baseline)
        exporter = repository / "export_public_events.py"
        exporter.write_text(exporter.read_text(encoding="utf-8") + "\n# shared audit fix\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repository), "commit", "-am", "shared Python fix"], check=True)
        preapplied = MODULE.git_revision(repository, "HEAD")
        with self.assertRaisesRegex(MODULE.ComparisonError, "already applied or cannot apply"):
            MODULE.compare(input_bundle=bundle, baseline_revision=baseline, candidate_repo=repository, today="2026-09-09", target_year=2026, python=sys.executable, quiet=True, shared_code_fix_revision=preapplied)

        subprocess.run(["git", "-C", str(repository), "checkout", "-q", baseline], check=True)
        (repository / "notes.md").write_text("not Python\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repository), "add", "notes.md"], check=True)
        subprocess.run(["git", "-C", str(repository), "commit", "-qm", "non Python fix"], check=True)
        non_python = MODULE.git_revision(repository, "HEAD")
        with self.assertRaisesRegex(MODULE.ComparisonError, "Python-only"):
            MODULE.compare(input_bundle=bundle, baseline_revision=baseline, candidate_repo=repository, today="2026-09-09", target_year=2026, python=sys.executable, quiet=True, shared_code_fix_revision=non_python)

    def test_matching_safe_refusal_is_blocked_never_four_output_pass(self):
        bundle = self.write_bundle()
        repository, _ = self.fixture_repository()
        exporter = repository / "export_public_events.py"
        original = exporter.read_text()
        exporter.write_text(original.replace(
            'out = os.environ["BON_ODORI_PUBLIC_OUT_DIR"]',
            'if a.target_year == 2027:\n    raise ValueError("public song projection refused invalid rows: fixture")\n'
            'out = os.environ["BON_ODORI_PUBLIC_OUT_DIR"]',
        ))
        subprocess.run(["git", "-C", str(repository), "commit", "-qam", "existing year rollover refusal"], check=True)
        baseline = MODULE.git_revision(repository, "HEAD")
        self.pair_bundle(bundle, baseline)
        report = MODULE.compare(input_bundle=bundle, baseline_revision=baseline, candidate_repo=repository, today="2026-09-09", target_year=2026, python=sys.executable, quiet=True)
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["full_four_output_parity"])
        self.assertEqual(sum(row["status"] == "pass" for row in report["matrix"]), 8)
        refusal = report["matrix"][-1]
        self.assertTrue(refusal["refusal_parity"])
        self.assertEqual(refusal["artifacts"], {})
        self.assertEqual(refusal["export_failures"]["candidate"]["artifacts_present"], [])
        # If the candidate bypasses the audit, the old rejection is no excuse.
        exporter.write_text(original)
        changed = MODULE.compare(input_bundle=bundle, baseline_revision=baseline, candidate_repo=repository, today="2026-09-09", target_year=2026, python=sys.executable, quiet=True)
        self.assertEqual(changed["status"], "fail")
        self.assertFalse(changed["matrix"][-1]["refusal_parity"])


if __name__ == "__main__":
    unittest.main()
