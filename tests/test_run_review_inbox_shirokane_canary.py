import hashlib
import json
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from master_rdb.master_db import init_db
from review_inbox_adapters.source_writer import ArtifactState, CasConflictError, SourceWriterError
from run_review_inbox_shirokane_canary import CONFIRM, run_canary


FIXTURE = Path(__file__).parent / "fixtures" / "registered_event_investigation_shirokane.json"
JST = ZoneInfo("Asia/Tokyo")
ENABLED_ENV = {
    "REVIEW_INBOX_DUAL_WRITE_MODE": "canary",
    "REVIEW_INBOX_CAS_PUBLISH_ENABLED": "true",
    "REVIEW_INBOX_READER_MODE": "legacy",
    "REVIEW_INBOX_LEGACY_WRITER_ENABLED": "true",
}


class FakeArtifactStore:
    def __init__(self, database):
        self.database_bytes = Path(database).read_bytes()
        self.snapshot_id = "R1"
        self.status_calls = 0
        self.fetch_calls = 0
        self.publish_calls = 0

    def status(self):
        self.status_calls += 1
        return ArtifactState(hashlib.sha256(self.database_bytes).hexdigest(), self.snapshot_id)

    def fetch(self, destination):
        self.fetch_calls += 1
        Path(destination).write_bytes(self.database_bytes)

    def publish(self, source, *, expected_remote_checksum):
        current = hashlib.sha256(self.database_bytes).hexdigest()
        if current != expected_remote_checksum:
            raise CasConflictError("fake conflict")
        self.publish_calls += 1
        self.database_bytes = Path(source).read_bytes()
        self.snapshot_id = "R2"
        return self.status()


def args_for(tmp, *, rstart="a" * 64, **overrides):
    values = {
        "input": FIXTURE,
        "snapshot_out": Path(tmp) / "snapshot.json",
        "report_out": Path(tmp) / "report.json",
        "observation_id": "b1-3b-test-run",
        "expect_rstart_checksum": rstart,
        "public_target_year": 2026,
        "public_today": "2026-07-18",
        "bucket": "unused-in-test",
        "prefix": "master-rdb",
        "work_dir": Path(tmp) / "work",
        "execute": True,
        "confirm": CONFIRM,
    }
    values.update(overrides)
    return Namespace(**values)


def make_master(path):
    conn = init_db(path)
    conn.commit()
    conn.close()


def fixed_public_digest(_database, *, target_year, today):
    return hashlib.sha256(today.encode("utf-8")).hexdigest()


class RunReviewInboxShirokaneCanaryTest(unittest.TestCase):
    def test_default_execute_off_stops_before_snapshot_or_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(tmp, execute=False, confirm="")
            stores = []
            with self.assertRaisesRegex(SourceWriterError, "execution is off"):
                run_canary(
                    args,
                    environ={},
                    now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                    store_factory=lambda _args: stores.append(object()),
                )

            self.assertFalse(Path(args.snapshot_out).exists())
            self.assertFalse(Path(args.report_out).exists())
            self.assertEqual(stores, [])

    def test_all_four_environment_gates_must_be_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(tmp)
            incomplete = dict(ENABLED_ENV)
            incomplete.pop("REVIEW_INBOX_READER_MODE")
            with self.assertRaisesRegex(SourceWriterError, "explicit environment gates"):
                run_canary(
                    args,
                    environ=incomplete,
                    now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                    store_factory=lambda _args: self.fail("store must not be created"),
                )

            self.assertFalse(Path(args.snapshot_out).exists())

    def test_cron_window_is_rejected_before_snapshot_or_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(tmp)
            with self.assertRaisesRegex(SourceWriterError, "17:20-18:00"):
                run_canary(
                    args,
                    environ=ENABLED_ENV,
                    now=datetime(2026, 7, 18, 17, 30, tzinfo=JST),
                    store_factory=lambda _args: self.fail("store must not be created"),
                )

            self.assertFalse(Path(args.snapshot_out).exists())

    def test_invalid_public_date_and_existing_evidence_fail_before_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            invalid = args_for(tmp, public_today="18-07-2026")
            with self.assertRaisesRegex(SourceWriterError, "YYYY-MM-DD"):
                run_canary(
                    invalid,
                    environ=ENABLED_ENV,
                    now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                    store_factory=lambda _args: self.fail("store must not be created"),
                )

            existing = args_for(tmp)
            Path(existing.report_out).write_text("existing", encoding="utf-8")
            with self.assertRaisesRegex(SourceWriterError, "refusing to overwrite"):
                run_canary(
                    existing,
                    environ=ENABLED_ENV,
                    now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                    store_factory=lambda _args: self.fail("store must not be created"),
                )

    def test_enabled_canary_freezes_one_item_runs_and_writes_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            make_master(db)
            store = FakeArtifactStore(db)
            args = args_for(
                tmp,
                rstart=hashlib.sha256(store.database_bytes).hexdigest(),
            )

            report = run_canary(
                args,
                environ=ENABLED_ENV,
                now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                store_factory=lambda _args: store,
                digest_function=fixed_public_digest,
            )
            frozen = json.loads(Path(args.snapshot_out).read_text(encoding="utf-8"))
            saved_report = json.loads(Path(args.report_out).read_text(encoding="utf-8"))

        self.assertTrue(report["published"])
        self.assertEqual(store.publish_calls, 1)
        self.assertEqual(store.fetch_calls, 2)
        self.assertEqual(frozen["item_count"], 1)
        self.assertEqual(frozen["selection"]["mode"], "canary")
        self.assertEqual(frozen["write_mode"], "canary_dual_write_explicit_gate")
        self.assertEqual(
            frozen["items"][0]["source_key"],
            "evtinv_d7b5f534c8b3ddd8",
        )
        self.assertEqual(saved_report["rend"]["snapshot_id"], "R2")
        self.assertTrue(saved_report["entrypoint"]["cron_window_checked"])

    def test_fixed_rstart_mismatch_stops_before_fetch_and_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            make_master(db)
            store = FakeArtifactStore(db)
            args = args_for(tmp, rstart="f" * 64)

            with self.assertRaisesRegex(SourceWriterError, "operator-fixed expectation"):
                run_canary(
                    args,
                    environ=ENABLED_ENV,
                    now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                    store_factory=lambda _args: store,
                    digest_function=fixed_public_digest,
                )

            self.assertEqual(store.status_calls, 1)
            self.assertEqual(store.fetch_calls, 0)
            self.assertEqual(store.publish_calls, 0)
            self.assertFalse(Path(args.report_out).exists())


if __name__ == "__main__":
    unittest.main()
