import sqlite3

from master_rdb.master_db import SCHEMA, normalize_text
from report_apply.apply_change_requests import (
    apply_payload,
    consistency_checks,
    validate_payload,
)


NOW = "2026-08-18T09:00:00+00:00"


def make_connection():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    conn.execute(
        """
        INSERT INTO event_series(
          series_id, series_key, canonical_name, normalized_name,
          annual_months_json, status, created_at, updated_at
        ) VALUES ('series_1', 'sample', 'サンプル', 'サンプル', '[]', 'active', ?, ?)
        """,
        (NOW, NOW),
    )
    conn.execute(
        """
        INSERT INTO event_occurrences(
          occurrence_id, series_id, event_year, occurrence_sequence,
          display_name, date_status, lifecycle_status, confidence, created_at, updated_at
        ) VALUES ('occ_1', 'series_1', 2025, 1, 'サンプル', 'ended', 'published', 'high', ?, ?)
        """,
        (NOW, NOW),
    )
    conn.execute(
        """
        INSERT INTO songs(song_id, canonical_title, normalized_title, status, created_at, updated_at)
        VALUES ('song_target', '東京音頭', '東京音頭', 'active', ?, ?)
        """,
        (NOW, NOW),
    )
    for evidence_id in ("ev_raw", "ev_target", "ev_noise"):
        conn.execute(
            """
            INSERT INTO evidence_items(
              evidence_id, platform, evidence_type, source_key, raw_json
            ) VALUES (?, 'youtube', 'observed', ?, '{}')
            """,
            (evidence_id, evidence_id),
        )
    conn.execute(
        """
        INSERT INTO occurrence_songs(
          occurrence_song_id, occurrence_id, song_id, song_title_raw, normalized_title,
          role, evidence_status, confidence, source_count, evidence_count, created_at, updated_at
        ) VALUES
          ('os_raw', 'occ_1', NULL, '東京おんど', '東京おんど', 'result', 'observed', 'medium', 1, 1, ?, ?),
          ('os_target', 'occ_1', 'song_target', '東京音頭', '東京音頭', 'result', 'observed', 'high', 1, 1, ?, ?),
          ('os_noise', 'occ_1', NULL, '24', '24', 'result', 'observed', 'low', 1, 1, ?, ?)
        """,
        (NOW, NOW, NOW, NOW, NOW, NOW),
    )
    conn.executemany(
        """
        INSERT INTO occurrence_song_evidence_links(
          occurrence_song_id, evidence_id, link_status, confidence
        ) VALUES (?, ?, 'linked', 0.8)
        """,
        (("os_raw", "ev_raw"), ("os_target", "ev_target"), ("os_noise", "ev_noise")),
    )
    conn.execute(
        """
        INSERT INTO observed_occurrences(
          observed_occurrence_id, source, raw_event_name, normalized_event_name,
          event_year, match_status, quality_status, source_payload_json, created_at, updated_at
        ) VALUES ('obs_1', 'youtube', 'サンプル', 'サンプル', 2025, 'matched_curated', 'matched_curated', '{}', ?, ?)
        """,
        (NOW, NOW),
    )
    observed = [
        ("obs_raw", "os_raw", "東京おんど", "東京おんど"),
        ("obs_noise", "os_noise", "24", "24"),
        ("obs_candidate", None, "新曲(Live)", normalize_text("新曲(Live)")),
    ]
    for observed_id, occurrence_song_id, raw_title, normalized in observed:
        conn.execute(
            """
            INSERT INTO observed_occurrence_songs(
              observed_occurrence_song_id, observed_occurrence_id, occurrence_song_id,
              raw_song_title, normalized_title, match_status, role, evidence_status,
              evidence_urls_json, source_payload_json, created_at, updated_at
            ) VALUES (?, 'obs_1', ?, ?, ?, 'unmatched', 'result', 'observed', '[]', '{}', ?, ?)
            """,
            (observed_id, occurrence_song_id, raw_title, normalized, NOW, NOW),
        )
    conn.commit()
    return conn


