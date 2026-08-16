"""Regression tests for keeping X claims out of ungated inherited predictions."""

from inherit_song_probabilities_rdb import find_inheritance_candidates, gather_evidence
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

