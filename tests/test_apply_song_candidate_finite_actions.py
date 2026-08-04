import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from master_rdb.master_db import init_db, normalize_text, table_counts
from review_inbox import record_inbox_decision, upsert_inbox_items
from review_inbox_adapters.source_writer import ArtifactState, CasConflictError, SourceWriterError
import apply_song_candidate_finite_actions as apply_module
from apply_song_candidate_finite_actions import (
    _song_only_authorizer,
    run_song_candidate_apply,
)
from song_candidate_finite_actions import GENERATOR_NAME
import operation_safety.manual_apply_guards as manual_apply_guards


SOURCE_ID = "daily_song_candidate"
SOURCE_KEY = "song_candidate|x-status:1"
INBOX_ID = "inbox_song_1"
REVIEWED_AT = "2026-08-05T09:00:00+09:00"


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


def _insert_song(conn, *, song_id, title, status, memo=""):
    normalized = normalize_text(title)
    conn.execute(
        """
        INSERT INTO songs(
          song_id, canonical_title, normalized_title, category, status, prior_tier,
          target_area, evidence_count, source_url, memo, created_at, updated_at
        ) VALUES (?, ?, ?, '', ?, '', '', NULL, '', ?, '2026-01-01T00:00:00+09:00', '2026-01-01T00:00:00+09:00')
        """,
        (song_id, title, normalized, status, memo),
    )
    conn.execute(
        "INSERT INTO song_aliases VALUES (?, ?, ?, 'canonical', 'manual')",
        (song_id, title, normalized),
    )


def make_master(
    path: Path,
    *,
    inbox_id: str = INBOX_ID,
    source_key: str = SOURCE_KEY,
    decision: str = "accepted",
    decision_route: str = "domain_stage",
    payload_title: str = "炭坑節",
    source_url: str = "",
    songs=(),
    extra_aliases=(),
):
    conn = init_db(path)
    try:
        # Mirrors review_inbox_adapters/low_priority_adapters.py DailySongAdapter's
        # common_item(): domain="曲・用語・低緊急度", kind="song", payload carries
        # the full source row including canonical_song_name/term.
        upsert_inbox_items(
            conn,
            [
                {
                    "inbox_id": inbox_id,
                    "kind": "song",
                    "domain": "曲・用語・低緊急度",
                    "time_scope": "reference",
                    "title": payload_title,
                    "source_id": SOURCE_ID,
                    "source_key": source_key,
                    "source_url": source_url,
                    "payload": {"canonical_song_name": payload_title},
                }
            ],
        )
        if decision:
            record_inbox_decision(
                conn,
                inbox_id,
                decision=decision,
                decided_by="内田さん",
                decision_route=decision_route,
                decided_at=REVIEWED_AT,
                ensure_schema=False,
            )
        for song in songs:
            _insert_song(conn, **song)
        for song_id, alias, source in extra_aliases:
            conn.execute(
                "INSERT INTO song_aliases VALUES (?, ?, ?, ?, 'manual')",
                (song_id, alias, normalize_text(alias), source),
            )
        conn.commit()
    finally:
        conn.close()


def decision_row(**overrides):
    base = {
        "source_inbox_id": INBOX_ID,
        "source_id": SOURCE_ID,
        "source_key": SOURCE_KEY,
        "candidate_title": "炭坑節",
        "action": "register_song",
        "reviewed_by": "内田さん",
        "reviewed_at": REVIEWED_AT,
        "source_url": "",
        "note": "",
    }
    base.update(overrides)
    return base


def payload(*rows):
    rows = list(rows) or [decision_row()]
    return {
        "schema_version": 1,
        "generated_by": GENERATOR_NAME,
        "write_mode": "reviewed_finite_actions",
        "decision_count": len(rows),
        "decisions": rows,
    }


def run(store, *, apply=False, backup_dir, digest=lambda _p: "public-same", **overrides):
    values = {
        "store": store,
        "reviewed_payload": payload(),
        "reviewed_payload_sha256": "a" * 64,
        "expected_rstart_checksum": hashlib.sha256(store.database_bytes).hexdigest(),
        "public_projection_digest": digest,
        "apply": apply,
        "backup_dir": backup_dir,
    }
    values.update(overrides)
    return run_song_candidate_apply(**values)


