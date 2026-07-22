import hashlib
import json
import sqlite3
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from master_rdb.master_db import init_db
from review_inbox_adapters.registered_event_investigation_adapter import build_snapshot
from review_inbox_adapters.source_writer import (
    ArtifactState,
    CasConflictError,
    SourceWriterError,
    SourceWriterFlags,
    run_source_shadow,
)
from run_review_inbox_registered_full_shadow import (
    CONFIRM,
    run_registered_full_shadow,
)


ROOT = Path(__file__).resolve().parents[1]
REGISTERED_INPUT = ROOT / "data" / "registered_event_investigation_queue.json"
SHIROKANE_INBOX_ID = "inbox_707cbf17503827d2"
JST = ZoneInfo("Asia/Tokyo")
ENABLED_ENV = {
    "REVIEW_INBOX_DUAL_WRITE_MODE": "bulk",
    "REVIEW_INBOX_CAS_PUBLISH_ENABLED": "true",
    "REVIEW_INBOX_READER_MODE": "legacy",
    "REVIEW_INBOX_LEGACY_WRITER_ENABLED": "true",
}


class FakeArtifactStore:
    def __init__(self, database):
        self.database_bytes = Path(database).read_bytes()
        self.snapshot_id = "R0"
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
        self.snapshot_id = f"R{self.publish_calls}"
        return self.status()