def requests():
    return {
        "request_type": "rdb_change_requests",
        "requests": [
            {
                "request_id": "merge",
                "change_type": "merge_song_identity",
                "raw_song_name": "東京おんど",
                "target_song_name": "東京音頭",
                "target_song_id": "song_target",
                "target_status": "active",
            },
            {
                "request_id": "noise",
                "change_type": "retract_song_identity",
                "raw_song_name": "24",
            },
            {
                "request_id": "candidate",
                "change_type": "register_song_candidate",
                "raw_song_name": "新曲(Live)",
                "target_song_name": "新曲",
            },
            {
                "request_id": "youtube",
                "change_type": "record_youtube_review_decision",
                "source_key": "video:abc123|year:2025",
                "inbox_id": "inbox_abc",
                "source_payload_hash": "a" * 64,
                "video_id": "abc123",
                "video_url": "https://www.youtube.com/watch?v=abc123",
                "decision": "accepted",
                "reason_detail": "曲目対応を確認",
                "review_payload": {"title_song_candidates": ["東京音頭"]},
            },
        ],
    }


def test_review_backlog_types_are_valid_without_occurrence_id():
    validate_payload(requests())


def test_review_backlog_actions_preserve_raw_observations_and_update_projection_state():
    conn = make_connection()
    payload = requests()
    result, issues = apply_payload(conn, payload, NOW)

    assert issues == []
    assert result["requests_unresolved"] == []
    assert len(result["requests_applied"]) == 4
    assert consistency_checks(conn, result) == []

    assert conn.execute(
        "SELECT COUNT(*) FROM occurrence_songs WHERE occurrence_song_id = 'os_raw'"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM occurrence_song_evidence_links WHERE occurrence_song_id = 'os_target'"
    ).fetchone()[0] == 2
    assert conn.execute(
        "SELECT occurrence_song_id, matched_song_id, match_status FROM observed_occurrence_songs WHERE observed_occurrence_song_id = 'obs_raw'"
    ).fetchone() == ("os_target", "song_target", "matched_song_llm_review")

    assert conn.execute(
        "SELECT COUNT(*) FROM occurrence_songs WHERE occurrence_song_id = 'os_noise'"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT occurrence_song_id, matched_song_id, match_status FROM observed_occurrence_songs WHERE observed_occurrence_song_id = 'obs_noise'"
    ).fetchone() == (None, None, "rejected_llm_review")

    candidate = conn.execute(
        "SELECT song_id, status FROM songs WHERE normalized_title = '新曲'"
    ).fetchone()
    assert candidate[1] == "candidate"
    assert conn.execute(
        "SELECT matched_song_id, match_status FROM observed_occurrence_songs WHERE observed_occurrence_song_id = 'obs_candidate'"
    ).fetchone() == (candidate[0], "candidate_song_llm_review")

    youtube = conn.execute(
        "SELECT raw_status, raw_json FROM evidence_items WHERE evidence_type = 'reviewed_video_evidence'"
    ).fetchone()
    assert youtube[0] == "reviewed_accepted"
    assert '"canonical_fact_links_created"' not in youtube[1]


def test_review_backlog_actions_are_idempotent():
    conn = make_connection()
    payload = requests()
    first, first_issues = apply_payload(conn, payload, NOW)
    second, second_issues = apply_payload(conn, payload, NOW)

    assert first_issues == second_issues == []
    assert first["requests_unresolved"] == second["requests_unresolved"] == []
    assert conn.execute(
        "SELECT COUNT(*) FROM songs WHERE normalized_title = '新曲'"
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM evidence_items WHERE evidence_type = 'reviewed_video_evidence'"
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM occurrence_song_evidence_links WHERE occurrence_song_id = 'os_target'"
    ).fetchone()[0] == 2