def songs_snapshot(db_path):
    conn = sqlite3.connect(db_path)
    try:
        songs = {row[0]: row[1] for row in conn.execute("SELECT song_id, status FROM songs")}
        aliases = sorted(
            (row[0], row[1]) for row in conn.execute("SELECT song_id, normalized_alias FROM song_aliases")
        )
    finally:
        conn.close()
    return songs, aliases


def store_snapshot(store, tmp):
    """The FakeArtifactStore holds published bytes in memory; write them out
    to disk under ``tmp`` (still open) before inspecting the result, since
    the original on-disk fixture DB is never mutated in place."""
    snapshot_path = Path(tmp) / f"snapshot_{store.publish_calls}.sqlite"
    snapshot_path.write_bytes(store.database_bytes)
    return songs_snapshot(snapshot_path)


# ---- register_song ----


def test_register_song_no_match_inserts_active_song_and_alias():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(db)
        store = FakeArtifactStore(db)
        result = run(store, apply=True, backup_dir=Path(tmp) / "backups")
    assert result["published"] is True
    assert result["actions"][0]["result"] == "inserted"


def test_register_song_promotes_candidate_status_to_active():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(
            db,
            songs=[{"song_id": "song_x", "title": "炭坑節", "status": "候補"}],
        )
        store = FakeArtifactStore(db)
        result = run(store, apply=True, backup_dir=Path(tmp) / "backups")
        assert result["actions"][0] == {
            "source_inbox_id": INBOX_ID,
            "action": "register_song",
            "candidate_title": "炭坑節",
            "target_song_id": None,
            "result": "promoted",
            "song_id": "song_x",
        }
        songs, _ = store_snapshot(store, tmp)
        assert songs["song_x"] == "active"


def test_register_song_verified_exact_is_noop():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(db, songs=[{"song_id": "song_x", "title": "炭坑節", "status": "active"}])
        store = FakeArtifactStore(db)
        result = run(store, apply=True, backup_dir=Path(tmp) / "backups")
    assert result["actions"][0]["result"] == "no_op"
    assert result["published"] is False
    assert result["no_op"] is True


def test_register_song_rejected_exact_is_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(db, songs=[{"song_id": "song_x", "title": "炭坑節", "status": "無効"}])
        store = FakeArtifactStore(db)
        with pytest.raises(SourceWriterError, match="rejected exact"):
            run(store, apply=True, backup_dir=Path(tmp) / "backups")


def test_register_song_alias_hit_is_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(
            db,
            songs=[{"song_id": "song_other", "title": "別の曲", "status": "active"}],
            extra_aliases=[("song_other", "炭坑節", "manual")],
        )
        store = FakeArtifactStore(db)
        with pytest.raises(SourceWriterError, match="alias hit"):
            run(store, apply=True, backup_dir=Path(tmp) / "backups")


def test_register_song_ambiguous_alias_is_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(
            db,
            songs=[
                {"song_id": "song_p", "title": "曲P", "status": "active"},
                {"song_id": "song_q", "title": "曲Q", "status": "active"},
            ],
            extra_aliases=[("song_p", "炭坑節", "manual"), ("song_q", "炭坑節", "manual")],
        )
        store = FakeArtifactStore(db)
        with pytest.raises(SourceWriterError, match="ambiguous alias"):
            run(store, apply=True, backup_dir=Path(tmp) / "backups")


# ---- status boundary golden tests (song_processing.song_catalog mapping) ----
# These pin down the exact P1 status vocabulary handling that was the root
# cause of the mid-review bug: status="有効" must classify as VERIFIED (not
# fall through to "candidate"), and any unrecognized status string must fail
# closed rather than silently being treated as a promotable/rejectable draft.


def test_register_song_alt_active_spelling_verified_exact_is_noop():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(db, songs=[{"song_id": "song_x", "title": "炭坑節", "status": "有効"}])
        store = FakeArtifactStore(db)
        result = run(store, apply=True, backup_dir=Path(tmp) / "backups")
    assert result["actions"][0]["result"] == "no_op"


