import hashlib
import sqlite3
import tempfile
from pathlib import Path

import pytest

from master_rdb.master_db import init_db
from review_inbox import inbox_rows, upsert_inbox_items
from review_inbox_adapters.decision_writer import (
    DecisionWriterFlags,
    run_decision_write,
    validate_decision_payload,
)
from review_inbox_adapters.source_writer import ArtifactState, CasConflictError, SourceWriterError


INBOX_ID = "inbox_rare_one"
SOURCE_KEY = "new_event_candidate|event|x-status:1234567890"


class FakeArtifactStore:
    def __init__(self, database: Path):
        self.database_bytes = Path(database).read_bytes()
        self.snapshot_id = "R1"
        self.publish_calls = 0
        self.status_calls = 0
        self.fetch_calls = 0
        self.conflict_on_publish_check = False

    def status(self):
        self.status_calls += 1
        checksum = hashlib.sha256(self.database_bytes).hexdigest()
        if self.conflict_on_publish_check and self.status_calls >= 2:
            checksum = "f" * 64
        return ArtifactState(checksum, self.snapshot_id)

    def fetch(self, destination):
        self.fetch_calls += 1
        Path(destination).write_bytes(self.database_bytes)

    def publish(self, source, *, expected_remote_checksum):
        assert hashlib.sha256(self.database_bytes).hexdigest() == expected_remote_checksum
        self.publish_calls += 1
        self.database_bytes = Path(source).read_bytes()
        self.snapshot_id = f"R{self.publish_calls + 1}"
        return ArtifactState(hashlib.sha256(self.database_bytes).hexdigest(), self.snapshot_id)


def make_master(path: Path) -> None:
    conn = init_db(path)
    try:
        upsert_inbox_items(conn, [{
            "inbox_id": INBOX_ID,
            "kind": "rare_signal",
            "domain": "今年の開催情報",
            "time_scope": "future",
            "title": "候補",
            "source_id": "rare_signal",
            "source_key": SOURCE_KEY,
            "payload": {"promotion_target": "event"},
        }])
        conn.commit()
    finally:
        conn.close()


def stage(*, reviewer="内田さん", route="domain_stage", decision="accepted", decided_at="2026-07-20T01:00:00+09:00"):
    update = {
        "inbox_id": INBOX_ID,
        "decision": decision,
        "decided_by": reviewer,
        "decided_at": decided_at,
        "decision_route": route,
    }
    return {
        "schema_version": 1,
        "generated_by": "review_inbox_decision_stage.py",
        "write_mode": "staged_only",
        "decision_count": 1,
        "inbox_decision_updates": [update],
    }


def flags():
    return DecisionWriterFlags("canary", True, "legacy", True)


def run(store, payload=None, **overrides):
    expected = hashlib.sha256(store.database_bytes).hexdigest()
    values = {
        "store": store,
        "staged_payload": payload or stage(),
        "staged_payload_sha256": "a" * 64,
        "expected_targets": {INBOX_ID: {"source_id": "rare_signal", "source_key": SOURCE_KEY}},
        "public_projection_digest": lambda _path: "public-same",
        "expected_rstart_checksum": expected,
        "flags": flags(),
    }
    values.update(overrides)
    return run_decision_write(**values)


def test_decision_write_publishes_one_lifecycle_only_then_exact_retry_is_noop():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(db)
        store = FakeArtifactStore(db)
        first = run(store)
        second = run(store)
        verified = Path(tmp) / "verified.sqlite"
        verified.write_bytes(store.database_bytes)
        conn = sqlite3.connect(verified)
        try:
            row = inbox_rows(conn, status=None, ensure_schema=False)[0]
        finally:
            conn.close()

    assert first["published"] is True
    assert second["no_op"] is True
    assert store.publish_calls == 1
    assert row["decision"] == "accepted"
    assert row["decision_route"] == "domain_stage"
    assert row["decided_by"] == "内田さん"


@pytest.mark.parametrize("payload", [
    stage(reviewer="別担当"),
    stage(route="no_apply"),
    stage(decided_at="2026-07-20T02:00:00+09:00"),
    stage(decision="rejected", route="no_apply"),
])
def test_existing_decision_requires_exact_lifecycle_for_noop(payload):
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(db)
        store = FakeArtifactStore(db)
        run(store)
        with pytest.raises(SourceWriterError, match="competing existing decision"):
            run(store, payload=payload)


def test_target_identity_and_cas_conflict_fail_closed():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(db)
        store = FakeArtifactStore(db)
        with pytest.raises(SourceWriterError, match="source_key mismatch"):
            run(store, expected_targets={INBOX_ID: {"source_id": "rare_signal", "source_key": "wrong"}})
        store.status_calls = 0
        store.conflict_on_publish_check = True
        with pytest.raises(CasConflictError):
            run(store)
        assert store.publish_calls == 0


def test_stage_validation_rejects_untrusted_or_ambiguous_inputs():
    invalid = stage()
    invalid["generated_by"] = "manual.json"
    with pytest.raises(SourceWriterError, match="not trusted"):
        validate_decision_payload(invalid)

    duplicate = stage()
    duplicate["inbox_decision_updates"] *= 2
    duplicate["decision_count"] = 2
    with pytest.raises(SourceWriterError, match="duplicate"):
        validate_decision_payload(duplicate)

    naive = stage(decided_at="2026-07-20T01:00:00")
    with pytest.raises(SourceWriterError, match="timezone"):
        validate_decision_payload(naive)


def test_writer_never_migrates_v1_schema():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "old.sqlite"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE review_inbox_items (inbox_id TEXT PRIMARY KEY)")
        conn.commit()
        conn.close()
        store = FakeArtifactStore(db)
        with pytest.raises(SourceWriterError, match="schema v2 is required"):
            run(store)
        conn = sqlite3.connect(db)
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(review_inbox_items)")}
        finally:
            conn.close()
    assert columns == {"inbox_id"}
