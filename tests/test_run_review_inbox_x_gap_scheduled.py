import hashlib
import json
import sqlite3
from argparse import Namespace
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from master_rdb.master_db import init_db
from review_inbox import inbox_rows
from review_inbox_adapters.source_adapter import write_adapted_snapshot
from review_inbox_adapters.source_writer import (
    ArtifactState,
    CasConflictError,
    SourceWriterError,
)
from review_inbox_adapters.x_gap_adapter import build_daily_cohort_snapshot
from run_review_inbox_x_gap_scheduled import CONFIRM, run_scheduled
from x_candidate_backlog import build_backlog


NOW = datetime(2026, 8, 18, 6, 30, tzinfo=timezone.utc)
ENABLED_ENV = {
    "REVIEW_INBOX_X_GAP_SCHEDULED_ENABLED": "true",
    "REVIEW_INBOX_DUAL_WRITE_MODE": "cohort",
    "REVIEW_INBOX_CAS_PUBLISH_ENABLED": "true",
    "REVIEW_INBOX_READER_MODE": "inbox",
    "REVIEW_INBOX_LEGACY_WRITER_ENABLED": "false",
    "REVIEW_INBOX_CRON_SERIALIZED_RUN": "true",
}


class FakeStore:
    def __init__(self, database: Path, *, conflict: bool = False):
        self.database_bytes = database.read_bytes()
        self.snapshot_id = "R1"
        self.publish_calls = 0
        self.status_calls = 0
        self.conflict = conflict

    def status(self):
        self.status_calls += 1
        checksum = hashlib.sha256(self.database_bytes).hexdigest()
        if self.conflict and self.status_calls == 2:
            checksum = "f" * 64
        return ArtifactState(checksum, self.snapshot_id)

    def fetch(self, destination):
        Path(destination).write_bytes(self.database_bytes)

    def publish(self, source, *, expected_remote_checksum):
        if hashlib.sha256(self.database_bytes).hexdigest() != expected_remote_checksum:
            raise CasConflictError("fake conflict")
        self.publish_calls += 1
        self.database_bytes = Path(source).read_bytes()
        self.snapshot_id = f"R{self.publish_calls + 1}"
        return self.status()


def candidate(index: int) -> dict:
    return {
        "candidate_id": f"candidate-{index}",
        "source_key": f"x:{index}",
        "candidate_kind": "official_new_event",
        "priority_score": 100 - index,
        "event_year": 2026,
        "observed_dates": ["2026-08-25"],
        "source_url": f"https://x.com/example/status/{index}",
        "source_text": "試験盆踊り 8月25日 試験公園",
        "source_officiality": {"classification": "registered_official_social"},
        "voice": {},
    }


def prepare(tmp_path: Path, count: int = 7):
    backlog = build_backlog(
        {
            "generated_at": NOW.isoformat(),
            "candidates": [candidate(index) for index in range(count)],
            "archived_candidates": [],
        },
        None,
        now=NOW,
        today=date(2026, 8, 18),
    )
    backlog_path = tmp_path / "backlog.json"
    backlog_path.write_text(json.dumps(backlog, ensure_ascii=False), encoding="utf-8")
    snapshot = build_daily_cohort_snapshot(backlog_path)
    input_path = tmp_path / "cohort.json"
    write_adapted_snapshot(snapshot, input_path)
    database = tmp_path / "master.sqlite"
    conn = init_db(database)
    conn.commit()
    conn.close()
    args = Namespace(
        input=input_path,
        backlog=backlog_path,
        snapshot_out=tmp_path / "frozen.json",
        report_out=tmp_path / "report.json",
        observation_id="github-100-1",
        public_target_year=2026,
        public_today="2026-08-18",
        bucket="unused",
        prefix="master-rdb",
        work_dir=tmp_path / "work",
        execute=True,
        confirm=CONFIRM,
    )
    return args, database


def digest(_database, *, target_year, today):
    return hashlib.sha256(f"{target_year}:{today}".encode()).hexdigest()


def test_scheduled_cohort_writes_five_and_only_then_marks_them_in_progress(tmp_path):
    args, database = prepare(tmp_path)
    store = FakeStore(database)
    report = run_scheduled(
        args,
        environ=ENABLED_ENV,
        now=NOW,
        store_factory=lambda _args: store,
        digest_function=digest,
    )
    verified = tmp_path / "verified.sqlite"
    verified.write_bytes(store.database_bytes)
    with sqlite3.connect(verified) as conn:
        rows = inbox_rows(conn, status=None)
    backlog = json.loads(args.backlog.read_text(encoding="utf-8"))
    assert report["published"] is True
    assert len(rows) == 5
    assert {row["source_id"] for row in rows} == {"x_gap"}
    assert backlog["summary"]["status_counts"]["in_progress"] == 5
    assert backlog["summary"]["status_counts"]["unprocessed"] == 2
    assert report["backlog_transition"]["source_keys"] == [
        item["source_key"] for item in rows
    ]


def test_gate_failure_happens_before_store_or_backlog_mutation(tmp_path):
    args, database = prepare(tmp_path)
    before = args.backlog.read_bytes()
    with pytest.raises(SourceWriterError, match="dual-write is off"):
        run_scheduled(
            args,
            environ={},
            now=NOW,
            store_factory=lambda _args: pytest.fail("store must not be created"),
            digest_function=digest,
        )
    assert args.backlog.read_bytes() == before


def test_cas_conflict_leaves_candidates_unprocessed(tmp_path):
    args, database = prepare(tmp_path)
    before = args.backlog.read_bytes()
    store = FakeStore(database, conflict=True)
    with pytest.raises(CasConflictError):
        run_scheduled(
            args,
            environ=ENABLED_ENV,
            now=NOW,
            store_factory=lambda _args: store,
            digest_function=digest,
        )
    assert args.backlog.read_bytes() == before
    assert not args.report_out.exists()


def test_runner_rejects_full_snapshot_mislabeled_as_daily_input(tmp_path):
    args, database = prepare(tmp_path)
    snapshot = json.loads(args.input.read_text(encoding="utf-8"))
    snapshot["selection"]["mode"] = "all"
    write_adapted_snapshot(snapshot, args.input)
    with pytest.raises(SourceWriterError, match="daily canary cohort"):
        run_scheduled(
            args,
            environ=ENABLED_ENV,
            now=NOW,
            store_factory=lambda _args: pytest.fail("store must not be created"),
            digest_function=digest,
        )
