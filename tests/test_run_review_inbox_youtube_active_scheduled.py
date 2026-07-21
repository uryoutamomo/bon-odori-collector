import hashlib
import json
import sqlite3
import tempfile
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from master_db import init_db
from review_inbox import inbox_rows
from review_inbox_adapters.source_writer import ArtifactState, CasConflictError, SourceWriterError
from run_review_inbox_youtube_active_scheduled import CONFIRM, run_scheduled


FIXTURE = Path(__file__).parent / "fixtures" / "youtube_active_video_review_examples.json"
JST = ZoneInfo("Asia/Tokyo")
ENABLED_ENV = {
    "REVIEW_INBOX_YOUTUBE_ACTIVE_SCHEDULED_ENABLED": "true",
    "REVIEW_INBOX_DUAL_WRITE_MODE": "bulk",
    "REVIEW_INBOX_CAS_PUBLISH_ENABLED": "true",
    "REVIEW_INBOX_READER_MODE": "legacy",
    "REVIEW_INBOX_LEGACY_WRITER_ENABLED": "true",
}


class FakeStore:
    def __init__(self, database: Path):
        self.data = Path(database).read_bytes()
        self.snapshot_id = "R1"
        self.publish_calls = 0

    def status(self):
        return ArtifactState(hashlib.sha256(self.data).hexdigest(), self.snapshot_id)

    def fetch(self, destination):
        Path(destination).write_bytes(self.data)

    def publish(self, source, *, expected_remote_checksum):
        if self.status().checksum != expected_remote_checksum:
            raise CasConflictError("fake conflict")
        self.data = Path(source).read_bytes()
        self.publish_calls += 1
        self.snapshot_id = f"R{self.publish_calls + 1}"
        return self.status()


def make_db(path: Path) -> None:
    conn = init_db(path)
    conn.commit()
    conn.close()


def args_for(tmp: str, **overrides) -> Namespace:
    values = {
        "input": FIXTURE,
        "snapshot_out": Path(tmp) / "snapshot.json",
        "report_out": Path(tmp) / "report.json",
        "observation_id": "youtube-scheduled-123-1",
        "public_today": "2026-07-20",
        "bucket": "unused",
        "prefix": "master-rdb",
        "work_dir": Path(tmp) / "work",
        "execute": True,
        "confirm": CONFIRM,
    }
    values.update(overrides)
    return Namespace(**values)


def fixed_public_digest(_database, *, today):
    return hashlib.sha256(today.encode("utf-8")).hexdigest()


def test_default_off_stops_before_evidence_or_artifact_access():
    with tempfile.TemporaryDirectory() as tmp:
        args = args_for(tmp, execute=False, confirm="")
        with pytest.raises(SourceWriterError, match="execution is off"):
            run_scheduled(args, environ={}, store_factory=lambda _args: pytest.fail("no store"))
        assert not Path(args.snapshot_out).exists()
        assert not Path(args.report_out).exists()


def test_repository_enable_gate_and_common_gates_precede_artifact_access():
    with tempfile.TemporaryDirectory() as tmp:
        args = args_for(tmp)
        with pytest.raises(SourceWriterError, match="dual-write is off"):
            run_scheduled(args, environ={}, store_factory=lambda _args: pytest.fail("no store"))
        incomplete = dict(ENABLED_ENV)
        incomplete.pop("REVIEW_INBOX_CAS_PUBLISH_ENABLED")
        with pytest.raises(SourceWriterError, match="explicit environment gates"):
            run_scheduled(args, environ=incomplete, store_factory=lambda _args: pytest.fail("no store"))


def test_enabled_scheduled_run_writes_all_pending_items_and_audited_evidence():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_db(db)
        store = FakeStore(db)
        args = args_for(tmp)
        report = run_scheduled(
            args,
            environ=ENABLED_ENV,
            now=datetime(2026, 7, 20, 15, 13, tzinfo=JST),
            store_factory=lambda _args: store,
            digest_function=fixed_public_digest,
        )
        verified = Path(tmp) / "verified.sqlite"
        verified.write_bytes(store.data)
        with sqlite3.connect(verified) as conn:
            rows = inbox_rows(conn, status=None)
        saved = json.loads(Path(args.report_out).read_text(encoding="utf-8"))

    assert report["published"] is True
    assert store.publish_calls == 1
    assert len(rows) == 3
    assert {row["source_id"] for row in rows} == {"youtube_evidence"}
    assert saved["reconciliation"]["summary"]["unmapped_count"] == 0
    assert saved["audit"]["public_projection_unchanged"] is True
    assert saved["entrypoint"]["legacy_writer_retained"] is True
    assert saved["entrypoint"]["source_queue"] == "youtube_active_video_review"


def test_cron_conflict_window_stops_before_artifact_access():
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(SourceWriterError, match="17:20-18:00"):
            run_scheduled(
                args_for(tmp),
                environ=ENABLED_ENV,
                now=datetime(2026, 7, 20, 17, 30, tzinfo=JST),
                store_factory=lambda _args: pytest.fail("no store"),
            )
