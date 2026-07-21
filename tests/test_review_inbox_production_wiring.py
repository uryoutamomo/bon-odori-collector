import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from io import BytesIO
from pathlib import Path
from unittest import mock

from review_inbox_adapters import production_wiring as wiring
from master_db import file_sha256, init_db
from review_inbox import upsert_inbox_items
from review_inbox_adapters.source_writer import ArtifactState, SourceWriterError


class FakeClientError(Exception):
    def __init__(self, code="NoSuchKey", status=404):
        self.response = {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }
        super().__init__(code)


class FakeS3:
    def __init__(self):
        self.objects = {}

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise FakeClientError()
        return {"Body": BytesIO(self.objects[(Bucket, Key)])}

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise FakeClientError()
        return {"ContentLength": len(self.objects[(Bucket, Key)])}

    def download_file(self, Bucket, Key, Filename):
        if (Bucket, Key) not in self.objects:
            raise FakeClientError()
        Path(Filename).write_bytes(self.objects[(Bucket, Key)])

    def upload_file(self, Filename, Bucket, Key, ExtraArgs=None):
        self.objects[(Bucket, Key)] = Path(Filename).read_bytes()


def make_master(path):
    conn = init_db(path)
    conn.commit()
    conn.close()


def seed_remote(client, database, snapshot_id="R1-snapshot"):
    checksum = file_sha256(database)
    client.objects[("bucket", "master-rdb/latest/bon_odori_master.sqlite")] = Path(
        database
    ).read_bytes()
    client.objects[("bucket", "master-rdb/latest/bon_odori_master_manifest.json")] = json.dumps(
        {
            "database_checksum": checksum,
            "artifact": {"snapshot_id": snapshot_id},
        }
    ).encode("utf-8")
    return checksum


class ReviewInboxProductionWiringTest(unittest.TestCase):
    def test_s3_artifact_store_fetches_and_cas_publishes_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            remote_db = tmp / "remote.sqlite"
            fetched_db = tmp / "fetched.sqlite"
            make_master(remote_db)
            client = FakeS3()
            rstart = seed_remote(client, remote_db)
            store = wiring.MasterDbS3ArtifactStore(
                bucket="bucket",
                prefix="master-rdb",
                client=client,
            )

            self.assertEqual(store.status(), ArtifactState(rstart, "R1-snapshot"))
            store.fetch(fetched_db)
            with closing(sqlite3.connect(fetched_db)) as conn:
                upsert_inbox_items(
                    conn,
                    [{
                        "kind": "occurrence_creation",
                        "title": "canary",
                        "source_id": "fixture",
                        "source_key": "one",
                    }],
                )
                conn.commit()
            expected_rend = file_sha256(fetched_db)
            state = store.publish(fetched_db, expected_remote_checksum=rstart)

        self.assertEqual(state.checksum, expected_rend)
        self.assertNotEqual(state.snapshot_id, "R1-snapshot")
        self.assertEqual(
            hashlib.sha256(
                client.objects[("bucket", "master-rdb/latest/bon_odori_master.sqlite")]
            ).hexdigest(),
            expected_rend,
        )

    def test_s3_adapter_hardcodes_force_false_and_cas_expectation(self):
        store = wiring.MasterDbS3ArtifactStore(
            bucket="bucket",
            prefix="master-rdb",
            client=object(),
        )
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "candidate.sqlite"
            db.write_bytes(b"candidate")
            with mock.patch.object(
                wiring.s3_artifact,
                "publish",
                return_value={"database_checksum": "b" * 64},
            ) as publish, mock.patch.object(
                wiring.MasterDbS3ArtifactStore,
                "status",
                return_value=ArtifactState("b" * 64, "R2"),
            ):
                state = store.publish(db, expected_remote_checksum="a" * 64)

        args = publish.call_args.args[0]
        self.assertFalse(args.force)
        self.assertEqual(args.expect_remote_checksum, "a" * 64)
        self.assertEqual(state, ArtifactState("b" * 64, "R2"))

    def test_s3_adapter_rejects_incomplete_remote_status(self):
        store = wiring.MasterDbS3ArtifactStore(
            bucket="bucket",
            prefix="master-rdb",
            client=object(),
        )
        with mock.patch.object(
            wiring.s3_artifact,
            "status",
            return_value={"remote_exists": True, "remote_checksum": "a" * 64},
        ):
            with self.assertRaisesRegex(SourceWriterError, "status is incomplete"):
                store.status()

    def test_public_projection_digest_ignores_review_inbox_only_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            make_master(db)
            with mock.patch("export_public_events.load_public_date_predictions_for_export", return_value={}):
                before = wiring.public_projection_digest(db, today="2026-07-18")
                with closing(sqlite3.connect(db)) as conn:
                    upsert_inbox_items(
                        conn,
                        [{
                            "kind": "occurrence_creation",
                            "title": "canary",
                            "source_id": "fixture",
                            "source_key": "one",
                        }],
                    )
                    conn.commit()
                after = wiring.public_projection_digest(db, today="2026-07-18")

        self.assertEqual(before, after)
        self.assertEqual(len(before), 64)


if __name__ == "__main__":
    unittest.main()