def test_reject_song_alt_active_spelling_is_blocked_as_verified():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(
            db,
            decision="rejected",
            decision_route="no_apply",
            payload_title="炭坑節",
            songs=[{"song_id": "song_x", "title": "炭坑節", "status": "有効"}],
        )
        store = FakeArtifactStore(db)
        with pytest.raises(SourceWriterError, match="verified exact"):
            run(
                store,
                apply=True,
                backup_dir=Path(tmp) / "backups",
                reviewed_payload=payload(decision_row(action="reject_song", candidate_title="炭坑節")),
            )


@pytest.mark.parametrize("unknown_status", ["", "draft", "pending_review", "deprecated"])
def test_register_song_unknown_status_is_fail_closed(unknown_status):
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(db, songs=[{"song_id": "song_x", "title": "炭坑節", "status": unknown_status}])
        store = FakeArtifactStore(db)
        with pytest.raises(SourceWriterError, match="unknown existing status"):
            run(store, apply=True, backup_dir=Path(tmp) / "backups")


@pytest.mark.parametrize("unknown_status", ["", "draft", "pending_review", "deprecated"])
def test_reject_song_unknown_status_is_fail_closed(unknown_status):
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(
            db,
            decision="rejected",
            decision_route="no_apply",
            payload_title="炭坑節",
            songs=[{"song_id": "song_x", "title": "炭坑節", "status": unknown_status}],
        )
        store = FakeArtifactStore(db)
        with pytest.raises(SourceWriterError, match="unknown existing status"):
            run(
                store,
                apply=True,
                backup_dir=Path(tmp) / "backups",
                reviewed_payload=payload(decision_row(action="reject_song", candidate_title="炭坑節")),
            )


def test_add_song_alias_target_with_alt_active_spelling_is_accepted():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(
            db,
            payload_title="たんこうぶし",
            songs=[{"song_id": "song_x", "title": "炭坑節", "status": "有効"}],
        )
        store = FakeArtifactStore(db)
        result = run(
            store,
            apply=True,
            backup_dir=Path(tmp) / "backups",
            reviewed_payload=payload(
                decision_row(action="add_song_alias", target_song_id="song_x", candidate_title="たんこうぶし")
            ),
        )
    assert result["actions"][0]["result"] == "alias_inserted"


def test_add_song_alias_target_with_unknown_status_is_fail_closed():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(
            db,
            payload_title="別名候補",
            songs=[{"song_id": "song_x", "title": "炭坑節", "status": "pending_review"}],
        )
        store = FakeArtifactStore(db)
        with pytest.raises(SourceWriterError, match="not active"):
            run(
                store,
                apply=True,
                backup_dir=Path(tmp) / "backups",
                reviewed_payload=payload(
                    decision_row(action="add_song_alias", target_song_id="song_x", candidate_title="別名候補")
                ),
            )


# ---- add_song_alias ----


def test_add_song_alias_inserts_new_alias():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(
            db,
            payload_title="たんこうぶし",
            songs=[{"song_id": "song_x", "title": "炭坑節", "status": "active"}],
        )
        store = FakeArtifactStore(db)
        result = run(
            store,
            apply=True,
            backup_dir=Path(tmp) / "backups",
            reviewed_payload=payload(
                decision_row(action="add_song_alias", target_song_id="song_x", candidate_title="たんこうぶし")
            ),
        )
        assert result["actions"][0]["result"] == "alias_inserted"
        _, aliases = store_snapshot(store, tmp)
        assert ("song_x", normalize_text("たんこうぶし")) in aliases


def test_add_song_alias_retry_is_noop():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(
            db,
            payload_title="たんこうぶし",
            songs=[{"song_id": "song_x", "title": "炭坑節", "status": "active"}],
            extra_aliases=[("song_x", "たんこうぶし", "review_inbox:song_candidate")],
        )
        store = FakeArtifactStore(db)
        result = run(
            store,
            apply=True,
            backup_dir=Path(tmp) / "backups",
            reviewed_payload=payload(
                decision_row(action="add_song_alias", target_song_id="song_x", candidate_title="たんこうぶし")
            ),
        )
    assert result["actions"][0]["result"] == "no_op"
    assert result["published"] is False


