import sqlite3
import pytest
from master_rdb.master_db import connect_existing, init_db
from review_inbox import INBOX_SCHEMA_VERSION, migrate_inbox_schema_v2


def occurrence(conn, ident, sequence=1, state="predicted", tier="rule_predicted"):
    conn.execute("INSERT INTO event_series(series_id,series_key,canonical_name,normalized_name,created_at,updated_at) VALUES ('s','series','Series','series','x','x') ON CONFLICT(series_id) DO NOTHING")
    conn.execute("INSERT INTO event_occurrences(occurrence_id,series_id,event_year,occurrence_sequence,display_name,current_event_state,date_certainty_tier,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)", (ident, "s", 2026, sequence, ident, state, tier, "x", "x"))


def test_occurrence_unique_allows_distinct_sequence_and_rejects_duplicate(tmp_path):
    conn = init_db(tmp_path / "db.sqlite")
    occurrence(conn, "one")
    occurrence(conn, "two", sequence=2)
    with pytest.raises(sqlite3.IntegrityError):
        occurrence(conn, "duplicate")


def test_event_state_axes_reject_invalid_inserts_and_updates(tmp_path):
    conn = init_db(tmp_path / "db.sqlite")
    for state, tier in [("confirmed", "rule_predicted"), ("ended", "season_hint"), ("predicted", "confirmed")]:
        with pytest.raises(sqlite3.IntegrityError):
            occurrence(conn, state + tier, sequence=len(state + tier), state=state, tier=tier)
    occurrence(conn, "confirmed", state="confirmed", tier="confirmed")
    occurrence(conn, "predicted", sequence=9)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE event_occurrences SET current_event_state='confirmed', date_certainty_tier='rule_predicted' WHERE occurrence_id='predicted'")


def test_migrations_are_recorded_unique_and_connections_enable_foreign_keys(tmp_path):
    path = tmp_path / "db.sqlite"
    conn = init_db(path)
    row = conn.execute("SELECT version,name,applied_at FROM schema_migrations").fetchone()
    assert all(row)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO schema_migrations VALUES (1,'again','x')")
    migrate_inbox_schema_v2(conn)
    assert conn.execute("SELECT name FROM schema_migrations WHERE version=?", (INBOX_SCHEMA_VERSION,)).fetchone()[0] == "review_inbox_v2"
    conn.close()
    with connect_existing(path) as existing:
        assert existing.execute("PRAGMA foreign_keys").fetchone()[0] == 1
