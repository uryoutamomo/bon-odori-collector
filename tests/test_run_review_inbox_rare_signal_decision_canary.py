import hashlib
import json
import tempfile
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from master_rdb.master_db import init_db
from review_inbox import upsert_inbox_items
from review_inbox_adapters.source_writer import ArtifactState, SourceWriterError
from run_review_inbox_rare_signal_decision_canary import CONFIRM, run_canary


JST = ZoneInfo("Asia/Tokyo")
INBOX_ID = "inbox_rare_one"
SOURCE_KEY = "new_event_candidate|event|x-status:1234567890"
ENABLED_ENV = {
    "REVIEW_INBOX_DECISION_WRITE_MODE": "canary",
    "REVIEW_INBOX_CAS_PUBLISH_ENABLED": "true",
    "REVIEW_INBOX_READER_MODE": "legacy",
    "REVIEW_INBOX_LEGACY_WRITER_ENABLED": "true",
}


class FakeStore:
    def __init__(self, db):
        self.data = Path(db).read_bytes()
        self.snapshot = "R1"
        self.publish_calls = 0

    def status(self):
        return ArtifactState(hashlib.sha256(self.data).hexdigest(), self.snapshot)

    def fetch(self, destination):
        Path(destination).write_bytes(self.data)

    def publish(self, source, *, expected_remote_checksum):
        assert hashlib.sha256(self.data).hexdigest() == expected_remote_checksum
        self.data = Path(source).read_bytes()
        self.publish_calls += 1
        self.snapshot = "R2"
        return self.status()


def make_db(path):
    conn = init_db(path)
    upsert_inbox_items(conn, [{
        "inbox_id": INBOX_ID, "kind": "rare_signal", "title": "候補",
        "source_id": "rare_signal", "source_key": SOURCE_KEY,
    }])
    conn.commit()
    conn.close()


def write_stage(path):
    payload = {
        "schema_version": 1,
        "generated_by": "review_inbox_decision_stage.py",
        "write_mode": "staged_only",
        "decision_count": 1,
        "inbox_decision_updates": [{
            "inbox_id": INBOX_ID, "decision": "accepted", "decided_by": "内田さん",
            "decided_at": "2026-07-20T01:00:00+09:00", "decision_route": "domain_stage",
        }],
    }
    Path(path).write_text(json.dumps(payload), encoding="utf-8")


def args_for(tmp, checksum, **overrides):
    values = {
        "staged_decisions": Path(tmp) / "stage.json",
        "frozen_stage_out": Path(tmp) / "frozen.json",
        "report_out": Path(tmp) / "report.json",
        "inbox_id": INBOX_ID,
        "source_key": SOURCE_KEY,
        "expect_rstart_checksum": checksum,
        "public_target_year": 2026,
        "public_today": "2026-07-20",
        "bucket": "unused",
        "prefix": "master-rdb",
        "work_dir": Path(tmp) / "work",
        "execute": True,
        "confirm": CONFIRM,
    }
    values.update(overrides)
    return Namespace(**values)


def test_default_off_stops_before_evidence_or_store():
    with tempfile.TemporaryDirectory() as tmp:
        args = args_for(tmp, "a" * 64, execute=False, confirm="")
        with pytest.raises(SourceWriterError, match="execution is off"):
            run_canary(args, environ={}, store_factory=lambda _args: pytest.fail("no store"))
        assert not Path(args.frozen_stage_out).exists()
        assert not Path(args.report_out).exists()


def test_enabled_runner_writes_frozen_stage_and_audited_report():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_db(db)
        store = FakeStore(db)
        args = args_for(tmp, store.status().checksum)
        write_stage(args.staged_decisions)
        report = run_canary(
            args,
            environ=ENABLED_ENV,
            now=datetime(2026, 7, 20, 12, 0, tzinfo=JST),
            store_factory=lambda _args: store,
            digest_function=lambda _db, *, today: f"public:{today}",
        )
        saved = json.loads(Path(args.report_out).read_text(encoding="utf-8"))
        frozen_matches = Path(args.frozen_stage_out).read_bytes() == Path(args.staged_decisions).read_bytes()

    assert report["published"] is True
    assert store.publish_calls == 1
    assert frozen_matches
    assert saved["entrypoint"]["inbox_id"] == INBOX_ID
    assert saved["audit"]["public_projection_unchanged"] is True


def test_identity_mismatch_and_cron_window_fail_before_store():
    with tempfile.TemporaryDirectory() as tmp:
        args = args_for(tmp, "a" * 64, inbox_id="wrong")
        write_stage(args.staged_decisions)
        with pytest.raises(SourceWriterError, match="approved inbox_id"):
            run_canary(
                args,
                environ=ENABLED_ENV,
                now=datetime(2026, 7, 20, 12, 0, tzinfo=JST),
                store_factory=lambda _args: pytest.fail("no store"),
            )

        cron_args = args_for(tmp, "a" * 64)
        with pytest.raises(SourceWriterError, match="17:20-18:00"):
            run_canary(
                cron_args,
                environ=ENABLED_ENV,
                now=datetime(2026, 7, 20, 17, 30, tzinfo=JST),
                store_factory=lambda _args: pytest.fail("no store"),
            )
