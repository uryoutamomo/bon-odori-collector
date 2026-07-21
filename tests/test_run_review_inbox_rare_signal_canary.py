import hashlib
import json
import sqlite3
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from master_db import init_db
from review_inbox import inbox_rows
from review_inbox_adapters.source_writer import ArtifactState, CasConflictError, SourceWriterError
from run_review_inbox_rare_signal_canary import CONFIRM, run_canary


FIXTURE = Path(__file__).parent / "fixtures" / "rare_signal_backcheck_two_examples.json"
SOURCE_KEY = "new_event_candidate|event|x-status:2000000000000000001"
JST = ZoneInfo("Asia/Tokyo")
ENABLED_ENV = {
    "REVIEW_INBOX_DUAL_WRITE_MODE": "canary",
    "REVIEW_INBOX_CAS_PUBLISH_ENABLED": "true",
    "REVIEW_INBOX_READER_MODE": "legacy",
    "REVIEW_INBOX_LEGACY_WRITER_ENABLED": "true",
}


class FakeArtifactStore:
    def __init__(self, database: Path):
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
        self.snapshot_id = f"R{self.publish_calls + 1}"
        return self.status()


def make_master(path: Path) -> None:
    conn = init_db(path)
    conn.commit()
    conn.close()


def fixed_public_digest(_database, *, today):
    return hashlib.sha256(today.encode("utf-8")).hexdigest()


def args_for(tmp: str, *, rstart: str = "a" * 64, suffix: str = "first", **overrides):
    values = {
        "input": FIXTURE,
        "canary_source_key": SOURCE_KEY,
        "snapshot_out": Path(tmp) / f"snapshot-{suffix}.json",
        "report_out": Path(tmp) / f"report-{suffix}.json",
        "observation_id": f"b2-3-{suffix}",
        "expect_rstart_checksum": rstart,
        "public_today": "2026-07-19",
        "bucket": "unused-in-test",
        "prefix": "master-rdb",
        "work_dir": Path(tmp) / "work",
        "execute": True,
        "confirm": CONFIRM,
    }
    values.update(overrides)
    return Namespace(**values)


class RunReviewInboxRareSignalCanaryTest(unittest.TestCase):
    def test_default_off_stops_before_snapshot_or_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(tmp, execute=False, confirm="")
            stores = []
            with self.assertRaisesRegex(SourceWriterError, "execution is off"):
                run_canary(
                    args,
                    environ={},
                    now=datetime(2026, 7, 19, 12, 0, tzinfo=JST),
                    store_factory=lambda _args: stores.append(object()),
                )

            self.assertFalse(Path(args.snapshot_out).exists())
            self.assertFalse(Path(args.report_out).exists())
            self.assertEqual(stores, [])

    def test_explicit_environment_and_cron_gates_precede_artifact_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(tmp)
            incomplete = dict(ENABLED_ENV)
            incomplete.pop("REVIEW_INBOX_READER_MODE")
            with self.assertRaisesRegex(SourceWriterError, "explicit environment gates"):
                run_canary(
                    args,
                    environ=incomplete,
                    now=datetime(2026, 7, 19, 12, 0, tzinfo=JST),
                    store_factory=lambda _args: self.fail("store must not be created"),
                )
            with self.assertRaisesRegex(SourceWriterError, "17:20-18:00"):
                run_canary(
                    args,
                    environ=ENABLED_ENV,
                    now=datetime(2026, 7, 19, 17, 30, tzinfo=JST),
                    store_factory=lambda _args: self.fail("store must not be created"),
                )

    def test_unknown_source_key_fails_before_artifact_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(tmp, canary_source_key="missing")
            with self.assertRaisesRegex(SourceWriterError, "exactly one item"):
                run_canary(
                    args,
                    environ=ENABLED_ENV,
                    now=datetime(2026, 7, 19, 12, 0, tzinfo=JST),
                    store_factory=lambda _args: self.fail("store must not be created"),
                )

    def test_enabled_canary_freezes_one_item_and_writes_audited_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            make_master(db)
            store = FakeArtifactStore(db)
            args = args_for(tmp, rstart=hashlib.sha256(store.database_bytes).hexdigest())

            report = run_canary(
                args,
                environ=ENABLED_ENV,
                now=datetime(2026, 7, 19, 12, 0, tzinfo=JST),
                store_factory=lambda _args: store,
                digest_function=fixed_public_digest,
            )
            frozen = json.loads(Path(args.snapshot_out).read_text(encoding="utf-8"))
            saved_report = json.loads(Path(args.report_out).read_text(encoding="utf-8"))

        self.assertTrue(report["published"])
        self.assertEqual(store.publish_calls, 1)
        self.assertEqual(store.fetch_calls, 2)
        self.assertEqual(frozen["item_count"], 1)
        self.assertEqual(frozen["selection"], {"mode": "canary", "source_keys": [SOURCE_KEY]})
        self.assertEqual(saved_report["lineage"]["source_id"], "rare_signal")
        self.assertEqual(saved_report["reconciliation"]["summary"]["unmapped_count"], 0)
        self.assertTrue(saved_report["audit"]["public_projection_unchanged"])

    def test_reobservation_preserves_reviewed_lifecycle_and_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            make_master(db)
            store = FakeArtifactStore(db)
            first_args = args_for(
                tmp,
                rstart=hashlib.sha256(store.database_bytes).hexdigest(),
            )
            first = run_canary(
                first_args,
                environ=ENABLED_ENV,
                now=datetime(2026, 7, 19, 12, 0, tzinfo=JST),
                store_factory=lambda _args: store,
                digest_function=fixed_public_digest,
            )

            decided_db = Path(tmp) / "decided.sqlite"
            decided_db.write_bytes(store.database_bytes)
            with sqlite3.connect(decided_db) as conn:
                inbox_id = conn.execute(
                    "SELECT inbox_id FROM review_inbox_items WHERE source_id='rare_signal'"
                ).fetchone()[0]
                conn.execute(
                    """
                    UPDATE review_inbox_items
                    SET status='accepted', decision='accepted', decided_by='内田さん',
                        decided_at='2026-07-19T03:00:00+00:00',
                        closed_at='2026-07-19T03:00:00+00:00',
                        decision_route='domain_stage'
                    WHERE inbox_id=?
                    """,
                    (inbox_id,),
                )
            store.database_bytes = decided_db.read_bytes()
            store.snapshot_id = "R-reviewed"
            second_args = args_for(
                tmp,
                suffix="second",
                rstart=hashlib.sha256(store.database_bytes).hexdigest(),
            )
            second = run_canary(
                second_args,
                environ=ENABLED_ENV,
                now=datetime(2026, 7, 19, 12, 5, tzinfo=JST),
                store_factory=lambda _args: store,
                digest_function=fixed_public_digest,
            )
            verified = Path(tmp) / "verified.sqlite"
            verified.write_bytes(store.database_bytes)
            with sqlite3.connect(verified) as conn:
                row = inbox_rows(conn, status=None)[0]

        self.assertTrue(first["published"])
        self.assertTrue(second["no_op"])
        self.assertFalse(second["published"])
        self.assertEqual(store.publish_calls, 1)
        self.assertEqual(row["decision"], "accepted")
        self.assertEqual(row["decided_by"], "内田さん")
        self.assertEqual(row["decision_route"], "domain_stage")


if __name__ == "__main__":
    unittest.main()
