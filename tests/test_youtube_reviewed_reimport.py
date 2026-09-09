"""The live setlist importer must preserve occurrence-specific review decisions."""

import sqlite3
from copy import deepcopy
from unittest.mock import patch

import apply_youtube_setlist_occurrences_rdb as importer
from master_rdb.master_db import SCHEMA


NOW = "2026-09-09T00:00:00+00:00"


def seeded_connection():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO event_series(series_id,series_key,canonical_name,normalized_name,"
        "annual_months_json,status,created_at,updated_at) "
        "VALUES ('series','series','サンプル','サンプル','[]','active',?,?)", (NOW, NOW)
    )
    for occurrence_id in ("occ_one", "occ_two"):
        conn.execute(
            "INSERT INTO event_occurrences(occurrence_id,series_id,event_year,occurrence_sequence,"
            "display_name,date_status,lifecycle_status,confidence,created_at,updated_at) "
            "VALUES (?,'series',2026,?,'サンプル','ended','published','high',?,?)",
            (occurrence_id, 1 if occurrence_id == "occ_one" else 2, NOW, NOW),
        )
    return conn


def occurrence(key="one"):
    return {
        "occurrence_key": key, "event_name_hint": "サンプル盆踊り",
        "venue": "サンプル公園", "event_date": "2026-08-01",
        "accounts": ["channel"], "confidence": "medium",
        "source_videos": [{"title": "サンプル盆踊り", "published_at": NOW}],
        "setlist": [{"number": 1, "title": "アンコール", "url": "https://youtu.be/source_one"}],
    }


def test_reimport_preserves_rejection_but_keeps_same_title_at_other_occurrence():
    with seeded_connection() as conn, patch.dict(
        importer.MANUAL_MATCH_OVERRIDES, {"one": "occ_one", "two": "occ_two"}
    ):
        first = occurrence()
        importer.apply_occurrence(conn, first, NOW)
        row_id = conn.execute("SELECT occurrence_song_id FROM occurrence_songs").fetchone()[0]
        # State produced by a reviewed occurrence-specific retraction.
        conn.execute(
            "UPDATE observed_occurrence_songs SET occurrence_song_id=NULL, matched_song_id=NULL, "
            "match_status='rejected_llm_review' WHERE occurrence_song_id=?", (row_id,)
        )
        conn.execute("DELETE FROM occurrence_song_evidence_links WHERE occurrence_song_id=?", (row_id,))
        conn.execute("DELETE FROM occurrence_songs WHERE occurrence_song_id=?", (row_id,))
        raw_before = conn.execute("SELECT * FROM observed_occurrence_songs").fetchall()
        evidence_before = conn.execute("SELECT * FROM evidence_items").fetchall()

        repeated = importer.apply_occurrence(conn, first, NOW)
        assert repeated["rejected_title_count"] == 1
        assert conn.execute("SELECT * FROM occurrence_songs").fetchall() == []
        assert conn.execute("SELECT * FROM occurrence_song_evidence_links").fetchall() == []
        assert conn.execute("SELECT * FROM observed_occurrence_songs").fetchall() == raw_before
        assert conn.execute("SELECT * FROM evidence_items").fetchall() == evidence_before

        # A new source for the rejected observation stays raw until reviewed.
        additional = deepcopy(first)
        additional["setlist"][0]["url"] = "https://youtu.be/source_two"
        importer.apply_occurrence(conn, additional, NOW)
        assert conn.execute("SELECT COUNT(*) FROM evidence_items").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM occurrence_songs").fetchone()[0] == 0

        importer.apply_occurrence(conn, occurrence("two"), NOW)
        assert conn.execute(
            "SELECT occurrence_id,song_title_raw FROM occurrence_songs"
        ).fetchall() == [("occ_two", "アンコール")]
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