def test_add_song_alias_target_not_active_is_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(
            db,
            payload_title="別名",
            songs=[{"song_id": "song_x", "title": "炭坑節", "status": "候補"}],
        )
        store = FakeArtifactStore(db)
        with pytest.raises(SourceWriterError, match="not active"):
            run(
                store,
                apply=True,
                backup_dir=Path(tmp) / "backups",
                reviewed_payload=payload(
                    decision_row(action="add_song_alias", target_song_id="song_x", candidate_title="別名")
                ),
            )


def test_add_song_alias_canonical_collision_is_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(
            db,
            payload_title="炭坑節",
            songs=[{"song_id": "song_x", "title": "炭坑節", "status": "active"}],
        )
        store = FakeArtifactStore(db)
        with pytest.raises(SourceWriterError, match="canonical normalized collision"):
            run(
                store,
                apply=True,
                backup_dir=Path(tmp) / "backups",
                reviewed_payload=payload(
                    decision_row(action="add_song_alias", target_song_id="song_x", candidate_title="炭坑節")
                ),
            )


def test_add_song_alias_would_collide_with_another_songs_canonical_title():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(
            db,
            payload_title="別の曲",
            songs=[
                {"song_id": "song_x", "title": "炭坑節", "status": "active"},
                {"song_id": "song_y", "title": "別の曲", "status": "active"},
            ],
        )
        store = FakeArtifactStore(db)
        with pytest.raises(SourceWriterError, match="collide with another song"):
            run(
                store,
                apply=True,
                backup_dir=Path(tmp) / "backups",
                reviewed_payload=payload(
                    decision_row(action="add_song_alias", target_song_id="song_x", candidate_title="別の曲")
                ),
            )


def test_add_song_alias_ambiguous_or_foreign_alias_is_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(
            db,
            payload_title="共有別名",
            songs=[
                {"song_id": "song_x", "title": "炭坑節", "status": "active"},
                {"song_id": "song_y", "title": "別の曲", "status": "active"},
            ],
            extra_aliases=[("song_y", "共有別名", "manual")],
        )
        store = FakeArtifactStore(db)
        with pytest.raises(SourceWriterError, match="ambiguous/foreign alias"):
            run(
                store,
                apply=True,
                backup_dir=Path(tmp) / "backups",
                reviewed_payload=payload(
                    decision_row(action="add_song_alias", target_song_id="song_x", candidate_title="共有別名")
                ),
            )


# ---- reject_song ----


def test_reject_song_no_match_inserts_tombstone():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(db, decision="rejected", decision_route="no_apply", payload_title="架空音頭")
        store = FakeArtifactStore(db)
        result = run(
            store,
            apply=True,
            backup_dir=Path(tmp) / "backups",
            reviewed_payload=payload(decision_row(action="reject_song", candidate_title="架空音頭")),
        )
        assert result["actions"][0]["result"] == "tombstoned"
        songs, _ = store_snapshot(store, tmp)
        assert songs[result["actions"][0]["song_id"]] == "無効"


def test_reject_song_candidate_exact_tombstones_existing_row():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(
            db,
            decision="rejected",
            decision_route="no_apply",
            payload_title="怪しい曲",
            songs=[{"song_id": "song_x", "title": "怪しい曲", "status": "候補"}],
        )
        store = FakeArtifactStore(db)
        result = run(
            store,
            apply=True,
            backup_dir=Path(tmp) / "backups",
            reviewed_payload=payload(decision_row(action="reject_song", candidate_title="怪しい曲")),
        )
        assert result["actions"][0]["result"] == "tombstoned_existing"
        songs, _ = store_snapshot(store, tmp)
        assert songs["song_x"] == "無効"


