import json
import sqlite3
import tempfile
import unittest
from argparse import Namespace
from io import BytesIO
from pathlib import Path

import master_rdb.master_db as master_db
from master_rdb.master_db import connect_existing, file_sha256


class FakeClientError(Exception):
    def __init__(self, code, status):
        self.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}
        super().__init__(code)


class FakeS3:
    def __init__(self):
        self.objects = {}

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise FakeClientError("NoSuchKey", 404)
        return {"Body": BytesIO(self.objects[(Bucket, Key)])}

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise FakeClientError("NoSuchKey", 404)
        return {"ContentLength": len(self.objects[(Bucket, Key)])}

    def download_file(self, Bucket, Key, Filename):
        if (Bucket, Key) not in self.objects:
            raise FakeClientError("NoSuchKey", 404)
        Path(Filename).write_bytes(self.objects[(Bucket, Key)])

    def upload_file(self, Filename, Bucket, Key, ExtraArgs=None):
        self.objects[(Bucket, Key)] = Path(Filename).read_bytes()


def make_db(path):
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO sample(name) VALUES ('bon')")
        conn.commit()


class MasterDbS3ArtifactTest(unittest.TestCase):
    def test_connect_existing_does_not_create_missing_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.sqlite"

            with self.assertRaises(SystemExit):
                connect_existing(missing)

            self.assertFalse(missing.exists())

    def test_artifact_keys_use_latest_and_snapshot_paths(self):
        keys = artifact.artifact_keys("prefix/", snapshot_id="snap1")

        self.assertEqual(keys["latest_database_key"], "prefix/latest/bon_odori_master.sqlite")
        self.assertEqual(keys["snapshot_manifest_key"], "prefix/snapshots/snap1/bon_odori_master_manifest.json")

    def test_publish_uploads_snapshot_and_latest_with_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db = tmp / "master.sqlite"
            manifest = tmp / "manifest.json"
            make_db(db)
            manifest.write_text("{}", encoding="utf-8")
            client = FakeS3()

            result = artifact.publish(
                Namespace(
                    bucket="bucket",
                    prefix="master-rdb",
                    db=db,
                    manifest=manifest,
                    snapshot_id="snap1",
                    expect_remote_checksum="",
                    force=False,
                ),
                client=client,
            )

            self.assertEqual(result["database_checksum"], file_sha256(db))
            self.assertIn(("bucket", "master-rdb/latest/bon_odori_master.sqlite"), client.objects)
            self.assertIn(("bucket", "master-rdb/snapshots/snap1/bon_odori_master_manifest.json"), client.objects)
            uploaded_manifest = json.loads(client.objects[("bucket", "master-rdb/latest/bon_odori_master_manifest.json")])
            self.assertEqual(uploaded_manifest["artifact"]["snapshot_id"], "snap1")
            self.assertEqual(uploaded_manifest["database_checksum"], file_sha256(db))

    def test_fetch_verifies_checksum_and_writes_local_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            source_db = tmp / "source.sqlite"
            target_db = tmp / "target.sqlite"
            target_manifest = tmp / "manifest.json"
            make_db(source_db)
            checksum = file_sha256(source_db)
            client = FakeS3()
            client.objects[("bucket", "master-rdb/latest/bon_odori_master.sqlite")] = source_db.read_bytes()
            client.objects[("bucket", "master-rdb/latest/bon_odori_master_manifest.json")] = json.dumps(
                {"database_checksum": checksum},
                ensure_ascii=False,
            ).encode("utf-8")

            result = artifact.fetch(
                Namespace(
                    bucket="bucket",
                    prefix="master-rdb",
                    db=target_db,
                    manifest=target_manifest,
                    overwrite=False,
                ),
                client=client,
            )

            self.assertEqual(result["database_checksum"], checksum)
            self.assertEqual(file_sha256(target_db), checksum)
            self.assertEqual(json.loads(target_manifest.read_text(encoding="utf-8"))["database_checksum"], checksum)

    def test_status_returns_remote_manifest_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            make_db(db)
            client = FakeS3()
            client.objects[("bucket", "master-rdb/latest/bon_odori_master.sqlite")] = db.read_bytes()
            client.objects[("bucket", "master-rdb/latest/bon_odori_master_manifest.json")] = json.dumps(
                {
                    "database_checksum": "remote-sha",
                    "generated_by": "build_master_rdb.py",
                    "table_counts": {"occurrence_dates": 290},
                    "artifact": {
                        "published_at": "2026-07-13T01:58:12+00:00",
                        "snapshot_id": "20260713T015812Z",
                    },
                },
                ensure_ascii=False,
            ).encode("utf-8")

            result = artifact.status(
                Namespace(bucket="bucket", prefix="master-rdb", db=db),
                client=client,
            )

            self.assertEqual(result["remote_checksum"], "remote-sha")
            self.assertEqual(result["remote_published_at"], "2026-07-13T01:58:12+00:00")
            self.assertEqual(result["remote_snapshot_id"], "20260713T015812Z")
            self.assertEqual(result["remote_generated_by"], "build_master_rdb.py")
            self.assertEqual(result["remote_table_counts"], {"occurrence_dates": 290})


if __name__ == "__main__":
    unittest.main()
