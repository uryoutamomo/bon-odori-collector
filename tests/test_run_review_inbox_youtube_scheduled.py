import hashlib
import json
import sqlite3
import tempfile
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from master_rdb.master_db import init_db
from review_inbox import inbox_rows
from review_inbox_adapters.source_writer import ArtifactState, CasConflictError, SourceWriterError
from run_review_inbox_youtube_scheduled import CONFIRM, run_scheduled


ROOT = Path(__file__).resolve().parents[1]
JST = ZoneInfo("Asia/Tokyo")
ENABLED_ENV = {
    "REVIEW_INBOX_YOUTUBE_AGGREGATE_SCHEDULED_ENABLED":"true",
    "REVIEW_INBOX_DUAL_WRITE_MODE":"bulk",
    "REVIEW_INBOX_CAS_PUBLISH_ENABLED":"true",
    "REVIEW_INBOX_READER_MODE":"legacy",
    "REVIEW_INBOX_LEGACY_WRITER_ENABLED":"true",
}


class FakeStore:
    def __init__(self, database):
        self.data = Path(database).read_bytes(); self.snapshot_id = "R1"; self.publish_calls = 0
    def status(self): return ArtifactState(hashlib.sha256(self.data).hexdigest(), self.snapshot_id)
    def fetch(self, destination): Path(destination).write_bytes(self.data)
    def publish(self, source, *, expected_remote_checksum):
        if self.status().checksum != expected_remote_checksum: raise CasConflictError("fake conflict")
        self.data = Path(source).read_bytes(); self.publish_calls += 1; self.snapshot_id = "R2"; return self.status()


def args_for(tmp, **overrides):
    values = {"active_input":ROOT/"tests/fixtures/youtube_active_video_review_examples.json","year_input":ROOT/"data/youtube_year_backfill_review_queue.json","user_input":ROOT/"data/youtube_user_confirmation_queue.json","snapshot_out":Path(tmp)/"snapshot.json","report_out":Path(tmp)/"report.json","observation_id":"youtube-aggregate-123-1","public_target_year":2026,"public_today":"2026-07-20","bucket":"unused","prefix":"master-rdb","work_dir":Path(tmp)/"work","execute":True,"confirm":CONFIRM}
    values.update(overrides); return Namespace(**values)


def fixed_digest(_database, *, target_year, today): return hashlib.sha256(f"{target_year}:{today}".encode()).hexdigest()


def test_default_off_stops_before_artifact_access():
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(SourceWriterError, match="execution is off"):
            run_scheduled(args_for(tmp,execute=False,confirm=""),environ={},store_factory=lambda _:pytest.fail("store"))


def test_repository_and_common_gates_stop_before_artifact_access():
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(SourceWriterError, match="dual-write is off"):
            run_scheduled(args_for(tmp),environ={},store_factory=lambda _:pytest.fail("store"))


def test_all_inputs_and_evidence_paths_must_be_distinct():
    with tempfile.TemporaryDirectory() as tmp:
        args = args_for(tmp)
        with pytest.raises(SourceWriterError, match="inputs must be distinct"):
            run_scheduled(args_for(tmp, year_input=args.active_input), environ=ENABLED_ENV, store_factory=lambda _:pytest.fail("store"))
        with pytest.raises(SourceWriterError, match="paths must be distinct"):
            run_scheduled(args_for(tmp, user_input=Path(tmp)/"snapshot.json"), environ=ENABLED_ENV, store_factory=lambda _:pytest.fail("store"))


def test_complete_aggregate_is_written_with_all_queue_lineage():
    with tempfile.TemporaryDirectory() as tmp:
        db=Path(tmp)/"master.sqlite"; conn=init_db(db); conn.commit(); conn.close(); store=FakeStore(db); args=args_for(tmp)
        report=run_scheduled(args,environ=ENABLED_ENV,now=datetime(2026,7,20,15,13,tzinfo=JST),store_factory=lambda _:store,digest_function=fixed_digest)
        verified=Path(tmp)/"verified.sqlite"; verified.write_bytes(store.data)
        with sqlite3.connect(verified) as conn: rows=inbox_rows(conn,status=None)
        saved=json.loads(Path(args.snapshot_out).read_text())
    assert report["published"] is True and store.publish_calls == 1
    assert len(rows) == saved["item_count"]
    assert saved["aggregate"]["complete"] is True
    assert [entry["queue"] for entry in saved["input_lineage"]] == ["active_video","year_backfill","user_confirmation"]
    assert report["entrypoint"]["source_queue"] == "youtube_aggregate"


def test_cron_conflict_window_stops_before_artifact_access():
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(SourceWriterError,match="17:20-18:00"):
            run_scheduled(args_for(tmp),environ=ENABLED_ENV,now=datetime(2026,7,20,17,30,tzinfo=JST),store_factory=lambda _:pytest.fail("store"))