def args_for(tmp, *, rstart="a" * 64, suffix="first", **overrides):
    values = {
        "input": REGISTERED_INPUT,
        "snapshot_out": Path(tmp) / f"snapshot-{suffix}.json",
        "report_out": Path(tmp) / f"report-{suffix}.json",
        "observation_id": f"b1-5-test-{suffix}",
        "expect_rstart_checksum": rstart,
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


def fixed_public_digest(_database, *, today):
    return hashlib.sha256(today.encode("utf-8")).hexdigest()


def seed_shirokane_canary(store, work_dir):
    return run_source_shadow(
        store=store,
        adapted_snapshot=build_snapshot(REGISTERED_INPUT, canary=True),
        observation_id="b1-3b-shirokane-canary-test",
        public_projection_digest=lambda db: fixed_public_digest(db, today="2026-07-18"),
        flags=SourceWriterFlags(
            dual_write_mode="canary",
            cas_publish_enabled=True,
            reader_mode="legacy",
            legacy_writer_enabled=True,
        ),
        work_dir=Path(work_dir),
        expected_rstart_checksum=store.status().checksum,
    )


class RunReviewInboxRegisteredFullShadowTest(unittest.TestCase):
    def test_default_execute_off_stops_before_snapshot_or_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(tmp, execute=False, confirm="")
            stores = []
            with self.assertRaisesRegex(SourceWriterError, "execution is off"):
                run_registered_full_shadow(
                    args,
                    environ={},
                    now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                    store_factory=lambda _args: stores.append(object()),
                )

            self.assertFalse(Path(args.snapshot_out).exists())
            self.assertFalse(Path(args.report_out).exists())
            self.assertEqual(stores, [])

    def test_confirmation_and_all_bulk_environment_gates_are_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            cases = (
                ({"confirm": "wrong"}, ENABLED_ENV, "--confirm must be exactly"),
                (
                    {},
                    {
                        key: value
                        for key, value in ENABLED_ENV.items()
                        if key != "REVIEW_INBOX_READER_MODE"
                    },
                    "explicit environment gates",
                ),
                (
                    {},
                    {**ENABLED_ENV, "REVIEW_INBOX_DUAL_WRITE_MODE": "canary"},
                    "must be explicitly set to bulk",
                ),
                (
                    {},
                    {**ENABLED_ENV, "REVIEW_INBOX_CAS_PUBLISH_ENABLED": "false"},
                    "CAS publication is off",
                ),
                ({}, {**ENABLED_ENV, "REVIEW_INBOX_READER_MODE": "inbox"}, "reader"),
                (
                    {},
                    {**ENABLED_ENV, "REVIEW_INBOX_LEGACY_WRITER_ENABLED": "false"},
                    "reader/writer flags",
                ),
            )
            for overrides, environ, message in cases:
                with self.subTest(message=message), self.assertRaisesRegex(
                    SourceWriterError, message
                ):
                    run_registered_full_shadow(
                        args_for(tmp, **overrides),
                        environ=environ,
                        now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                        store_factory=lambda _args: self.fail("store must not be created"),
                    )

    def test_cron_fixed_inputs_and_existing_evidence_fail_before_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SourceWriterError, "17:20-18:00"):
                run_registered_full_shadow(
                    args_for(tmp),
                    environ=ENABLED_ENV,
                    now=datetime(2026, 7, 18, 17, 30, tzinfo=JST),
                    store_factory=lambda _args: self.fail("store must not be created"),
                )

            for overrides, message in (
                ({"expect_rstart_checksum": "short"}, "64-character SHA-256"),
                ({"public_today": "18-07-2026"}, "YYYY-MM-DD"),
            ):
                with self.subTest(overrides=overrides), self.assertRaisesRegex(
                    SourceWriterError, message
                ):
                    run_registered_full_shadow(
                        args_for(tmp, **overrides),
                        environ=ENABLED_ENV,
                        now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                        store_factory=lambda _args: self.fail("store must not be created"),
                    )

            args = args_for(tmp)
            Path(args.report_out).write_text("existing", encoding="utf-8")
            with self.assertRaisesRegex(SourceWriterError, "refusing to overwrite"):
                run_registered_full_shadow(
                    args,
                    environ=ENABLED_ENV,
                    now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                    store_factory=lambda _args: self.fail("store must not be created"),
                )

    def test_fixed_rstart_mismatch_stops_before_fetch_and_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            make_master(db)
            store = FakeArtifactStore(db)
            with self.assertRaisesRegex(SourceWriterError, "operator-fixed expectation"):
                run_registered_full_shadow(
                    args_for(tmp, rstart="f" * 64),
                    environ=ENABLED_ENV,
                    now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                    store_factory=lambda _args: store,
                    digest_function=fixed_public_digest,
                )

            self.assertEqual(store.status_calls, 1)
            self.assertEqual(store.fetch_calls, 0)
            self.assertEqual(store.publish_calls, 0)

    def test_real_full_input_retains_shirokane_and_adds_remaining_78(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            make_master(db)
            store = FakeArtifactStore(db)
            seed_shirokane_canary(store, Path(tmp) / "canary-work")
            args = args_for(tmp, rstart=hashlib.sha256(store.database_bytes).hexdigest())

            report = run_registered_full_shadow(
                args,
                environ=ENABLED_ENV,
                now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                store_factory=lambda _args: store,
                digest_function=fixed_public_digest,
            )
            frozen = json.loads(Path(args.snapshot_out).read_text(encoding="utf-8"))
            remote = Path(tmp) / "remote.sqlite"
            remote.write_bytes(store.database_bytes)
            conn = sqlite3.connect(remote)
            try:
                row_count = conn.execute(
                    "SELECT COUNT(*) FROM review_inbox_items "
                    "WHERE source_id = 'registered_event_investigation'"
                ).fetchone()[0]
                null_lifecycle_count = conn.execute(
                    "SELECT COUNT(*) FROM review_inbox_items "
                    "WHERE source_id = 'registered_event_investigation' "
                    "AND status = 'pending' AND decision IS NULL AND decided_by IS NULL "
                    "AND decided_at IS NULL AND closed_at IS NULL AND decision_route IS NULL"
                ).fetchone()[0]
                shirokane = conn.execute(
                    "SELECT last_seen_at, status, decision FROM review_inbox_items "
                    "WHERE inbox_id = ?",
                    (SHIROKANE_INBOX_ID,),
                ).fetchone()
            finally:
                conn.close()

        self.assertTrue(report["published"])
        self.assertFalse(report["no_op"])
        self.assertEqual(report["reconciliation"]["summary"]["seen_count"], 79)
        self.assertEqual(report["reconciliation"]["summary"]["changed_count"], 78)
        self.assertEqual(report["reconciliation"]["summary"]["unchanged_count"], 1)
        self.assertEqual(report["reconciliation"]["summary"]["stale_candidate_count"], 0)
        self.assertEqual(report["reconciliation"]["summary"]["unmapped_count"], 0)
        self.assertTrue(report["parity"]["summary"]["parity"])
        self.assertEqual(report["parity"]["summary"]["expected_count"], 79)
        self.assertTrue(report["audit"]["domain_table_counts_unchanged"])
        self.assertTrue(report["audit"]["public_projection_unchanged"])
        self.assertEqual(frozen["item_count"], 79)
        self.assertEqual(frozen["selection"]["mode"], "all")
        self.assertEqual(len(frozen["selection"]["source_keys"]), 79)
        self.assertEqual(frozen["scope_counts"], {"future": 79})
        self.assertEqual(
            frozen["kind_counts"],
            {
                "current_year_confirmation": 55,
                "occurrence_creation": 17,
                "venue_review": 7,
            },
        )
        self.assertEqual(row_count, 79)
        self.assertEqual(null_lifecycle_count, 79)
        self.assertEqual(shirokane, ("b1-3b-shirokane-canary-test", "pending", None))

    def test_second_full_run_is_no_op_with_79_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            make_master(db)
            store = FakeArtifactStore(db)
            first = args_for(tmp, rstart=hashlib.sha256(store.database_bytes).hexdigest())
            run_registered_full_shadow(
                first,
                environ=ENABLED_ENV,
                now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                store_factory=lambda _args: store,
                digest_function=fixed_public_digest,
            )
            second = args_for(
                tmp,
                suffix="second",
                rstart=hashlib.sha256(store.database_bytes).hexdigest(),
            )
            report = run_registered_full_shadow(
                second,
                environ=ENABLED_ENV,
                now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                store_factory=lambda _args: store,
                digest_function=fixed_public_digest,
            )

        self.assertTrue(report["no_op"])
        self.assertFalse(report["published"])
        self.assertEqual(store.publish_calls, 1)
        self.assertEqual(report["reconciliation"]["summary"]["changed_count"], 0)
        self.assertEqual(report["reconciliation"]["summary"]["unchanged_count"], 79)
        self.assertTrue(report["parity"]["summary"]["parity"])


if __name__ == "__main__":
    unittest.main()
