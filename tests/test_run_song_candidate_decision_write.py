import hashlib
import json
import sqlite3
import tempfile
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from master_rdb.master_db import init_db
from review_inbox import inbox_rows, upsert_inbox_items
from review_inbox_adapters.source_writer import ArtifactState, SourceWriterError
from scripts.run_song_candidate_decision_write import (
    require_explicit_environment,
    run_batch,
    validate_pair,
)


INBOX_ID = "inbox_song_one"
SOURCE_KEY = "song:新曲"


class FakeStore:
    def __init__(self, database: Path):
        self.database_bytes = Path(database).read_bytes()
        self.snapshot_id = "R1"
        self.publish_calls = 0

    def status(self):
        return ArtifactState(hashlib.sha256(self.database_bytes).hexdigest(), self.snapshot_id)

    def fetch(self, destination):
        Path(destination).write_bytes(self.database_bytes)

    def publish(self, source, *, expected_remote_checksum):
        assert hashlib.sha256(self.database_bytes).hexdigest() == expected_remote_checksum
        self.database_bytes = Path(source).read_bytes()
        self.publish_calls += 1
        self.snapshot_id = "R2"
        return self.status()


def make_master(path: Path) -> None:
    conn = init_db(path)
    try:
        upsert_inbox_items(
            conn,
            [
                {
                    "inbox_id": INBOX_ID,
                    "kind": "song",
                    "domain": "曲・用語・低緊急度",
                    "title": "新曲",
                    "source_id": "daily_song_candidate",
                    "source_key": SOURCE_KEY,
                    "source_url": "https://example.com/song",
                    "payload": {"canonical_song_name": "新曲"},
                }
            ],
        )
        conn.commit()
    finally:
        conn.close()


def lifecycle():
    return {
        "inbox_id": INBOX_ID,
        "decision": "accepted",
        "decided_by": "内田さん",
        "decided_at": "2026-08-06T01:00:00+09:00",
        "decision_route": "domain_stage",
    }


def decision_payload():
    return {
        "schema_version": 1,
        "generated_by": "review_inbox_decision_stage.py",
        "write_mode": "staged_only",
        "decision_count": 1,
        "inbox_decision_updates": [lifecycle()],
    }


def action_payload():
    return {
        "schema_version": 1,
        "generated_by": "review_inbox_decision_stage.py",
        "source_id": "review_inbox",
        "write_mode": "reviewed_song_finite_actions",
        "decision_count": 1,
        "rows": [
            {
                "inbox_update": lifecycle(),
                "apply_value": "register_song",
                "note": "確認",
                "domain_stage_type": "song_candidate",
                "domain_candidate": {
                    "source_inbox_id": INBOX_ID,
                    "source_id": "daily_song_candidate",
                    "source_key": SOURCE_KEY,
                    "source_url": "https://example.com/song",
                    "kind": "song",
                    "finite_action": "register_song",
                    "target_song_id": None,
                    "payload": {"canonical_song_name": "新曲"},
                    "write_mode": "reviewed_finite_action",
                },
            }
        ],
    }


def test_validate_pair_rejects_lifecycle_or_target_mismatch():
    decisions = decision_payload()
    actions = action_payload()
    decisions["inbox_decision_updates"][0]["decision"] = "rejected"
    decisions["inbox_decision_updates"][0]["decision_route"] = "no_apply"
    with pytest.raises(SourceWriterError, match="lifecycle"):
        validate_pair(decisions, actions)


@pytest.mark.parametrize("mode", ["canary", "bulk"])
def test_environment_allows_explicit_canary_or_bulk(mode):
    flags = require_explicit_environment(
        {
            "REVIEW_INBOX_DECISION_WRITE_MODE": mode,
            "REVIEW_INBOX_CAS_PUBLISH_ENABLED": "true",
            "REVIEW_INBOX_READER_MODE": "legacy",
            "REVIEW_INBOX_LEGACY_WRITER_ENABLED": "true",
        }
    )
    assert flags.decision_write_mode == mode


def test_batch_is_default_off_and_then_writes_only_review_lifecycle():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        database = root / "master.sqlite"
        make_master(database)
        store = FakeStore(database)
        decisions = root / "review_inbox_decision_updates.json"
        actions = root / "review_inbox_song_candidate_actions.json"
        decisions.write_text(json.dumps(decision_payload()), encoding="utf-8")
        actions.write_text(json.dumps(action_payload()), encoding="utf-8")
        args = Namespace(
            staged_decisions=decisions,
            staged_actions=actions,
            frozen_evidence_dir=root / "frozen",
            report_out=root / "report.json",
            expect_rstart_checksum=store.status().checksum,
            public_target_year=2026,
            public_today="2026-08-06",
            bucket="",
            prefix="",
            work_dir=None,
            execute=False,
            confirm="",
        )
        with pytest.raises(SourceWriterError, match="execution is off"):
            run_batch(args, store_factory=lambda _args: store)

        args.execute = True
        args.confirm = "WRITE SONG CANDIDATE DECISIONS"
        env = {
            "REVIEW_INBOX_DECISION_WRITE_MODE": "bulk",
            "REVIEW_INBOX_CAS_PUBLISH_ENABLED": "true",
            "REVIEW_INBOX_READER_MODE": "legacy",
            "REVIEW_INBOX_LEGACY_WRITER_ENABLED": "true",
        }
        report = run_batch(
            args,
            environ=env,
            now=datetime(2026, 8, 5, 16, 0, tzinfo=UTC),
            store_factory=lambda _args: store,
            digest_function=lambda _db, **_kwargs: "same",
        )
        verified = root / "verified.sqlite"
        verified.write_bytes(store.database_bytes)
        conn = sqlite3.connect(verified)
        try:
            row = inbox_rows(conn, status=None, ensure_schema=False)[0]
            song_count = conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
        finally:
            conn.close()

        assert report["published"] is True
        assert report["entrypoint"]["next_step"].startswith("use Rend checksum")
        assert (root / "frozen/review_inbox_decision_updates.json").exists()
        assert (root / "frozen/review_inbox_song_candidate_actions.json").exists()
        assert row["decision"] == "accepted"
        assert row["decision_route"] == "domain_stage"
        assert song_count == 0
