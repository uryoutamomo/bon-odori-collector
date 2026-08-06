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
from review_inbox import inbox_rows
from review_inbox_adapters.source_writer import ArtifactState, CasConflictError, SourceWriterError
from run_review_inbox_x_gap_canary import CONFIRM, run_canary


JST = ZoneInfo("Asia/Tokyo")
ENABLED_ENV = {
    "REVIEW_INBOX_DUAL_WRITE_MODE": "canary",
    "REVIEW_INBOX_CAS_PUBLISH_ENABLED": "true",
    "REVIEW_INBOX_READER_MODE": "legacy",
    "REVIEW_INBOX_LEGACY_WRITER_ENABLED": "true",
}
CANARY_KEY = "x:lane2-canary"


class FakeArtifactStore:
    def __init__(self, database: Path):
        self.database_bytes = database.read_bytes()
        self.snapshot_id = "R1"
        self.fetch_calls = 0
        self.publish_calls = 0

    def status(self):
        return ArtifactState(hashlib.sha256(self.database_bytes).hexdigest(), self.snapshot_id)

    def fetch(self, destination):
        self.fetch_calls += 1
        Path(destination).write_bytes(self.database_bytes)

    def publish(self, source, *, expected_remote_checksum):
        if hashlib.sha256(self.database_bytes).hexdigest() != expected_remote_checksum:
            raise CasConflictError("fake conflict")
        self.publish_calls += 1
        self.database_bytes = Path(source).read_bytes()
        self.snapshot_id = f"R{self.publish_calls + 1}"
        return self.status()


def make_master(path: Path) -> None:
    conn = init_db(path)
    conn.commit()
    conn.close()


def fixed_public_digest(_database, *, target_year, today):
    return hashlib.sha256(today.encode("utf-8")).hexdigest()


def candidate(source_key: str, *, lane: str) -> dict:
    return {
        "source_key": source_key,
        "candidate_kind": "schedule_change",
        "priority_score": 80,
        "event_year": 2026,
        "source_url": "https://x.com/example/status/1",
        "source_text": "盆踊りの日程が変更されました",
        "source_date_hint": "2026-08-06",
        "matched_occurrence": {
            "event_name": "テスト盆踊り",
            "venue": "テスト会場",
            "date_start": "2026-08-20",
        },
        "source_officiality": {"classification": "registered_official_social"},
        "lane": lane,
    }


def write_lanes(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "lanes": {
                    "lane1_auto_plan": [candidate("x:lane1", lane="lane1_auto_plan")],
                    "lane2_operator_review": [
                        candidate(CANARY_KEY, lane="lane2_operator_review")
                    ],
                    "lane3_user_review": [
                        candidate("x:lane3", lane="lane3_user_review")
                    ],
                },
                "archived_candidates": [candidate("x:archived", lane="archived")],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def args_for(tmp: str, *, source_key: str = CANARY_KEY, **overrides):
    lanes = Path(tmp) / "x_review_lanes.json"
    write_lanes(lanes)
    values = {
        "input": lanes,
        "canary_source_key": source_key,
        "snapshot_out": Path(tmp) / "snapshot.json",
        "report_out": Path(tmp) / "report.json",
        "observation_id": "x-gap-canary-1",
        "expect_rstart_checksum": "a" * 64,
        "public_target_year": 2026,
        "public_today": "2026-08-06",
        "bucket": "unused-in-test",
        "prefix": "master-rdb",
        "work_dir": Path(tmp) / "work",
        "execute": True,
        "confirm": CONFIRM,
    }
    values.update(overrides)
    return Namespace(**values)


class RunReviewInboxXGapCanaryTest(unittest.TestCase):
    def test_default_off_stops_before_snapshot_or_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(tmp, execute=False, confirm="")
            with self.assertRaisesRegex(SourceWriterError, "execution is off"):
                run_canary(
                    args,
                    environ={},
                    now=datetime(2026, 8, 6, 12, tzinfo=JST),
                    store_factory=lambda _args: self.fail("store must not be created"),
                )
            self.assertFalse(args.snapshot_out.exists())
            self.assertFalse(args.report_out.exists())

    def test_environment_and_cron_gates_precede_artifact_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(tmp)
            incomplete = dict(ENABLED_ENV)
            incomplete.pop("REVIEW_INBOX_READER_MODE")
            with self.assertRaisesRegex(SourceWriterError, "explicit environment gates"):
                run_canary(
                    args,
                    environ=incomplete,
                    now=datetime(2026, 8, 6, 12, tzinfo=JST),
                    store_factory=lambda _args: self.fail("store must not be created"),
                )
            with self.assertRaisesRegex(SourceWriterError, "17:20-18:00"):
                run_canary(
                    args,
                    environ=ENABLED_ENV,
                    now=datetime(2026, 8, 6, 17, 30, tzinfo=JST),
                    store_factory=lambda _args: self.fail("store must not be created"),
                )

    def test_lane1_archived_and_missing_keys_cannot_be_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for source_key in ("x:lane1", "x:archived", "missing"):
                args = args_for(tmp, source_key=source_key)
                with self.assertRaisesRegex(SourceWriterError, "lane2/lane3"):
                    run_canary(
                        args,
                        environ=ENABLED_ENV,
                        now=datetime(2026, 8, 6, 12, tzinfo=JST),
                        store_factory=lambda _args: self.fail("store must not be created"),
                    )

    def test_enabled_canary_writes_one_lane2_item_with_cas_and_parity(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "master.sqlite"
            make_master(database)
            store = FakeArtifactStore(database)
            args = args_for(
                tmp,
                expect_rstart_checksum=hashlib.sha256(store.database_bytes).hexdigest(),
            )
            report = run_canary(
                args,
                environ=ENABLED_ENV,
                now=datetime(2026, 8, 6, 12, tzinfo=JST),
                store_factory=lambda _args: store,
                digest_function=fixed_public_digest,
            )
            frozen = json.loads(args.snapshot_out.read_text(encoding="utf-8"))
            verified = Path(tmp) / "verified.sqlite"
            verified.write_bytes(store.database_bytes)
            with sqlite3.connect(verified) as conn:
                rows = inbox_rows(conn, status=None)

        self.assertTrue(report["published"])
        self.assertEqual(store.fetch_calls, 2)
        self.assertEqual(store.publish_calls, 1)
        self.assertEqual(frozen["item_count"], 1)
        self.assertEqual(frozen["selection"], {"mode": "canary", "source_keys": [CANARY_KEY]})
        self.assertEqual(frozen["lane"], "lane2_operator_review")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_id"], "x_gap")
        self.assertEqual(rows[0]["source_key"], CANARY_KEY)
        self.assertTrue(report["audit"]["public_projection_unchanged"])
        self.assertEqual(report["reconciliation"]["summary"]["unmapped_count"], 0)


if __name__ == "__main__":
    unittest.main()
