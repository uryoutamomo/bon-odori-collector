"""Regression tests for safe multi-year song inheritance."""

import json

from inherit_song_probabilities_rdb import find_inheritance_candidates, gather_evidence, inherit
from master_rdb.master_db import init_db


NOW = "2026-08-16T00:00:00+00:00"


def seed_occurrences(conn):
    conn.execute(
        """
        INSERT INTO event_series (
          series_id, series_key, canonical_name, normalized_name, created_at, updated_at
        ) VALUES ('series_1', 'series-1', 'テスト盆踊り', 'テスト盆踊り', ?, ?)
        """,
        (NOW, NOW),
    )
    conn.executemany(
        """
        INSERT INTO event_occurrences (
          occurrence_id, origin, series_id, event_year, display_name, created_at, updated_at
        ) VALUES (?, 'curated', 'series_1', ?, ?, ?, ?)
        """,
        [
            ("occ_2025", 2025, "テスト盆踊り 2025", NOW, NOW),
            ("occ_2026", 2026, "テスト盆踊り 2026", NOW, NOW),
        ],
    )
    conn.executemany(
        """
        INSERT INTO songs (
          song_id, canonical_title, normalized_title, status, created_at, updated_at
        ) VALUES (?, ?, ?, 'active', ?, ?)
        """,
        [
            ("song_x", "Xだけの曲", "Xだけの曲", NOW, NOW),
            ("song_curated", "公式根拠の曲", "公式根拠の曲", NOW, NOW),
        ],
    )
    conn.executemany(
        """
        INSERT INTO occurrence_songs (
          occurrence_song_id, origin, occurrence_id, song_id, song_title_raw,
          normalized_title, role, evidence_status, created_at, updated_at
        ) VALUES (?, ?, 'occ_2025', ?, ?, ?, 'result', 'observed', ?, ?)
        """,
        [
            ("osong_x", "observed_x_post", "song_x", "Xだけの曲", "Xだけの曲", NOW, NOW),
            (
                "osong_curated",
                "curated",
                "song_curated",
                "公式根拠の曲",
                "公式根拠の曲",
                NOW,
                NOW,
            ),
        ],
    )


def test_x_materializer_owned_fact_is_not_an_inheritance_source(tmp_path):
    conn = init_db(tmp_path / "master.sqlite")
    seed_occurrences(conn)

    candidates = find_inheritance_candidates(conn, 2026)

    assert [row["source_occurrence_song_id"] for row in candidates] == ["osong_curated"]


def test_inheritance_uses_only_accepted_non_x_claim_evidence(tmp_path):
    conn = init_db(tmp_path / "master.sqlite")
    seed_occurrences(conn)
    conn.executemany(
        """
        INSERT INTO evidence_items (
          evidence_id, platform, evidence_type, source_key, account_key, raw_json
        ) VALUES (?, ?, ?, ?, ?, '{}')
        """,
        [
            ("evid_official", "web", "official_page", "official", "official"),
            ("evid_retracted", "web", "official_page", "old", "old"),
            ("evid_x", "x", "x_song_claim_v2", "tweet_1", "x-account"),
        ],
    )
    conn.executemany(
        """
        INSERT INTO occurrence_song_evidence_links (
          occurrence_song_id, evidence_id, link_status, confidence
        ) VALUES ('osong_curated', ?, ?, ?)
        """,
        [
            ("evid_official", "accepted", 0.8),
            ("evid_retracted", "retracted", 0.9),
            ("evid_x", "accepted", 0.95),
        ],
    )

    evidence = gather_evidence(conn, "osong_curated")

    assert evidence == [{"kind": "hint", "reliability": 0.8, "speaker": "official"}]


def test_inheritance_combines_direct_evidence_from_multiple_years(tmp_path):
    conn = init_db(tmp_path / "master.sqlite")
    seed_occurrences(conn)
    conn.execute(
        """
        INSERT INTO event_occurrences (
          occurrence_id, origin, series_id, event_year, display_name, created_at, updated_at
        ) VALUES ('occ_2024', 'curated', 'series_1', 2024, 'テスト盆踊り 2024', ?, ?)
        """,
        (NOW, NOW),
    )
    conn.execute(
        """
        INSERT INTO occurrence_songs (
          occurrence_song_id, origin, occurrence_id, song_id, song_title_raw,
          normalized_title, role, evidence_status, created_at, updated_at
        ) VALUES (
          'osong_curated_2024', 'curated', 'occ_2024', 'song_curated',
          '公式根拠の曲', '公式根拠の曲', 'result', 'observed', ?, ?
        )
        """,
        (NOW, NOW),
    )
    conn.executemany(
        """
        INSERT INTO evidence_items (
          evidence_id, platform, evidence_type, source_key, account_key, raw_json
        ) VALUES (?, 'youtube', 'historical_occurrence_video', ?, ?, '{}')
        """,
        [
            ("evid_2024", "video_2024", "same-channel"),
            ("evid_2025", "video_2025", "same-channel"),
        ],
    )
    conn.executemany(
        """
        INSERT INTO occurrence_song_evidence_links (
          occurrence_song_id, evidence_id, link_status, confidence
        ) VALUES (?, ?, 'accepted', 0.85)
        """,
        [
            ("osong_curated_2024", "evid_2024"),
            ("osong_curated", "evid_2025"),
        ],
    )

    first = inherit(conn, 2026, NOW)
    inherited = conn.execute(
        """
        SELECT probability, inherited_from_year, notes
        FROM occurrence_songs
        WHERE occurrence_id='occ_2026' AND normalized_title='公式根拠の曲'
        """
    ).fetchone()

    assert len(first["created"]) == 1
    assert first["created"][0]["basis_label"] == "2024・2025年実測"
    assert inherited[0] == 70
    assert inherited[1] == 2025
    notes = json.loads(inherited[2])
    assert notes["source_years"] == [2024, 2025]
    assert notes["historical_basis_label"] == "2024・2025年実測"

    second = inherit(conn, 2026, NOW)
    assert second["created"] == []
    assert len(second["updated"]) == 1