def test_reject_song_verified_exact_is_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(
            db,
            decision="rejected",
            decision_route="no_apply",
            payload_title="炭坑節",
            songs=[{"song_id": "song_x", "title": "炭坑節", "status": "active"}],
        )
        store = FakeArtifactStore(db)
        with pytest.raises(SourceWriterError, match="verified exact"):
            run(
                store,
                apply=True,
                backup_dir=Path(tmp) / "backups",
                reviewed_payload=payload(decision_row(action="reject_song", candidate_title="炭坑節")),
            )


def test_reject_song_rejected_exact_retry_is_noop():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(
            db,
            decision="rejected",
            decision_route="no_apply",
            payload_title="却下済み曲",
            songs=[{"song_id": "song_x", "title": "却下済み曲", "status": "無効"}],
        )
        store = FakeArtifactStore(db)
        result = run(
            store,
            apply=True,
            backup_dir=Path(tmp) / "backups",
            reviewed_payload=payload(decision_row(action="reject_song", candidate_title="却下済み曲")),
        )
    assert result["actions"][0]["result"] == "no_op"
    assert result["published"] is False


# ---- hold ----


def test_hold_does_not_touch_domain_tables():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(db, decision="hold", decision_route="no_apply")
        store = FakeArtifactStore(db)
        result = run(
            store,
            apply=True,
            backup_dir=Path(tmp) / "backups",
            reviewed_payload=payload(decision_row(action="hold")),
        )
    assert result["actions"][0]["result"] == "held"
    assert result["published"] is False
    assert result["no_op"] is True


# ---- source / lifecycle guard ----


def test_source_key_mismatch_is_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(db, source_key="song_candidate|x-status:actual")
        store = FakeArtifactStore(db)
        with pytest.raises(SourceWriterError, match="source_key mismatch"):
            run(store, apply=True, backup_dir=Path(tmp) / "backups")


@pytest.mark.parametrize(
    "decision,route",
    [("hold", "domain_stage"), ("accepted", "no_apply"), (None, None)],
)
def test_lifecycle_mismatch_is_blocked_for_register(decision, route):
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(db, decision=decision, decision_route=route)
        store = FakeArtifactStore(db)
        with pytest.raises(SourceWriterError, match="lifecycle mismatch"):
            run(store, apply=True, backup_dir=Path(tmp) / "backups")


def test_missing_inbox_row_is_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(db)
        store = FakeArtifactStore(db)
        with pytest.raises(SourceWriterError, match="not found"):
            run(
                store,
                apply=True,
                backup_dir=Path(tmp) / "backups",
                reviewed_payload=payload(decision_row(source_inbox_id="does_not_exist")),
            )


def test_kind_mismatch_is_blocked():
    # A row staged for a different B4 domain (e.g. venue_candidate) must not
    # be treated as a song row just because domain/source_id happen to line up.
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        conn = init_db(db)
        try:
            upsert_inbox_items(
                conn,
                [
                    {
                        "inbox_id": INBOX_ID,
                        "kind": "venue_candidate",
                        "domain": "曲・用語・低緊急度",
                        "time_scope": "reference",
                        "title": "炭坑節",
                        "source_id": SOURCE_ID,
                        "source_key": SOURCE_KEY,
                        "payload": {"canonical_song_name": "炭坑節"},
                    }
                ],
            )
            record_inbox_decision(
                conn,
                INBOX_ID,
                decision="accepted",
                decided_by="内田さん",
                decision_route="domain_stage",
                decided_at=REVIEWED_AT,
                ensure_schema=False,
            )
            conn.commit()
        finally:
            conn.close()
        store = FakeArtifactStore(db)
        with pytest.raises(SourceWriterError, match="not kind=song"):
            run(store, apply=True, backup_dir=Path(tmp) / "backups")


def test_candidate_title_mismatch_with_staged_payload_is_blocked():
    # A reviewer approving inbox_song_1 must not be able to write an arbitrary
    # title by pointing a different candidate_title at that source_inbox_id.
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(db, payload_title="炭坑節")
        store = FakeArtifactStore(db)
        with pytest.raises(SourceWriterError, match="does not match the staged inbox payload"):
            run(
                store,
                apply=True,
                backup_dir=Path(tmp) / "backups",
                reviewed_payload=payload(decision_row(candidate_title="別の曲を勝手に登録")),
            )


