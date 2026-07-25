import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from argparse import Namespace
from io import BytesIO
from pathlib import Path

import master_rdb.master_db as master_db
import master_rdb.s3_artifact as artifact
from master_rdb.master_db import connect_existing, file_sha256
from review_inbox import INBOX_SCHEMA


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
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO sample(name) VALUES ('bon')")
        conn.commit()


# 2026-07-24 に本番を上書きした v1 系統の inbox を再現する。
# v2 の8列 (time_scope / decision / decided_by / decided_at / closed_at /
# decision_route / source_payload_hash / last_seen_at) だけが無い17列。
INBOX_SCHEMA_V1 = """
CREATE TABLE review_inbox_items (
  inbox_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  domain TEXT NOT NULL,
  priority_label TEXT,
  priority_score REAL,
  title TEXT NOT NULL,
  event_name TEXT,
  venue TEXT,
  event_year INTEGER,
  source_id TEXT NOT NULL,
  source_key TEXT NOT NULL,
  source_url TEXT,
  recommended_action TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


def make_db_with_inbox(path, schema_version):
    make_db(path)
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(INBOX_SCHEMA if schema_version == 2 else INBOX_SCHEMA_V1)
        conn.commit()


def publish_args(db, manifest, **overrides):
    args = {
        "bucket": "bucket",
        "prefix": "master-rdb",
        "db": db,
        "manifest": manifest,
        "snapshot_id": "snap1",
        "expect_remote_checksum": "",
        "force": False,
    }
    args.update(overrides)
    return Namespace(**args)


def seed_remote(client, checksum, inbox_schema_version=None):
    payload = {"database_checksum": checksum}
    if inbox_schema_version is not None:
        payload["review_inbox_schema_version"] = inbox_schema_version
    client.objects[("bucket", "master-rdb/latest/bon_odori_master_manifest.json")] = json.dumps(
        payload, ensure_ascii=False
    ).encode("utf-8")


class MasterDbS3ArtifactTest(unittest.TestCase):
    def test_connect_existing_does_not_create_missing_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.sqlite"

            with self.assertRaises(SystemExit):
                connect_existing(missing)

            self.assertFalse(missing.exists())

    def test_connect_existing_closes_connection_after_context_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            make_db(db)

            with connect_existing(db) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM sample").fetchone()[0], 1)

            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")

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


class PublishInboxSchemaGuardTest(unittest.TestCase):
    def test_publish_records_inbox_schema_version_in_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db = tmp / "master.sqlite"
            manifest = tmp / "manifest.json"
            make_db_with_inbox(db, 2)
            manifest.write_text("{}", encoding="utf-8")
            client = FakeS3()

            artifact.publish(publish_args(db, manifest), client=client)

            for key in (
                "master-rdb/latest/bon_odori_master_manifest.json",
                "master-rdb/snapshots/snap1/bon_odori_master_manifest.json",
            ):
                uploaded = json.loads(client.objects[("bucket", key)])
                self.assertEqual(uploaded["review_inbox_schema_version"], 2)

    def test_publish_records_version_one_for_downgraded_inbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db = tmp / "master.sqlite"
            manifest = tmp / "manifest.json"
            make_db_with_inbox(db, 1)
            manifest.write_text("{}", encoding="utf-8")
            client = FakeS3()

            artifact.publish(publish_args(db, manifest), client=client)

            uploaded = json.loads(client.objects[("bucket", "master-rdb/latest/bon_odori_master_manifest.json")])
            self.assertEqual(uploaded["review_inbox_schema_version"], 1)

    def test_publish_blocks_inbox_schema_downgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db = tmp / "master.sqlite"
            manifest = tmp / "manifest.json"
            make_db_with_inbox(db, 1)
            manifest.write_text("{}", encoding="utf-8")
            client = FakeS3()
            seed_remote(client, "remote-sha", inbox_schema_version=2)

            # チェックサムは合わせておく。止めたのが CAS ではなく退行ガードだと確かめるため。
            with self.assertRaises(SystemExit) as caught:
                artifact.publish(
                    publish_args(db, manifest, expect_remote_checksum="remote-sha"),
                    client=client,
                )

            self.assertIn("review inbox schema downgrade blocked", str(caught.exception))
            self.assertIn("local=1 remote=2", str(caught.exception))
            self.assertNotIn(
                ("bucket", "master-rdb/latest/bon_odori_master.sqlite"), client.objects
            )

    def test_force_allows_intentional_inbox_schema_downgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db = tmp / "master.sqlite"
            manifest = tmp / "manifest.json"
            make_db_with_inbox(db, 1)
            manifest.write_text("{}", encoding="utf-8")
            client = FakeS3()
            seed_remote(client, "remote-sha", inbox_schema_version=2)

            artifact.publish(publish_args(db, manifest, force=True), client=client)

            self.assertIn(("bucket", "master-rdb/latest/bon_odori_master.sqlite"), client.objects)

    def test_publish_allows_inbox_schema_upgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db = tmp / "master.sqlite"
            manifest = tmp / "manifest.json"
            make_db_with_inbox(db, 2)
            manifest.write_text("{}", encoding="utf-8")
            client = FakeS3()
            seed_remote(client, "remote-sha", inbox_schema_version=1)

            artifact.publish(
                publish_args(db, manifest, expect_remote_checksum="remote-sha"),
                client=client,
            )

            uploaded = json.loads(client.objects[("bucket", "master-rdb/latest/bon_odori_master_manifest.json")])
            self.assertEqual(uploaded["review_inbox_schema_version"], 2)

    def test_publish_allows_when_remote_manifest_predates_the_guard(self):
        # このガードより前に publish された manifest にはキーが無い。
        # 比較できない一回目を止めると定時 publish が落ちるので通す。
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db = tmp / "master.sqlite"
            manifest = tmp / "manifest.json"
            make_db_with_inbox(db, 1)
            manifest.write_text("{}", encoding="utf-8")
            client = FakeS3()
            seed_remote(client, "remote-sha")

            artifact.publish(
                publish_args(db, manifest, expect_remote_checksum="remote-sha"),
                client=client,
            )

            self.assertIn(("bucket", "master-rdb/latest/bon_odori_master.sqlite"), client.objects)

    def test_local_inbox_schema_version_does_not_create_the_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            make_db(db)

            self.assertEqual(artifact.local_inbox_schema_version(db), 1)

            with closing(sqlite3.connect(db)) as conn:
                tables = {
                    row[0]
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
            self.assertNotIn("review_inbox_items", tables)

    def test_local_inbox_schema_version_is_none_for_missing_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(artifact.local_inbox_schema_version(Path(tmp) / "missing.sqlite"))


if __name__ == "__main__":
    unittest.main()
