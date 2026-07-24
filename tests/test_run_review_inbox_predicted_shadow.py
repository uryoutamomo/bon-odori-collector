import hashlib
import sqlite3
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from master_rdb.master_db import init_db
from review_inbox_adapters.source_writer import ArtifactState, CasConflictError, SourceWriterError
from run_review_inbox_predicted_shadow import SOURCE_CONFIGS, run_predicted_shadow


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


def args_for(tmp, *, source="research", rstart="a" * 64, suffix="first", **overrides):
    values = {
        "source": source,
        "input": None,
        "snapshot_out": Path(tmp) / f"{source}-snapshot-{suffix}.json",
        "report_out": Path(tmp) / f"{source}-report-{suffix}.json",
        "observation_id": f"b1-6-{source}-{suffix}",
        "expect_rstart_checksum": rstart,
        "public_target_year": 2026,
        "public_today": "2026-07-18",
        "bucket": "unused-in-test",
        "prefix": "master-rdb",
        "work_dir": Path(tmp) / "work",
        "execute": True,
        "confirm": SOURCE_CONFIGS[source]["confirm"],
    }
    values.update(overrides)
    return Namespace(**values)


def make_master(path):
    conn = init_db(path)
    conn.commit()
    conn.close()


def fixed_public_digest(_database, *, target_year, today):
    return hashlib.sha256(today.encode("utf-8")).hexdigest()


class RunReviewInboxPredictedShadowTest(unittest.TestCase):
    def test_each_source_is_default_off_before_snapshot_or_store(self):
        for source in SOURCE_CONFIGS:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as tmp:
                args = args_for(tmp, source=source, execute=False, confirm="")
                stores = []
                with self.assertRaisesRegex(SourceWriterError, "execution is off"):
                    run_predicted_shadow(
                        args,
                        environ={},
                        now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                        store_factory=lambda _args: stores.append(object()),
                    )
                self.assertFalse(Path(args.snapshot_out).exists())
                self.assertEqual(stores, [])

    def test_source_specific_confirm_and_bulk_gates_are_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            cases = (
                (args_for(tmp, confirm="wrong"), ENABLED_ENV, "--confirm must be exactly"),
                (
                    args_for(tmp),
                    {
                        key: value
                        for key, value in ENABLED_ENV.items()
                        if key != "REVIEW_INBOX_READER_MODE"
                    },
                    "explicit environment gates",
                ),
                (
                    args_for(tmp),
                    {**ENABLED_ENV, "REVIEW_INBOX_DUAL_WRITE_MODE": "canary"},
                    "must be explicitly set to bulk",
                ),
                (
                    args_for(tmp),
                    {**ENABLED_ENV, "REVIEW_INBOX_CAS_PUBLISH_ENABLED": "false"},
                    "CAS publication is off",
                ),
            )
            for args, environ, message in cases:
                with self.subTest(message=message), self.assertRaisesRegex(
                    SourceWriterError, message
                ):
                    run_predicted_shadow(
                        args,
                        environ=environ,
                        now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                        store_factory=lambda _args: self.fail("store must not be created"),
                    )

    def test_cron_bad_rstart_and_existing_evidence_stop_before_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SourceWriterError, "17:20-18:00"):
                run_predicted_shadow(
                    args_for(tmp),
                    environ=ENABLED_ENV,
                    now=datetime(2026, 7, 18, 17, 30, tzinfo=JST),
                    store_factory=lambda _args: self.fail("store must not be created"),
                )
            with self.assertRaisesRegex(SourceWriterError, "64-character SHA-256"):
                run_predicted_shadow(
                    args_for(tmp, expect_rstart_checksum="short"),
                    environ=ENABLED_ENV,
                    now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                    store_factory=lambda _args: self.fail("store must not be created"),
                )
            args = args_for(tmp)
            Path(args.report_out).write_text("existing", encoding="utf-8")
            with self.assertRaisesRegex(SourceWriterError, "refusing to overwrite"):
                run_predicted_shadow(
                    args,
                    environ=ENABLED_ENV,
                    now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                    store_factory=lambda _args: self.fail("store must not be created"),
                )

    def test_rstart_mismatch_stops_before_fetch_and_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            make_master(db)
            store = FakeArtifactStore(db)
            with self.assertRaisesRegex(SourceWriterError, "operator-fixed expectation"):
                run_predicted_shadow(
                    args_for(tmp, rstart="f" * 64),
                    environ=ENABLED_ENV,
                    now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                    store_factory=lambda _args: store,
                    digest_function=fixed_public_digest,
                )
            self.assertEqual(store.status_calls, 1)
            self.assertEqual(store.fetch_calls, 0)
            self.assertEqual(store.publish_calls, 0)

    def test_real_sources_run_separately_with_twenty_pending_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            make_master(db)
            store = FakeArtifactStore(db)
            reports = {}
            for source in ("research", "date-review"):
                args = args_for(
                    tmp,
                    source=source,
                    rstart=hashlib.sha256(store.database_bytes).hexdigest(),
                )
                reports[source] = run_predicted_shadow(
                    args,
                    environ=ENABLED_ENV,
                    now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                    store_factory=lambda _args: store,
                    digest_function=fixed_public_digest,
                )

            remote = Path(tmp) / "remote.sqlite"
            remote.write_bytes(store.database_bytes)
            conn = sqlite3.connect(remote)
            try:
                source_counts = dict(
                    conn.execute(
                        "SELECT source_id, COUNT(*) FROM review_inbox_items GROUP BY source_id"
                    ).fetchall()
                )
                lifecycle_count = conn.execute(
                    "SELECT COUNT(*) FROM review_inbox_items "
                    "WHERE kind='predicted_date' AND time_scope='future' AND status='pending' "
                    "AND decision IS NULL AND decided_by IS NULL AND decided_at IS NULL "
                    "AND closed_at IS NULL AND decision_route IS NULL"
                ).fetchone()[0]
                distinct_ids = conn.execute(
                    "SELECT COUNT(DISTINCT inbox_id) FROM review_inbox_items"
                ).fetchone()[0]
            finally:
                conn.close()

        self.assertEqual(
            source_counts,
            {"predicted_occurrence_research": 8, "predicted_occurrence_date_review": 12},
        )
        self.assertEqual(lifecycle_count, 20)
        self.assertEqual(distinct_ids, 20)
        self.assertEqual(store.publish_calls, 2)
        for source, count in (("research", 8), ("date-review", 12)):
            report = reports[source]
            self.assertTrue(report["published"])
            self.assertTrue(report["parity"]["summary"]["parity"])
            self.assertEqual(report["parity"]["summary"]["expected_count"], count)
            self.assertEqual(report["reconciliation"]["summary"]["unmapped_count"], 0)
            self.assertTrue(report["audit"]["domain_table_counts_unchanged"])
            self.assertTrue(report["audit"]["public_projection_unchanged"])

    def test_same_source_second_run_is_no_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            make_master(db)
            store = FakeArtifactStore(db)
            first = args_for(tmp, rstart=hashlib.sha256(store.database_bytes).hexdigest())
            run_predicted_shadow(
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
            report = run_predicted_shadow(
                second,
                environ=ENABLED_ENV,
                now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                store_factory=lambda _args: store,
                digest_function=fixed_public_digest,
            )

        self.assertTrue(report["no_op"])
        self.assertFalse(report["published"])
        self.assertEqual(store.publish_calls, 1)
        self.assertEqual(report["reconciliation"]["summary"]["unchanged_count"], 8)


if __name__ == "__main__":
    unittest.main()