def test_reviewed_by_mismatch_with_decided_by_is_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(db)
        store = FakeArtifactStore(db)
        with pytest.raises(SourceWriterError, match="reviewed_by does not match"):
            run(
                store,
                apply=True,
                backup_dir=Path(tmp) / "backups",
                reviewed_payload=payload(decision_row(reviewed_by="なりすまし担当")),
            )


def test_reviewed_at_mismatch_with_decided_at_is_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(db)
        store = FakeArtifactStore(db)
        with pytest.raises(SourceWriterError, match="reviewed_at does not match"):
            run(
                store,
                apply=True,
                backup_dir=Path(tmp) / "backups",
                reviewed_payload=payload(decision_row(reviewed_at="2026-08-05T10:00:00+09:00")),
            )


def test_source_url_conflict_with_inbox_row_is_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(db, source_url="https://example.com/inbox-evidence")
        store = FakeArtifactStore(db)
        with pytest.raises(SourceWriterError, match="source_url does not match"):
            run(
                store,
                apply=True,
                backup_dir=Path(tmp) / "backups",
                reviewed_payload=payload(
                    decision_row(source_url="https://example.com/different-evidence")
                ),
            )


def test_real_low_priority_song_adapter_row_satisfies_the_lifecycle_guard():
    """Integration check against the real B4 adapter shape (not a hand-rolled
    fixture): review_inbox_adapters.low_priority_adapters.DailySongAdapter
    stages domain="曲・用語・低緊急度", kind="song", payload=dict(row)."""
    from review_inbox_adapters.low_priority_adapters import DailySongAdapter

    adapter_payload = {
        "rows": [
            {
                "canonical_song_name": "炭坑節",
                "event_name": "",
                "venue": "",
                "evidence_url": "",
            }
        ]
    }
    (staged_item,) = DailySongAdapter().adapt(adapter_payload)
    assert staged_item["kind"] == "song"
    assert staged_item["domain"] == "曲・用語・低緊急度"

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        conn = init_db(db)
        try:
            staged_item["inbox_id"] = INBOX_ID
            # source_id is the adapter class's source_id, not part of common_item()'s output.
            staged_item["source_id"] = DailySongAdapter.source_id
            staged_item["source_key"] = SOURCE_KEY
            upsert_inbox_items(conn, [staged_item])
            record_inbox_decision(
                conn,
                INBOX_ID,
                decision="accepted",
                decided_by="内田さん",
                decision_route="domain_stage",
                decided_at=REVIEWED_AT,
                ensure_schema=False,
            )
            conn.commit()
        finally:
            conn.close()
        store = FakeArtifactStore(db)
        result = run(store, apply=True, backup_dir=Path(tmp) / "backups")
    assert result["actions"][0]["result"] == "inserted"


# ---- dry-run / apply / CAS / audit ----


def test_dry_run_does_not_publish():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(db)
        store = FakeArtifactStore(db)
        result = run(store, apply=False, backup_dir=Path(tmp) / "backups")
        assert result["dry_run"] is True
        assert result["published"] is False
        assert store.publish_calls == 0
        songs, _ = songs_snapshot(db)
        assert songs == {}


def test_apply_publishes_then_exact_retry_is_noop():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(db)
        store = FakeArtifactStore(db)
        first = run(store, apply=True, backup_dir=Path(tmp) / "backups")
        second = run(store, apply=True, backup_dir=Path(tmp) / "backups")
    assert first["published"] is True
    assert store.publish_calls == 1
    assert second["published"] is False


