import pytest

from export_public_events import load_rdb_occurrence_songs
from master_rdb.master_db import init_db
from report_apply.event_report_helpers import link_resolved_occurrence_song


NOW = "2026-08-16T00:00:00+00:00"


def seed_domain(conn, *, song_status="active"):
    conn.execute(
        """
        INSERT INTO songs (
          song_id, canonical_title, normalized_title, status, created_at, updated_at
        ) VALUES ('song_tokyo', '東京音頭', '東京音頭', ?, ?, ?)
        """,
        (song_status, NOW, NOW),
    )
    conn.execute(
        """
        INSERT INTO event_series (
          series_id, series_key, canonical_name, normalized_name, created_at, updated_at
        ) VALUES ('series_1', 'series-1', 'テスト盆踊り', 'テスト盆踊り', ?, ?)
        """,
        (NOW, NOW),
    )
    conn.execute(
        """
        INSERT INTO event_occurrences (
          occurrence_id, series_id, event_year, display_name, created_at, updated_at
        ) VALUES ('occ_1', 'series_1', 2026, 'テスト盆踊り', ?, ?)
        """,
        (NOW, NOW),
    )
    conn.execute(
        """
        INSERT INTO evidence_items (
          evidence_id, platform, evidence_type, source_key, raw_json
        ) VALUES ('evid_1', 'x', 'song_claim', 'obs_1', '{}')
        """
    )


def test_resolved_helper_never_creates_a_song_and_uses_claim_semantics(tmp_path):
    conn = init_db(tmp_path / "master.sqlite")
    seed_domain(conn)

    linked = link_resolved_occurrence_song(
        conn,
        "occ_1",
        "song_tokyo",
        "東京音頭",
        "evid_1",
        role="setlist",
        evidence_status="announced",
        evidence_note="X announcement",
        now=NOW,
    )

    row = conn.execute(
        "SELECT origin, song_id, role, evidence_status FROM occurrence_songs"
    ).fetchone()
    assert linked["created"] is True
    assert tuple(row) == ("observed_x_post", "song_tokyo", "setlist", "announced")
    assert conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0] == 1


def test_resolved_helper_fails_closed_on_existing_fact_collision(tmp_path):
    conn = init_db(tmp_path / "master.sqlite")
    seed_domain(conn)
    conn.execute(
        """
        INSERT INTO occurrence_songs (
          occurrence_song_id, occurrence_id, song_title_raw, normalized_title,
          role, evidence_status, confidence, created_at, updated_at
        ) VALUES ('osong_existing', 'occ_1', '東京音頭', '東京音頭',
                  'result', 'observed', 'high', ?, ?)
        """,
        (NOW, NOW),
    )
    with pytest.raises(ValueError, match="conflicts"):
        link_resolved_occurrence_song(
            conn,
            "occ_1",
            "song_tokyo",
            "東京音頭",
            "evid_1",
            role="result",
            evidence_status="observed",
            evidence_note="X observation",
            now=NOW,
        )


def test_public_export_requires_active_song_and_accepted_evidence_for_x_fact(tmp_path):
    conn = init_db(tmp_path / "master.sqlite")
    seed_domain(conn)
    linked = link_resolved_occurrence_song(
        conn,
        "occ_1",
        "song_tokyo",
        "東京音頭",
        "evid_1",
        role="result",
        evidence_status="observed",
        evidence_note="X observation",
        now=NOW,
    )
    conn.row_factory = __import__("sqlite3").Row

    assert [row["name"] for row in load_rdb_occurrence_songs(conn)["occ_1"]] == ["東京音頭"]

    conn.execute(
        "UPDATE occurrence_song_evidence_links SET link_status='retracted' WHERE occurrence_song_id=?",
        (linked["occurrence_song_id"],),
    )
    assert load_rdb_occurrence_songs(conn) == {}

    conn.execute(
        "UPDATE occurrence_song_evidence_links SET link_status='accepted' WHERE occurrence_song_id=?",
        (linked["occurrence_song_id"],),
    )
    conn.execute("UPDATE songs SET status='無効' WHERE song_id='song_tokyo'")
    assert load_rdb_occurrence_songs(conn) == {}


def test_public_export_rejects_malformed_x_role_mapping(tmp_path):
    conn = init_db(tmp_path / "master.sqlite")
    seed_domain(conn)
    conn.execute(
        """
        INSERT INTO occurrence_songs (
          occurrence_song_id, origin, occurrence_id, song_id, song_title_raw,
          normalized_title, role, evidence_status, confidence, created_at, updated_at
        ) VALUES ('osong_bad', 'observed_x_post', 'occ_1', 'song_tokyo', '東京音頭',
                  '東京音頭', 'prediction', 'announced', 'high', ?, ?)
        """,
        (NOW, NOW),
    )
    conn.execute(
        """
        INSERT INTO occurrence_song_evidence_links (
          occurrence_song_id, evidence_id, link_status
        ) VALUES ('osong_bad', 'evid_1', 'accepted')
        """
    )
    conn.row_factory = __import__("sqlite3").Row
    assert load_rdb_occurrence_songs(conn) == {}
