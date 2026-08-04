import hashlib
import json
import sqlite3

import pytest

from build_song_evidence_adapter_shadow import build_report
from song_processing.song_catalog import SongCatalog
from song_processing.song_evidence_adapters import (
    adapt_human_change_requests,
    adapt_ocr_reviews,
    adapt_x_candidates,
    adapt_youtube_setlists,
    build_snapshot,
    resolve_occurrence_target,
    route_candidate,
)


def make_db(path=None):
    conn = sqlite3.connect(path or ":memory:")
    conn.executescript(
        """
        CREATE TABLE songs (
          song_id TEXT PRIMARY KEY, canonical_title TEXT, status TEXT
        );
        CREATE TABLE song_aliases (
          song_id TEXT, alias TEXT, normalized_alias TEXT
        );
        CREATE TABLE event_series (
          series_id TEXT PRIMARY KEY, canonical_name TEXT, normalized_name TEXT
        );
        CREATE TABLE venues (
          venue_id TEXT PRIMARY KEY, canonical_name TEXT, normalized_name TEXT
        );
        CREATE TABLE event_occurrences (
          occurrence_id TEXT PRIMARY KEY, series_id TEXT, event_year INTEGER,
          display_name TEXT, venue_id TEXT, date_start TEXT, date_end TEXT,
          date_status TEXT, lifecycle_status TEXT, confidence TEXT, source_kind TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO songs VALUES (?, ?, ?)",
        [
            ("song_verified", "東京音頭", "有効"),
            ("song_candidate", "ふるさと音頭", "候補"),
            ("song_rejected", "大人の部", "無効"),
            ("song_alias_a", "正調A", "有効"),
            ("song_alias_b", "正調B", "有効"),
        ],
    )
    conn.executemany(
        "INSERT INTO song_aliases VALUES (?, ?, ?)",
        [
            ("song_verified", "東京おんど", "東京おんど"),
            ("song_alias_a", "同名別称", "同名別称"),
            ("song_alias_b", "同名別称", "同名別称"),
        ],
    )
    conn.execute("INSERT INTO event_series VALUES ('series_1', '神楽坂盆踊り', '神楽坂盆踊り')")
    conn.execute("INSERT INTO venues VALUES ('venue_1', '神楽坂通り', '神楽坂通り')")
    conn.execute(
        "INSERT INTO event_occurrences VALUES "
        "('occ_1', 'series_1', 2026, '神楽坂盆踊り', 'venue_1', "
        "'2026-07-19', '2026-07-20', 'confirmed', 'published', 'confirmed', 'official')"
    )
    conn.commit()
    return conn


def catalog(conn):
    return SongCatalog.from_connection(conn)


def strong_target(_target):
    return {"match_state": "strong", "occurrence_id": "occ_1", "match_score": 1.0}


def test_x_adapter_preserves_each_raw_evidence_and_stable_identity():
    payload = {
        "rows": [{
            "category": "曲候補",
            "term": "東京音頭",
            "evidence": [
                {"url": "https://x.com/a/status/1", "text": "東京音頭を踊った"},
                {"url": "https://x.com/b/status/2", "text": "東京音頭です"},
            ],
        }]
    }
    before = adapt_x_candidates(payload)
    after = adapt_x_candidates(payload)
    assert len(before) == 2
    assert [row["candidate_id"] for row in before] == [row["candidate_id"] for row in after]
    assert {row["source_url"] for row in before} == {
        "https://x.com/a/status/1", "https://x.com/b/status/2"
    }
    assert all(row["evidence_strength"] == "prose" for row in before)


def test_youtube_adapter_uses_structured_event_and_video_provenance():
    rows = adapt_youtube_setlists({
        "occurrences": [{
            "occurrence_key": "set_1",
            "event_name_hint": "神楽坂盆踊り",
            "venue": "神楽坂通り",
            "event_date": "2026-07-19",
            "setlist": [{"number": 1, "title": "東京音頭", "url": "https://youtu.be/abc"}],
            "source_videos": [{
                "url": "https://youtu.be/abc", "published_at": "2026-07-20T00:00:00Z",
                "account": "channel", "title": "東京音頭 神楽坂盆踊り",
            }],
        }]
    })
    assert len(rows) == 1
    assert rows[0]["source_kind"] == "youtube_setlist"
    assert rows[0]["event_target"]["event_year"] == 2026
    assert rows[0]["raw_text"] == "東京音頭 神楽坂盆踊り"


def test_ocr_adapter_requires_approval_and_explicit_songs():
    payload = {"items": [
        {"status": "pending", "songs": ["東京音頭"]},
        {
            "status": "approved", "id": "ocr1", "event_name": "神楽坂盆踊り",
            "venue": "神楽坂通り", "event_date": "2026-07-19",
            "songs": ["東京音頭", {"title": "ふるさと音頭"}],
        },
    ]}
    rows = adapt_ocr_reviews(payload)
    assert [row["raw_song_title"] for row in rows] == ["東京音頭", "ふるさと音頭"]
    with pytest.raises(ValueError, match="explicit songs"):
        adapt_ocr_reviews({"items": [{"status": "approved", "ocr_text": "東京音頭"}]})


def test_human_report_adapter_accepts_only_finite_song_evidence_requests():
    payload = {"requests": [
        {"request_id": "ignore", "change_type": "update_venue"},
        {
            "request_id": "songs1", "change_type": "add_song_evidence",
            "occurrence_id": "occ_1", "evidence_mode": "firsthand_observed",
            "songs": [{"title": "東京音頭"}],
            "source": {"source_key": "uchida", "text_excerpt": "現地確認"},
        },
    ]}
    rows = adapt_human_change_requests(payload)
    assert len(rows) == 1
    assert rows[0]["evidence_strength"] == "human_confirmed"
    assert rows[0]["event_target"]["occurrence_id"] == "occ_1"


@pytest.mark.parametrize(
    ("title", "expected_route", "reason"),
    [
        ("東京音頭", "auto_link", "verified_song_strong_event_structured_evidence"),
        ("東京おんど", "auto_link", "verified_song_strong_event_structured_evidence"),
        ("ふるさと音頭", "review_song_identity", "catalog_candidate"),
        ("大人の部", "reject", "catalog_rejected"),
        ("同名別称", "review_song_identity", "catalog_ambiguous_alias"),
        ("未知曲", "review_song_identity", "catalog_unresolved_or_unknown"),
    ],
)
def test_catalog_and_strong_event_produce_finite_routes(title, expected_route, reason):
    conn = make_db()
    candidate = adapt_ocr_reviews({"items": [{
        "status": "approved", "id": "ocr", "songs": [title],
        "occurrence_id": "occ_1", "evidence_mode": "official_setlist",
    }]})[0]
    routed = route_candidate(candidate, catalog(conn), strong_target)
    assert routed["route"] == expected_route
    assert routed["reason_code"] == reason


def test_prose_and_ambiguous_event_never_auto_link():
    conn = make_db()
    x_candidate = adapt_x_candidates({"rows": [{
        "category": "曲×会場共起", "song_name": "東京音頭", "venue": "神楽坂通り",
        "event_candidates": ["神楽坂盆踊り"], "evidence": [{"url": "https://x.com/a"}],
    }]})[0]
    assert route_candidate(x_candidate, catalog(conn), strong_target)["route"] == "review_evidence_strength"

    youtube = adapt_youtube_setlists({"occurrences": [{
        "occurrence_key": "y1", "event_name_hint": "神楽坂盆踊り",
        "setlist": [{"title": "東京音頭", "url": "https://youtu.be/a"}],
    }]})[0]
    ambiguous = lambda _target: {"match_state": "ambiguous", "occurrence_id": "", "match_score": 0.95}
    assert route_candidate(youtube, catalog(conn), ambiguous)["route"] == "review_event_match"

    ocr_without_mode = adapt_ocr_reviews({"items": [{
        "status": "approved", "id": "ocr", "songs": ["東京音頭"], "occurrence_id": "occ_1",
    }]})[0]
    routed = route_candidate(ocr_without_mode, catalog(conn), strong_target)
    assert routed["route"] == "review_evidence_strength"
    assert routed["reason_code"] == "evidence_mode_required"


def test_occurrence_resolution_is_unique_and_fail_closed():
    conn = make_db()
    result = resolve_occurrence_target(conn, {
        "event_name_hint": "神楽坂盆踊り", "venue_hint": "神楽坂通り", "event_year": 2026,
    })
    assert result["match_state"] == "strong"
    assert result["occurrence_id"] == "occ_1"
    assert resolve_occurrence_target(conn, {"event_name_hint": "存在しない祭り"})["match_state"] == "none"
    assert resolve_occurrence_target(conn, {"occurrence_id": "missing"})["match_state"] == "missing"


def test_snapshot_deduplicates_identical_candidates_and_counts_routes():
    conn = make_db()
    row = adapt_ocr_reviews({"items": [{
        "status": "approved", "id": "ocr", "songs": ["東京音頭"], "occurrence_id": "occ_1",
        "evidence_mode": "official_setlist",
    }]})[0]
    snapshot = build_snapshot([row, row], catalog(conn), strong_target)
    assert snapshot["candidate_count"] == 1
    assert snapshot["route_counts"] == {"auto_link": 1}


def test_shadow_report_reads_database_without_modifying_it(tmp_path):
    db = tmp_path / "master.sqlite"
    make_db(db).close()
    x_path = tmp_path / "x.json"
    youtube_path = tmp_path / "youtube.json"
    ocr_path = tmp_path / "ocr.json"
    human_path = tmp_path / "human.json"
    x_path.write_text(json.dumps({"rows": []}), encoding="utf-8")
    youtube_path.write_text(json.dumps({"occurrences": []}), encoding="utf-8")
    ocr_path.write_text(json.dumps({"items": []}), encoding="utf-8")
    human_path.write_text(json.dumps({"requests": [{
        "request_id": "h1", "change_type": "add_song_evidence", "occurrence_id": "occ_1",
        "evidence_mode": "firsthand_observed", "songs": [{"title": "東京音頭"}],
        "source": {"source_key": "firsthand"},
    }]}), encoding="utf-8")
    before = hashlib.sha256(db.read_bytes()).hexdigest()

    report = build_report(
        db_path=db, x_path=x_path, youtube_path=youtube_path,
        ocr_path=ocr_path, human_paths=[human_path],
    )

    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    assert report["generated_by"] == "build_song_evidence_adapter_shadow.py"
    assert report["write_mode"] == "shadow_read_only"
    assert report["route_counts"] == {"auto_link": 1}
    assert report["inputs"]["master_db"]["sha256"] == before