def test_backup_is_not_overwritten_and_matches_rstart():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(db)
        store = FakeArtifactStore(db)
        backup_dir = Path(tmp) / "backups"

        first_rstart_checksum = hashlib.sha256(store.database_bytes).hexdigest()
        first = run(store, apply=True, backup_dir=backup_dir)
        first_backup_path = Path(first["backup_path"])
        assert first_backup_path.name == f"song_candidate_apply_rstart_{first_rstart_checksum}.sqlite"
        assert first_backup_path.exists()
        original_bytes = first_backup_path.read_bytes()
        assert hashlib.sha256(original_bytes).hexdigest() == first_rstart_checksum

        # publish() moved the remote forward, so a second run fetches a
        # different Rstart and must land in a differently-named backup file,
        # leaving the first backup's bytes untouched.
        second_rstart_checksum = hashlib.sha256(store.database_bytes).hexdigest()
        assert second_rstart_checksum != first_rstart_checksum
        second = run(store, apply=False, backup_dir=backup_dir)
        second_backup_path = Path(second["backup_path"])
        assert second_backup_path != first_backup_path
        assert second_backup_path.name == f"song_candidate_apply_rstart_{second_rstart_checksum}.sqlite"
        assert first_backup_path.read_bytes() == original_bytes


def test_authorizer_denies_writes_outside_songs_and_song_aliases():
    assert _song_only_authorizer(sqlite3.SQLITE_INSERT, "songs", None, None, None) == sqlite3.SQLITE_OK
    assert _song_only_authorizer(sqlite3.SQLITE_UPDATE, "song_aliases", None, None, None) == sqlite3.SQLITE_OK
    assert (
        _song_only_authorizer(sqlite3.SQLITE_UPDATE, "review_inbox_items", None, None, None)
        == sqlite3.SQLITE_DENY
    )
    assert _song_only_authorizer(sqlite3.SQLITE_INSERT, "events", None, None, None) == sqlite3.SQLITE_DENY
    assert _song_only_authorizer(sqlite3.SQLITE_SELECT, "review_inbox_items", None, None, None) == sqlite3.SQLITE_OK


def test_cas_conflict_blocks_publish():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(db)
        store = FakeArtifactStore(db)
        store.conflict_on_publish_check = True
        with pytest.raises(CasConflictError):
            run(store, apply=True, backup_dir=Path(tmp) / "backups")
    assert store.publish_calls == 0


def test_public_projection_change_is_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(db)
        store = FakeArtifactStore(db)
        calls = {"n": 0}

        def digest(_path):
            calls["n"] += 1
            return "same" if calls["n"] == 1 else "changed"

        with pytest.raises(SourceWriterError, match="public projection"):
            run(store, apply=True, backup_dir=Path(tmp) / "backups", digest=digest)


def test_conflicting_decisions_for_same_title_roll_back_together():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(
            db,
            inbox_id="inbox_song_reg",
            decision="accepted",
            decision_route="domain_stage",
            payload_title="同名曲",
        )
        conn = sqlite3.connect(db)
        try:
            upsert_inbox_items(
                conn,
                [
                    {
                        "inbox_id": "inbox_song_rej",
                        "kind": "song",
                        "domain": "曲・用語・低緊急度",
                        "time_scope": "reference",
                        "title": "同名曲",
                        "source_id": SOURCE_ID,
                        "source_key": "song_candidate|x-status:2",
                        "payload": {"canonical_song_name": "同名曲"},
                    }
                ],
            )
            record_inbox_decision(
                conn,
                "inbox_song_rej",
                decision="rejected",
                decided_by="内田さん",
                decision_route="no_apply",
                decided_at=REVIEWED_AT,
                ensure_schema=False,
            )
            conn.commit()
        finally:
            conn.close()
        store = FakeArtifactStore(db)
        rows = [
            decision_row(source_inbox_id="inbox_song_reg", action="register_song", candidate_title="同名曲"),
            decision_row(
                source_inbox_id="inbox_song_rej",
                source_key="song_candidate|x-status:2",
                action="reject_song",
                candidate_title="同名曲",
            ),
        ]
        with pytest.raises(SourceWriterError):
            run(store, apply=True, backup_dir=Path(tmp) / "backups", reviewed_payload=payload(*rows))
        songs, _ = songs_snapshot(db)
        assert songs == {}


