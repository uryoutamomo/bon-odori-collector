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
from review_inbox_adapters.source_writer import ArtifactState, CasConflictError, SourceWriterError
from run_review_inbox_official_bulk_shadow import (
    CONFIRM,
    run_official_bulk_shadow,
)


ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_INPUT = ROOT / "data" / "official_source_review_candidates.json"
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


def args_for(tmp, *, rstart="a" * 64, suffix="first", **overrides):
    values = {
        "input": OFFICIAL_INPUT,
        "snapshot_out": Path(tmp) / f"snapshot-{suffix}.json",
        "report_out": Path(tmp) / f"report-{suffix}.json",
        "observation_id": f"b1-4b-test-{suffix}",
        "expect_rstart_checksum": rstart,
        "public_today": "2026-07-18",
        "target_year": 2026,
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


class RunReviewInboxOfficialBulkShadowTest(unittest.TestCase):
    def test_default_execute_off_stops_before_snapshot_or_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(tmp, execute=False, confirm="")
            stores = []
            with self.assertRaisesRegex(SourceWriterError, "execution is off"):
                run_official_bulk_shadow(
                    args,
                    environ={},
                    now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                    store_factory=lambda _args: stores.append(object()),
                )

            self.assertFalse(Path(args.snapshot_out).exists())
            self.assertFalse(Path(args.report_out).exists())
            self.assertEqual(stores, [])

    def test_exact_confirmation_and_all_four_environment_gates_are_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(tmp, confirm="wrong")
            with self.assertRaisesRegex(SourceWriterError, "--confirm must be exactly"):
                run_official_bulk_shadow(
                    args,
                    environ=ENABLED_ENV,
                    now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                    store_factory=lambda _args: self.fail("store must not be created"),
                )

            args = args_for(tmp)
            incomplete = dict(ENABLED_ENV)
            incomplete.pop("REVIEW_INBOX_READER_MODE")
            with self.assertRaisesRegex(SourceWriterError, "explicit environment gates"):
                run_official_bulk_shadow(
                    args,
                    environ=incomplete,
                    now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                    store_factory=lambda _args: self.fail("store must not be created"),
                )

    def test_bulk_mode_and_legacy_safety_gates_are_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, value, message in (
                ("REVIEW_INBOX_DUAL_WRITE_MODE", "canary", "must be explicitly set to bulk"),
                ("REVIEW_INBOX_CAS_PUBLISH_ENABLED", "false", "CAS publication is off"),
                ("REVIEW_INBOX_READER_MODE", "inbox", "reader"),
                ("REVIEW_INBOX_LEGACY_WRITER_ENABLED", "false", "reader/writer flags"),
            ):
                environ = dict(ENABLED_ENV)
                environ[name] = value
                with self.subTest(name=name), self.assertRaisesRegex(SourceWriterError, message):
                    run_official_bulk_shadow(
                        args_for(tmp),
                        environ=environ,
                        now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                        store_factory=lambda _args: self.fail("store must not be created"),
                    )

    def test_cron_window_and_existing_evidence_are_rejected_before_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(tmp)
            with self.assertRaisesRegex(SourceWriterError, "17:20-18:00"):
                run_official_bulk_shadow(
                    args,
                    environ=ENABLED_ENV,
                    now=datetime(2026, 7, 18, 17, 30, tzinfo=JST),
                    store_factory=lambda _args: self.fail("store must not be created"),
                )

            Path(args.report_out).write_text("existing", encoding="utf-8")
            with self.assertRaisesRegex(SourceWriterError, "refusing to overwrite"):
                run_official_bulk_shadow(
                    args,
                    environ=ENABLED_ENV,
                    now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                    store_factory=lambda _args: self.fail("store must not be created"),
                )

    def test_invalid_fixed_inputs_are_rejected_before_snapshot_or_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            cases = (
                ({"expect_rstart_checksum": "short"}, "64-character SHA-256"),
                ({"public_today": "18-07-2026"}, "YYYY-MM-DD"),
                ({"target_year": 1999}, "between 2000 and 2100"),
            )
            for overrides, message in cases:
                with self.subTest(overrides=overrides), self.assertRaisesRegex(
                    SourceWriterError, message
                ):
                    run_official_bulk_shadow(
                        args_for(tmp, **overrides),
                        environ=ENABLED_ENV,
                        now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                        store_factory=lambda _args: self.fail("store must not be created"),
                    )

            self.assertFalse((Path(tmp) / "snapshot-first.json").exists())
            self.assertFalse((Path(tmp) / "report-first.json").exists())

    def test_fixed_rstart_mismatch_stops_before_fetch_and_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            make_master(db)
            store = FakeArtifactStore(db)
            with self.assertRaisesRegex(SourceWriterError, "operator-fixed expectation"):
                run_official_bulk_shadow(
                    args_for(tmp, rstart="f" * 64),
                    environ=ENABLED_ENV,
                    now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                    store_factory=lambda _args: store,
                    digest_function=fixed_public_digest,
                )

            self.assertEqual(store.status_calls, 1)
            self.assertEqual(store.fetch_calls, 0)
            self.assertEqual(store.publish_calls, 0)

    def test_real_official_input_bulk_writes_52_with_zero_diff_parity(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            make_master(db)
            store = FakeArtifactStore(db)
            args = args_for(tmp, rstart=hashlib.sha256(store.database_bytes).hexdigest())

            report = run_official_bulk_shadow(
                args,
                environ=ENABLED_ENV,
                now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                store_factory=lambda _args: store,
                digest_function=fixed_public_digest,
            )
            frozen = json.loads(Path(args.snapshot_out).read_text(encoding="utf-8"))
            saved_report = json.loads(Path(args.report_out).read_text(encoding="utf-8"))

            remote = Path(tmp) / "remote.sqlite"
            remote.write_bytes(store.database_bytes)
            conn = sqlite3.connect(remote)
            try:
                row_count = conn.execute(
                    "SELECT COUNT(*) FROM review_inbox_items WHERE source_id = 'official_source'"
                ).fetchone()[0]
                decided_count = conn.execute(
                    "SELECT COUNT(*) FROM review_inbox_items "
                    "WHERE source_id = 'official_source' AND decision IS NOT NULL"
                ).fetchone()[0]
            finally:
                conn.close()

        self.assertTrue(report["published"])
        self.assertFalse(report["no_op"])
        self.assertEqual(store.publish_calls, 1)
        self.assertEqual(store.fetch_calls, 2)
        self.assertEqual(frozen["item_count"], 52)
        self.assertEqual(frozen["selection"]["mode"], "all")
        self.assertEqual(len(frozen["selection"]["source_keys"]), 52)
        self.assertEqual(frozen["scope_counts"], {"future": 5, "historical": 47})
        self.assertEqual(report["parity"]["summary"]["expected_count"], 52)
        self.assertTrue(report["parity"]["summary"]["parity"])
        self.assertEqual(report["reconciliation"]["summary"]["unmapped_count"], 0)
        self.assertEqual(report["reconciliation"]["summary"]["stale_candidate_count"], 0)
        self.assertTrue(report["audit"]["domain_table_counts_unchanged"])
        self.assertTrue(report["audit"]["public_projection_unchanged"])
        self.assertEqual(saved_report["entrypoint"]["item_count"], 52)
        self.assertEqual(row_count, 52)
        self.assertEqual(decided_count, 0)

    def test_missing_pending_item_is_reported_stale_without_delete_or_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            make_master(db)
            store = FakeArtifactStore(db)
            first = args_for(tmp, rstart=hashlib.sha256(store.database_bytes).hexdigest())
            run_official_bulk_shadow(
                first,
                environ=ENABLED_ENV,
                now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                store_factory=lambda _args: store,
                digest_function=fixed_public_digest,
            )

            payload = json.loads(OFFICIAL_INPUT.read_text(encoding="utf-8"))
            payload["rows"] = payload["rows"][:-1]
            reduced_input = Path(tmp) / "official-reduced.json"
            reduced_input.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            second = args_for(
                tmp,
                suffix="second",
                input=reduced_input,
                rstart=hashlib.sha256(store.database_bytes).hexdigest(),
            )
            report = run_official_bulk_shadow(
                second,
                environ=ENABLED_ENV,
                now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                store_factory=lambda _args: store,
                digest_function=fixed_public_digest,
            )
            remote = Path(tmp) / "remote-after-stale.sqlite"
            remote.write_bytes(store.database_bytes)
            conn = sqlite3.connect(remote)
            try:
                row_count = conn.execute(
                    "SELECT COUNT(*) FROM review_inbox_items WHERE source_id = 'official_source'"
                ).fetchone()[0]
            finally:
                conn.close()

        self.assertTrue(report["no_op"])
        self.assertFalse(report["published"])
        self.assertEqual(store.publish_calls, 1)
        self.assertEqual(report["reconciliation"]["summary"]["seen_count"], 51)
        self.assertEqual(report["reconciliation"]["summary"]["stale_candidate_count"], 1)
        self.assertEqual(report["reconciliation"]["summary"]["unmapped_count"], 0)
        self.assertTrue(report["parity"]["summary"]["parity"])
        self.assertEqual(row_count, 52)


if __name__ == "__main__":
    unittest.main()
