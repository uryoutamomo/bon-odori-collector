import json
import sqlite3
from pathlib import Path

import pytest

from scripts.build_review_backlog_canonical_apply_plan import (
    build_plan,
    build_song_identity_plan,
    build_youtube_plan,
    connect_read_only,
)


ROOT = Path(__file__).resolve().parents[1]


def make_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE songs (
          song_id TEXT PRIMARY KEY,
          canonical_title TEXT NOT NULL,
          normalized_title TEXT NOT NULL UNIQUE,
          status TEXT NOT NULL
        );
        CREATE TABLE song_aliases (
          song_id TEXT NOT NULL,
          alias TEXT NOT NULL,
          normalized_alias TEXT NOT NULL,
          source TEXT NOT NULL,
          confidence TEXT NOT NULL,
          PRIMARY KEY (song_id, normalized_alias)
        );
        CREATE TABLE occurrence_songs (
          occurrence_song_id TEXT PRIMARY KEY,
          occurrence_id TEXT NOT NULL,
          song_id TEXT,
          song_title_raw TEXT NOT NULL,
          normalized_title TEXT NOT NULL,
          role TEXT NOT NULL,
          origin TEXT NOT NULL,
          evidence_status TEXT NOT NULL
        );
        CREATE TABLE occurrence_song_evidence_links (
          occurrence_song_id TEXT NOT NULL,
          evidence_id TEXT NOT NULL,
          PRIMARY KEY (occurrence_song_id, evidence_id)
        );
        CREATE TABLE evidence_items (
          evidence_id TEXT PRIMARY KEY,
          url TEXT,
          source_key TEXT,
          source_id TEXT
        );
        CREATE TABLE observed_occurrence_songs (
          observed_occurrence_song_id TEXT PRIMARY KEY,
          evidence_urls_json TEXT NOT NULL,
          source_payload_json TEXT NOT NULL
        );
        INSERT INTO songs VALUES ('song_target', '東京音頭', '東京音頭', 'active');
        INSERT INTO occurrence_songs VALUES
          ('raw_1', 'occ_1', NULL, '東京おんど', '東京おんど', 'played', 'observed', 'supported'),
          ('target_1', 'occ_1', 'song_target', '東京音頭', '東京音頭', 'played', 'curated', 'supported'),
          ('noise_1', 'occ_2', NULL, '24', '24', 'played', 'observed', 'weak');
        INSERT INTO occurrence_song_evidence_links VALUES ('raw_1', 'ev_1');
        INSERT INTO evidence_items VALUES ('ev_youtube', 'https://youtu.be/abc123', 'video:abc123', 'abc123');
        """
    )
    connection.commit()
    connection.close()


def song_decision(*, source_key: str, raw: str, decision: str, target=None) -> dict:
    return {
        "source_key": source_key,
        "inbox_id": f"inbox_{source_key}",
        "raw_song_name": raw,
        "decision": decision,
        "target_song_name": target,
        "target_catalog_match": (
            {"song_id": "song_target", "song_name": target} if target else None
        ),
    }


def youtube_decision(*, source_key: str, decision: str) -> dict:
    return {
        "source_key": source_key,
        "inbox_id": f"inbox_{source_key}",
        "decision": decision,
    }


def test_read_only_connection_rejects_writes(tmp_path):
    db = tmp_path / "master.sqlite"
    make_db(db)

    with connect_read_only(db) as connection:
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute(
                "INSERT INTO songs VALUES ('x', 'x', 'x', 'active')"
            )


def test_plan_fails_closed_when_master_db_differs_from_frozen_input(tmp_path):
    db = tmp_path / "master.sqlite"
    make_db(db)

    with pytest.raises(ValueError, match="differs from the frozen review input"):
        build_plan(master_db=db, generated_at="2026-08-18T00:00:00+09:00")


def test_song_plan_requires_explicit_materializers(tmp_path):
    db = tmp_path / "master.sqlite"
    make_db(db)
    decisions = [
        song_decision(
            source_key="merge", raw="東京おんど", decision="既存曲へ統合", target="東京音頭"
        ),
        song_decision(source_key="noise", raw="24", decision="曲名ノイズとして除外"),
        song_decision(
            source_key="new", raw="新曲", decision="新規曲候補として維持", target="新曲"
        ),
        song_decision(
            source_key="missing", raw="別名", decision="既存曲へ統合", target="存在しない曲"
        ),
    ]
    decisions[-1]["target_catalog_match"] = None

    with connect_read_only(db) as connection:
        plan = build_song_identity_plan(connection, decisions)

    assert plan["summary"]["action_counts"] == {
        "requires_merge_materializer": 1,
        "requires_retraction_materializer": 1,
        "requires_candidate_registration_from_public_source": 1,
        "blocked_target_song_missing_from_rdb": 1,
    }
    assert plan["summary"]["rdb_conflict_row_count"] == 1
    assert plan["summary"]["target_missing_from_rdb_count"] == 1


def test_youtube_presence_is_not_treated_as_proof_of_full_materialization(tmp_path):
    db = tmp_path / "master.sqlite"
    make_db(db)
    decisions = [
        youtube_decision(source_key="video:abc123|year:2026", decision="採用"),
        youtube_decision(source_key="video:absent|year:2026", decision="採用"),
        youtube_decision(source_key="video:abc123|year:2025", decision="不採用"),
        youtube_decision(source_key="video:rejected|year:2025", decision="不採用"),
    ]

    with connect_read_only(db) as connection:
        plan = build_youtube_plan(connection, decisions)

    assert plan["summary"]["action_counts"] == {
        "already_present_or_partially_materialized": 1,
        "requires_identity_packet_before_materialize": 1,
        "no_write_retraction_review_required": 1,
        "no_canonical_write": 1,
    }


def test_frozen_real_plan_accounts_for_all_505_decisions_without_write_mode():
    plan = json.loads(
        (ROOT / "data/review_backlog_canonical_apply_plan.json").read_text(
            encoding="utf-8"
        )
    )

    assert plan["mode"] == "read_only_dry_run"
    assert plan["summary"] == {
        "review_decision_count": 505,
        "decision_counts": {
            "youtube": 247,
            "publication_song_identity": 147,
            "historical_reference_quality": 60,
            "publication_event_date": 38,
            "publication_sync": 12,
            "x_gap": 1,
        },
        "production_write_ready_count": 0,
        "canonical_write_performed": False,
        "separate_repository_sync_count": 12,
        "date_promotions_allowed": 0,
    }
    assert plan["canonical_write_boundary"]["apply_mode_exists"] is False
    assert plan["master_db"]["opened_read_only"] is True
