import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
import yaml
from pathlib import Path

from master_rdb.capture_public_projection_inputs import CaptureError, capture
from argparse import Namespace
from master_rdb.master_db import file_sha256


OPENSSL = shutil.which("openssl")


class CapturePublicProjectionInputsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = Path(__file__).resolve().parents[1]
        self.db = self.root / "master.sqlite"
        connection = sqlite3.connect(self.db)
        try:
            connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
            connection.execute("INSERT INTO sample(value) VALUES ('bon')")
            connection.commit()
        finally:
            connection.close()
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(json.dumps({"database_checksum": file_sha256(self.db)}), encoding="utf-8")
        self.inputs = []
        for relative_path in (
            "data/event_date_predictions.json",
            "data/event_date_update_candidates.json",
            "data/public_event_overrides.json",
            "data/public_fixed_date_rules.json",
            "data/song_master_initial_registration.json",
            "data/rdb_song_review_source.json",
            "data/public/event_song_occurrences_public.json",
        ):
            source = self.repo / relative_path
            self.inputs.append(source)
        self.cert = self.root / "recipient.pem"
        self.key = self.root / "recipient.key"
        if OPENSSL:
            subprocess.run(
                [OPENSSL, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=r2-test", "-keyout", str(self.key), "-out", str(self.cert)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def tearDown(self):
        self.temp.cleanup()

    def args(self, **overrides):
        values = {
            "db": self.db,
            "manifest": self.manifest,
            "input": self.inputs,
            "today": "2026-09-09",
            "target_year": "2026",
            "recipient_cert": self.cert,
            "output": self.root / "bundle.cms",
            "repo": self.repo,
            "openssl": OPENSSL or "openssl",
        }
        values.update(overrides)
        return Namespace(**values)

    def fixture_repository(self, *, broken_json=False, dirty=False):
        repository = self.root / "repository"
        subprocess.run(["git", "init", "-q", str(repository)], check=True)
        subprocess.run(["git", "-C", str(repository), "config", "user.email", "r2@example.test"], check=True)
        subprocess.run(["git", "-C", str(repository), "config", "user.name", "R2 test"], check=True)
        inputs = []
        for index, relative_path in enumerate(
            (
                "data/event_date_predictions.json",
                "data/event_date_update_candidates.json",
                "data/public_event_overrides.json",
                "data/public_fixed_date_rules.json",
                "data/song_master_initial_registration.json",
                "data/rdb_song_review_source.json",
                "data/public/event_song_occurrences_public.json",
            )
        ):
            path = repository / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{broken\n" if broken_json and index == 0 else "{}\n", encoding="utf-8")
            inputs.append(path)
        subprocess.run(["git", "-C", str(repository), "add", "data"], check=True)
        subprocess.run(["git", "-C", str(repository), "commit", "-qm", "fixture"], check=True)
        if dirty:
            inputs[0].write_text('{"dirty": true}\n', encoding="utf-8")
        return repository, inputs

    @unittest.skipUnless(OPENSSL, "openssl is required for CMS round-trip")
    def test_round_trip_contains_hashed_inputs_and_context(self):
        args = self.args()
        capture(args)
        plaintext = self.root / "decrypted.tar.gz"
        subprocess.run(
            [OPENSSL, "cms", "-decrypt", "-inform", "DER", "-binary", "-in", str(args.output), "-recip", str(self.cert), "-inkey", str(self.key), "-out", str(plaintext)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with tarfile.open(plaintext, "r:gz") as archive:
            names = archive.getnames()
            self.assertEqual(names[:2], ["master/bon_odori_master.sqlite", "master/bon_odori_master_manifest.json"])
            self.assertEqual(names[-1], "bundle-metadata.json")
            metadata = json.load(io.TextIOWrapper(archive.extractfile("bundle-metadata.json"), encoding="utf-8"))
        self.assertEqual(metadata["git_sha"], subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip())
        self.assertEqual(metadata["today"], "2026-09-09")
        self.assertEqual(metadata["target_year"], 2026)
        self.assertEqual(metadata["inputs"]["database"]["sha256"], file_sha256(self.db))
        self.assertEqual(
            metadata["inputs"]["supplemental_json"],
            [{"path": str(path.relative_to(self.repo)), "sha256": file_sha256(path)} for path in self.inputs],
        )

    def test_checksum_mismatch_creates_no_artifact(self):
        self.manifest.write_text(json.dumps({"database_checksum": "0" * 64}), encoding="utf-8")
        args = self.args()
        with self.assertRaisesRegex(CaptureError, "does not match"):
            capture(args)
        self.assertFalse(args.output.exists())

    def test_missing_supplemental_input_creates_no_artifact(self):
        args = self.args(input=self.inputs[:-1])
        with self.assertRaisesRegex(CaptureError, "exactly the seven required"):
            capture(args)
        self.assertFalse(args.output.exists())

    def test_invalid_recipient_certificate_creates_no_artifact(self):
        self.cert.write_text("not a certificate\n", encoding="utf-8")
        args = self.args()
        with self.assertRaisesRegex(CaptureError, "valid PEM X.509"):
            capture(args)
        self.assertFalse(args.output.exists())

    def test_dirty_supplemental_input_creates_no_artifact(self):
        repository, inputs = self.fixture_repository(dirty=True)
        args = self.args(repo=repository, input=inputs)
        with self.assertRaisesRegex(CaptureError, "differs from HEAD"):
            capture(args)
        self.assertFalse(args.output.exists())

    def test_committed_invalid_json_creates_no_artifact(self):
        repository, inputs = self.fixture_repository(broken_json=True)
        args = self.args(repo=repository, input=inputs)
        with self.assertRaisesRegex(CaptureError, "not valid JSON"):
            capture(args)
        self.assertFalse(args.output.exists())

    def test_sqlite_sidecars_create_no_artifact(self):
        for suffix in ("-wal", "-shm", "-journal"):
            with self.subTest(suffix=suffix):
                sidecar = Path(f"{self.db}{suffix}")
                sidecar.write_bytes(b"sidecar")
                args = self.args(output=self.root / f"bundle{suffix}.cms")
                with self.assertRaisesRegex(CaptureError, "database sidecar is present"):
                    capture(args)
                self.assertFalse(args.output.exists())
                sidecar.unlink()

    def test_cms_partial_output_failure_creates_no_final_artifact(self):
        fake_openssl = self.root / "fake-openssl"
        fake_openssl.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = x509 ]; then exit 0; fi\n"
            "while [ \"$#\" -gt 0 ]; do\n"
            "  if [ \"$1\" = -out ]; then printf partial > \"$2\"; exit 1; fi\n"
            "  shift\n"
            "done\n"
            "exit 1\n",
            encoding="utf-8",
        )
        fake_openssl.chmod(0o700)
        args = self.args(openssl=str(fake_openssl))
        with self.assertRaisesRegex(CaptureError, "CMS encryption failed"):
            capture(args)
        self.assertFalse(args.output.exists())

    def workflow(self):
        path = self.repo / ".github/workflows/capture-public-projection-inputs.yml"
        return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    def test_workflow_limits_to_manual_encrypted_reads(self):
        workflow = self.workflow()
        self.assertEqual(set(workflow["on"]), {"workflow_dispatch"})
        self.assertEqual(workflow["concurrency"], {
            "group": "bon-odori-master-rdb", "cancel-in-progress": "false",
        })
        self.assertEqual(set(workflow["jobs"]), {"capture"})
        job = workflow["jobs"]["capture"]
        self.assertEqual(job["permissions"], {"contents": "read", "id-token": "write"})
        steps = job["steps"]
        commands = [step["run"] for step in steps if "run" in step]
        self.assertEqual(len(commands), 3)
        self.assertEqual(commands[0], "pip install -r requirements.txt")
        self.assertEqual(commands[1], "python master_db_s3_artifact.py fetch --overwrite")
        self.assertTrue(all("${{ inputs." not in command for command in commands))
        uploads = [step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@")]
        self.assertEqual(len(uploads), 1)
        self.assertEqual(uploads[0]["with"]["path"], "${{ runner.temp }}/public-projection-inputs.cms")
        self.assertEqual(uploads[0]["with"]["retention-days"], "3")
        self.assertEqual(uploads[0]["with"]["if-no-files-found"], "error")
        self.assertNotIn("if", uploads[0])

    @unittest.skipUnless(OPENSSL, "openssl is required for workflow round-trip")
    def test_workflow_encryption_step_runs_real_cli_and_rejects_shell_input(self):
        repository, _ = self.fixture_repository()
        script = repository / "master_rdb/capture_public_projection_inputs.py"
        script.parent.mkdir()
        shutil.copyfile(self.repo / "master_rdb/capture_public_projection_inputs.py", script)
        shutil.copyfile(self.db, repository / "data/bon_odori_master.sqlite")
        shutil.copyfile(self.manifest, repository / "data/bon_odori_master_manifest.json")
        runner_temp = self.root / "runner"
        runner_temp.mkdir()
        executable_dir = self.root / "bin"
        executable_dir.mkdir()
        (executable_dir / "python").symlink_to(sys.executable)
        env = dict(os.environ, PATH=str(executable_dir) + os.pathsep + os.environ["PATH"],
                   RUNNER_TEMP=str(runner_temp), RECIPIENT_CERTIFICATE=self.cert.read_text(),
                   COMPARISON_TODAY="2026-09-09", COMPARISON_TARGET_YEAR="2026")
        command = next(step["run"] for step in self.workflow()["jobs"]["capture"]["steps"]
                       if step.get("name") == "Encrypt comparison inputs for the named recipient")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", command],
                                cwd=repository, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        artifact = runner_temp / "public-projection-inputs.cms"
        self.assertEqual([path.name for path in runner_temp.iterdir()], [artifact.name])
        plaintext = self.root / "workflow-decrypted.tar.gz"
        subprocess.run([OPENSSL, "cms", "-decrypt", "-inform", "DER", "-binary", "-in", str(artifact),
                        "-recip", str(self.cert), "-inkey", str(self.key), "-out", str(plaintext)],
                       check=True, capture_output=True)
        with tarfile.open(plaintext, "r:gz") as archive:
            metadata = json.load(archive.extractfile("bundle-metadata.json"))
        self.assertEqual(metadata["inputs"]["database"]["sha256"], file_sha256(self.db))
        artifact.unlink()
        env["COMPARISON_TODAY"] = '2026-09-09$(touch "$RUNNER_TEMP/injected")'
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", command],
                                cwd=repository, env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(runner_temp.iterdir()), [])
