import sqlite3

import pytest

from event_model.local_judgment_migration import migrate_local_judgment_contract
from event_model.x_song_identity_migration import migrate_x_song_identity
from master_rdb.master_db import init_db
from run_x_song_identity_migration import CONFIRM_TEXT, run


EXPECTED_TABLES = {
    "x_song_resolution_decisions",
    "x_occurrence_resolution_decisions",
    "x_song_materializations",
    "x_song_retractions",
}


def test_master_schema_contains_e2_song_identity_tables(tmp_path):
    conn = init_db(tmp_path / "master.sqlite")
    tables = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert EXPECTED_TABLES <= tables
    conn.close()


def test_migration_is_additive_idempotent_and_uses_version_four(tmp_path):
    db = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE songs (song_id TEXT PRIMARY KEY);
        CREATE TABLE event_occurrences (occurrence_id TEXT PRIMARY KEY);
        CREATE TABLE occurrence_songs (occurrence_song_id TEXT PRIMARY KEY);
        CREATE TABLE evidence_items (evidence_id TEXT PRIMARY KEY);
        """
    )
    migrate_local_judgment_contract(conn)
    first = migrate_x_song_identity(conn)
    second = migrate_x_song_identity(conn)

    assert first["migration_version"] == 4
    assert set(first["tables_added"]) == EXPECTED_TABLES
    assert second["tables_added"] == []
    assert conn.execute(
        "SELECT name FROM local_judgment_schema_migrations WHERE version=4"
    ).fetchone()[0] == "x_song_identity_v2"


def test_migration_requires_local_judgment_contract():
    conn = sqlite3.connect(":memory:")
    with pytest.raises(ValueError, match="local judgment migration"):
        migrate_x_song_identity(conn)


def test_resolution_phase_and_action_are_constrained(tmp_path):
    conn = init_db(tmp_path / "master.sqlite")
    params = {
        "decision_id": "sdec_1",
        "observation_id": "obs_1",
        "observation_sha256": "a" * 64,
        "packet_id": "spkt_1",
        "packet_sha256": "b" * 64,
        "phase": "retrieval",
        "action": "new_song",
        "candidate_rows_json": "[]",
        "candidate_set_sha256": "c" * 64,
        "catalog_snapshot_json": "[]",
        "catalog_snapshot_sha256": "d" * 64,
        "reason_code": "test",
        "actor_id": "test",
        "decided_at": "2026-08-16T00:00:00+00:00",
        "created_at": "2026-08-16T00:00:00+00:00",
    }
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO x_song_resolution_decisions (
              decision_id, observation_id, observation_sha256, packet_id,
              packet_sha256, phase, action, candidate_rows_json,
              candidate_set_sha256, catalog_snapshot_json,
              catalog_snapshot_sha256, reason_code, actor_id, decided_at, created_at
            ) VALUES (
              :decision_id, :observation_id, :observation_sha256, :packet_id,
              :packet_sha256, :phase, :action, :candidate_rows_json,
              :candidate_set_sha256, :catalog_snapshot_json,
              :catalog_snapshot_sha256, :reason_code, :actor_id, :decided_at, :created_at
            )
            """,
            params,
        )
    conn.close()


def test_runner_is_dry_run_by_default_and_execute_requires_confirmation(tmp_path):
    db = tmp_path / "master.sqlite"
    conn = init_db(db)
    migrate_local_judgment_contract(conn)
    conn.commit()
    conn.close()

    report = run(db_path=db)
    assert report["mode"] == "dry_run"
    with sqlite3.connect(db) as check:
        assert check.execute(
            "SELECT COUNT(*) FROM local_judgment_schema_migrations WHERE version=4"
        ).fetchone()[0] == 0

    with pytest.raises(ValueError, match="--confirm"):
        run(db_path=db, execute=True)
    report = run(db_path=db, execute=True, confirm=CONFIRM_TEXT)
    assert report["mode"] == "execute"
    with sqlite3.connect(db) as check:
        assert check.execute(
            "SELECT COUNT(*) FROM local_judgment_schema_migrations WHERE version=4"
        ).fetchone()[0] == 1
