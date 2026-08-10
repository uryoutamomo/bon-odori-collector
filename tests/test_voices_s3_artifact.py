import gzip
import io
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from collection_support import voices_s3_artifact as artifact


class NotFound(Exception):
    response = {"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}}


class FakeS3:
    def __init__(self):
        self.objects = {}

    def get_object(self, *, Bucket, Key):
        try:
            body = self.objects[(Bucket, Key)]["Body"]
        except KeyError as exc:
            raise NotFound() from exc
        return {"Body": io.BytesIO(body)}

    def put_object(self, **kwargs):
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = kwargs


class VoicesS3ArtifactTest(unittest.TestCase):
    def args(self, root, command_name="seed", **extra):
        values = {
            "bucket": "voices-test", "prefix": "voices", "voices": str(root / "voices.json"),
            "provenance": str(root / "voices_s3_manifest.json"), "snapshot_id": "run-1",
            "expect_remote_checksum": "", "expect_source_sha256": "", "expect_item_count": 0,
            "overwrite": True, "command_name": command_name,
        }
        values.update(extra)
        return Namespace(**values)

    def test_seed_fetch_publish_preserves_snapshot_and_provenance(self):
        client = FakeS3()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            voices = [{"source": "x", "url": "https://x.example/1", "text": "原文"}]
            (root / "voices.json").write_text(json.dumps(voices, ensure_ascii=False), encoding="utf-8")
            raw_sha = artifact.sha256_bytes((root / "voices.json").read_bytes())
            seeded = artifact.seed(self.args(root, expect_source_sha256=raw_sha, expect_item_count=1), client=client)
            self.assertEqual(seeded["item_count"], 1)
            self.assertEqual(seeded["source_counts"], {"x": 1})
            key = artifact.artifact_keys("voices")["latest_data"]
            self.assertEqual(json.loads(gzip.decompress(client.objects[("voices-test", key)]["Body"])), voices)

            (root / "voices.json").unlink()
            fetched = artifact.fetch(self.args(root, command_name="fetch"), client=client)
            self.assertEqual(fetched["content_sha256"], seeded["content_sha256"])
            self.assertEqual(json.loads((root / "voices.json").read_text(encoding="utf-8")), voices)
            self.assertTrue((root / "voices_s3_manifest.json").exists())

            changed = voices + [{"source": "youtube", "url": "https://youtu.be/2", "text": "説明"}]
            (root / "voices.json").write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
            published = artifact.publish(self.args(root, command_name="publish", snapshot_id="run-2"), client=client)
            self.assertEqual(published["previous_checksum"], seeded["content_sha256"])
            self.assertEqual(published["source_counts"], {"x": 1, "youtube": 1})

    def test_seed_refuses_an_existing_artifact_and_fetch_checks_checksum(self):
        client = FakeS3()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "voices.json").write_text("[]", encoding="utf-8")
            args = self.args(root, expect_source_sha256=artifact.sha256_bytes((root / "voices.json").read_bytes()), expect_item_count=0)
            artifact.seed(args, client=client)
            with self.assertRaisesRegex(SystemExit, "one-time"):
                artifact.seed(args, client=client)
            manifest_key = artifact.artifact_keys("voices")["latest_manifest"]
            manifest = json.loads(client.objects[("voices-test", manifest_key)]["Body"])
            manifest["content_sha256"] = "bad"
            client.objects[("voices-test", manifest_key)]["Body"] = json.dumps(manifest).encode()
            with self.assertRaisesRegex(SystemExit, "checksum mismatch"):
                artifact.fetch(self.args(root, command_name="fetch"), client=client)

    def test_seed_cli_parse_has_all_publish_attributes(self):
        client = FakeS3()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "voices.json"
            source.write_text(json.dumps([{"source": "x", "url": "https://x.example/1"}]), encoding="utf-8")
            parsed = artifact.build_parser().parse_args([
                "--bucket", "voices-test", "--voices", str(source),
                "--provenance", str(root / "voices_s3_manifest.json"),
                "seed", "--snapshot-id", "cli-seed",
                "--expect-source-sha256", artifact.sha256_bytes(source.read_bytes()),
                "--expect-item-count", "1",
            ])
            manifest = artifact.seed(parsed, client=client)
        self.assertEqual(manifest["snapshot_id"], "cli-seed")

    def test_private_bucket_and_workflow_hydration_are_wired(self):
        template = Path("infra/dynamodb-queue.yml").read_text(encoding="utf-8")
        self.assertIn("VoicesArchiveBucket:", template)
        self.assertIn("VoicesArchiveBucketPolicy:", template)
        self.assertIn("PolicyName: VoicesArchiveAccess", template)
        self.assertIn("${VoicesArchiveBucket.Arn}/${VoicesArchivePrefix}/*", template)

        fetch_step = """    - name: Fetch voices artifact
      env:
        VOICES_S3_BUCKET: ${{ vars.VOICES_S3_BUCKET }}
        VOICES_S3_PREFIX: ${{ vars.VOICES_S3_PREFIX || 'voices' }}
        AWS_REGION: ap-northeast-1
      run: python voices_s3_artifact.py fetch --overwrite
"""
        workflow_paths = [
            Path(".github/workflows/collect.yml"),
            Path(".github/workflows/youtube_daily_backfill.yml"),
            Path(".github/workflows/weekly_harvest.yml"),
        ]
        workflows = {
            path: path.read_text(encoding="utf-8")
            for path in workflow_paths
        }
        for path, workflow in workflows.items():
            with self.subTest(workflow=str(path)):
                self.assertIn(fetch_step, workflow)

        collect_workflow = workflows[Path(".github/workflows/collect.yml")]
        self.assertIn("Publish voices artifact", collect_workflow)
        self.assertNotIn("git add data/latest.json data/seen.json data/voices.json", collect_workflow)

        for path in workflow_paths[1:]:
            with self.subTest(read_only_workflow=str(path)):
                self.assertNotIn("Publish voices artifact", workflows[path])
                self.assertNotIn("voices_s3_artifact.py publish", workflows[path])

    def test_run_wrapper_fetches_then_publishes(self):
        args = artifact.build_parser().parse_args(["run", "--", "python", "writer.py"])
        with (
            patch.object(artifact, "fetch") as fetch,
            patch.object(artifact, "publish") as publish,
            patch.object(artifact.subprocess, "run", return_value=Namespace(returncode=0)) as run,
        ):
            artifact.run(args)
        fetch.assert_called_once_with(args)
        publish.assert_called_once_with(args)
        run.assert_called_once_with(["python", "writer.py"], check=False)


if __name__ == "__main__":
    unittest.main()