def test_unexplained_delta_rolls_back_the_whole_transaction(monkeypatch):
    # Simulate an action implementation bug: it writes a songs row but
    # reports "no_op" (expected delta {songs: 0}). The mismatch must raise
    # and roll back everything from this apply, not just the broken action.
    def broken_register(conn, decision):
        song_id = "song_broken"
        conn.execute(
            "INSERT INTO songs("
            "song_id, canonical_title, normalized_title, category, status, "
            "prior_tier, target_area, evidence_count, source_url, memo, created_at, updated_at"
            ") VALUES (?, ?, ?, '', 'active', '', '', NULL, '', '', ?, ?)",
            (song_id, "壊れた曲", normalize_text("壊れた曲"), REVIEWED_AT, REVIEWED_AT),
        )
        return {"result": "no_op", "song_id": song_id}

    monkeypatch.setitem(apply_module._DISPATCH, "register_song", broken_register)

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "master.sqlite"
        make_master(db)
        store = FakeArtifactStore(db)
        with pytest.raises(SourceWriterError, match="unexplained delta"):
            run(store, apply=True, backup_dir=Path(tmp) / "backups")
        songs, _ = songs_snapshot(db)
    assert songs == {}
    assert store.publish_calls == 0


def test_cli_apply_requires_the_exact_confirmation_phrase(monkeypatch, tmp_path):
    db = tmp_path / "master.sqlite"
    make_master(db)
    store = FakeArtifactStore(db)
    monkeypatch.setattr(apply_module, "_build_store", lambda bucket, prefix: store)
    monkeypatch.setattr(
        apply_module, "_build_public_projection_digest", lambda target_year, today: (lambda _p: "same")
    )

    payload_path = tmp_path / "reviewed.json"
    payload_path.write_text(json.dumps(payload()), encoding="utf-8")
    argv = [
        "--reviewed-payload",
        str(payload_path),
        "--bucket",
        "test-bucket",
        "--prefix",
        "test-prefix",
        "--expect-rstart-checksum",
        hashlib.sha256(store.database_bytes).hexdigest(),
        "--apply",
        "--backup-dir",
        str(tmp_path / "backups"),
        "--target-year",
        "2026",
        "--today",
        "2026-08-05",
    ]

    with pytest.raises(ValueError, match="requires --confirm"):
        apply_module._cli(argv)
    assert store.publish_calls == 0

    ok_argv = argv + ["--confirm", manual_apply_guards.SONG_CANDIDATE_FINITE_ACTIONS_CONFIRMATION]
    assert apply_module._cli(ok_argv) == 0
    assert store.publish_calls == 1


def test_cli_requires_explicit_target_year_and_today(monkeypatch, tmp_path, capsys):
    db = tmp_path / "master.sqlite"
    make_master(db)
    store = FakeArtifactStore(db)
    monkeypatch.setattr(apply_module, "_build_store", lambda bucket, prefix: store)
    monkeypatch.setattr(
        apply_module, "_build_public_projection_digest", lambda target_year, today: (lambda _p: "same")
    )
    payload_path = tmp_path / "reviewed.json"
    payload_path.write_text(json.dumps(payload()), encoding="utf-8")
    base_argv = [
        "--reviewed-payload",
        str(payload_path),
        "--bucket",
        "test-bucket",
        "--prefix",
        "test-prefix",
        "--expect-rstart-checksum",
        hashlib.sha256(store.database_bytes).hexdigest(),
    ]

    # Neither --target-year nor --today has a datetime.now() fallback anymore;
    # omitting either is an argparse usage error (SystemExit), not a silent
    # "today" guess.
    with pytest.raises(SystemExit):
        apply_module._cli(base_argv)
    capsys.readouterr()

    with pytest.raises(SystemExit):
        apply_module._cli(base_argv + ["--target-year", "2026"])
    capsys.readouterr()


def test_cli_rejects_malformed_today():
    db_dir = tempfile.mkdtemp()
    db = Path(db_dir) / "master.sqlite"
    make_master(db)
    argv_tail = ["--target-year", "2026", "--today", "2026/08/05"]
    with pytest.raises(SourceWriterError, match="YYYY-MM-DD"):
        apply_module._cli(
            [
                "--reviewed-payload",
                str(Path(db_dir) / "does-not-need-to-exist.json"),
                "--bucket",
                "b",
                "--prefix",
                "p",
                "--expect-rstart-checksum",
                "a" * 64,
                *argv_tail,
            ]
        )
