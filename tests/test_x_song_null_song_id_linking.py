"""B2 regression tests for linking legacy occurrence facts to a resolved song."""

import pytest

from master_rdb.master_db import init_db
from report_apply.event_report_helpers import link_resolved_occurrence_song


NOW = "2026-08-16T00:00:00+00:00"


def seed_domain(conn):
    conn.executemany(
        """
        INSERT INTO songs (
          song_id, canonical_title, normalized_title, status, created_at, updated_at
        ) VALUES (?, ?, ?, 'active', ?, ?)
        """,
        [
            ("song_tokyo", "東京音頭", "東京音頭", NOW, NOW),
            ("song_other", "別の東京音頭", "別の東京音頭", NOW, NOW),
        ],
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
        INSERT INTO evidence_items (evidence_id, platform, evidence_type, source_key, raw_json)
        VALUES ('evid_x', 'x', 'x_song_claim_v2', 'obs_1', '{}')
        """
    )


def insert_existing_fact(conn, *, song_id):
    conn.execute(
        """
        INSERT INTO occurrence_songs (
          occurrence_song_id, origin, occurrence_id, song_id, song_title_raw,
          normalized_title, role, evidence_status, probability, confidence,
          source_count, evidence_count, inherited_from_year,
          first_observed_at, last_observed_at, notes, created_at, updated_at
        ) VALUES (
          'osong_existing', 'curated', 'occ_1', ?, '東京 音頭',
          '東京音頭', 'setlist', 'announced', 0.42, 'medium',
          7, 8, 2025, ?, ?, '{"keep":"all"}', ?, ?
        )
        """,
        (song_id, NOW, NOW, NOW, NOW),
    )


def occurrence_row(conn):
    conn.row_factory = __import__("sqlite3").Row
    return dict(conn.execute("SELECT * FROM occurrence_songs WHERE occurrence_song_id='osong_existing'").fetchone())


def test_null_song_id_is_cas_filled_without_mutating_existing_fact_columns(tmp_path):
    conn = init_db(tmp_path / "master.sqlite")
    seed_domain(conn)
    insert_existing_fact(conn, song_id=None)
    before = occurrence_row(conn)

    linked = link_resolved_occurrence_song(
        conn, "occ_1", "song_tokyo", "東京音頭", "evid_x",
        role="setlist", evidence_status="announced", evidence_note="X announcement", now=NOW,
    )

    after = occurrence_row(conn)
    assert linked == {"occurrence_song_id": "osong_existing", "created": False}
    assert after["song_id"] == "song_tokyo"
    assert {key: value for key, value in after.items() if key != "song_id"} == {
        key: value for key, value in before.items() if key != "song_id"
    }
    link = conn.execute(
        """SELECT link_status, confidence, notes FROM occurrence_song_evidence_links
           WHERE occurrence_song_id='osong_existing' AND evidence_id='evid_x'"""
    ).fetchone()
    assert tuple(link) == ("accepted", 0.95, "X announcement")


def test_non_null_different_song_id_fails_closed_without_linking(tmp_path):
    conn = init_db(tmp_path / "master.sqlite")
    seed_domain(conn)
    insert_existing_fact(conn, song_id="song_other")
    before = occurrence_row(conn)

    with pytest.raises(ValueError, match="conflicts"):
        link_resolved_occurrence_song(
            conn, "occ_1", "song_tokyo", "東京音頭", "evid_x",
            role="setlist", evidence_status="announced", evidence_note="X announcement", now=NOW,
        )

    assert occurrence_row(conn) == before
    assert conn.execute("SELECT COUNT(*) FROM occurrence_song_evidence_links").fetchone()[0] == 0
