"""Mutation-oriented guards for E2-S v2 resolution and materialization.

These cases deliberately live apart from the lifecycle tests: each asserts one
hold/rejection that must remain fail-closed when the materializer is changed.
"""

import pytest

from master_rdb.master_db import init_db
from report_apply.materialize_x_song_resolutions import materialize
from review_inbox_adapters.x_occurrence_resolution_contract import (
    apply_results as apply_occurrence_results,
    build_packet_set as build_occurrence_packets,
)
from review_inbox_adapters.x_song_resolution_contract import (
    apply_results as apply_song_results,
    build_packet_set as build_song_packets,
)


NOW = "2026-08-16T00:00:00+00:00"
MODEL = "test-model"
PROMPT_SHA = "1" * 64


def observation(**overrides):
    row = {
        "observation_schema_version": 2,
        "observation_id": "xsong2_guard",
        "claim_family_id": "xsclaim_guard",
        "tweet_id": "tweet_guard",
        "url": "https://x.example/tweet_guard",
        "account": "@official",
        "event_name": "テスト盆踊り",
        "event_name_in_text": True,
        "song_name": "東京音頭",
        "claim_type": "announced",
        "evidence_quote": "曲目は東京音頭です",
        "claim_type_conflict": False,
        "event_context_valid": True,
        "event_date_start": "2026-08-20",
        "event_date_end": "2026-08-20",
        "event_venue_name": None,
        "event_dependency_key": None,
    }
    row.update(overrides)
    return row


def make_db(tmp_path):
    conn = init_db(tmp_path / "master.sqlite")
    for song_id, title, status in [
        ("song_tokyo", "東京音頭", "active"),
        ("song_candidate", "候補音頭", "候補"),
        ("song_rejected", "大人の部", "無効"),
    ]:
        conn.execute(
            """
            INSERT INTO songs (
              song_id, canonical_title, normalized_title, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (song_id, title, title, status, NOW, NOW),
        )
    conn.execute(
        """
        INSERT INTO event_series (
          series_id, series_key, canonical_name, normalized_name, created_at, updated_at
        ) VALUES ('series_guard', 'series-guard', 'テスト盆踊り', 'テスト盆踊り', ?, ?)
        """,
        (NOW, NOW),
    )
    conn.execute(
        """
        INSERT INTO event_occurrences (
          occurrence_id, series_id, event_year, display_name, created_at, updated_at
        ) VALUES ('occ_guard', 'series_guard', 2026, 'テスト盆踊り', ?, ?)
        """,
        (NOW, NOW),
    )
    conn.commit()
    return conn


def apply_song(conn, ledger, action, selected_song_id=None):
    packet_set = build_song_packets(conn, ledger, phase="retrieval", generated_at=NOW)
    packet = packet_set["packets"][0]
    apply_song_results(
        conn,
        ledger,
        {packet["packet_id"]: {"packet": packet, "packet_set": packet_set}},
        {"schema": "x_song_resolution_results_v2", "results": [{
            "packet_id": packet["packet_id"],
            "action": action,
            "selected_song_id": selected_song_id,
        }]},
        actor_id="oto-test", model_id=MODEL, prompt_sha256=PROMPT_SHA, decided_at=NOW,
    )


def apply_new_song(conn, ledger):
    apply_song(conn, ledger, "candidate_missing")
    packet_set = build_song_packets(conn, ledger, phase="novelty", generated_at=NOW)
    packet = packet_set["packets"][0]
    apply_song_results(
        conn,
        ledger,
        {packet["packet_id"]: {"packet": packet, "packet_set": packet_set}},
        {"schema": "x_song_resolution_results_v2", "results": [{
            "packet_id": packet["packet_id"], "action": "new_song", "selected_song_id": None,
        }]},
        actor_id="oto-test", model_id=MODEL, prompt_sha256=PROMPT_SHA, decided_at=NOW,
    )


def apply_occurrence(conn, ledger):
    packet_set = build_occurrence_packets(conn, ledger, generated_at=NOW)
    packet = packet_set["packets"][0]
    apply_occurrence_results(
        conn,
        ledger,
        packet_set,
        {"schema": "x_occurrence_resolution_results_v2", "results": [{
            "packet_id": packet["packet_id"],
            "action": "match_occurrence",
            "selected_occurrence_id": "occ_guard",
        }]},
        actor_id="oto-test", model_id=MODEL, prompt_sha256=PROMPT_SHA, decided_at=NOW,
    )


def resolve_current(conn, ledger, *, song_id="song_tokyo"):
    apply_song(conn, ledger, "match_song", song_id)
    apply_occurrence(conn, ledger)


def held_reason(conn, ledger):
    report = materialize(conn, ledger, actor_id="oto-test", now=NOW)
    assert report["applied"] == []
    return report["held"]


def test_novelty_packet_rejects_unresolved_retrieval_decision(tmp_path):
    conn = make_db(tmp_path)
    ledger = {"observations": [observation()]}
    apply_song(conn, ledger, "unresolved")

    novelty = build_song_packets(conn, ledger, phase="novelty", generated_at=NOW)

    assert novelty["packets"] == []
    assert novelty["excluded"] == [{
        "observation_id": "xsong2_guard", "reason": "retrieval_not_candidate_missing",
    }]


def test_new_song_alias_collision_aborts_materialization(tmp_path):
    conn = make_db(tmp_path)
    ledger = {"observations": [observation(song_name="新しい盆唄", evidence_quote="曲目は新しい盆唄です")]}
    apply_new_song(conn, ledger)
    apply_occurrence(conn, ledger)
    conn.execute(
        """
        INSERT INTO song_aliases (song_id, alias, normalized_alias, source)
        VALUES ('song_tokyo', '新しい盆唄', '新しい盆唄', 'late_catalog_change')
        """
    )
    conn.commit()

    with pytest.raises(ValueError, match="collides with the catalog"):
        materialize(conn, ledger, actor_id="oto-test", now=NOW)
    assert conn.execute("SELECT COUNT(*) FROM songs WHERE canonical_title='新しい盆唄'").fetchone()[0] == 0


def test_materializer_holds_when_observation_changed_after_both_decisions(tmp_path):
    conn = make_db(tmp_path)
    ledger = {"observations": [observation()]}
    resolve_current(conn, ledger)
    ledger["observations"][0]["evidence_quote"] = "東京音頭です"

    assert held_reason(conn, ledger) == [{
        "observation_id": "xsong2_guard", "reason": "observation_stale",
    }]


def test_materializer_holds_when_selected_song_catalog_row_is_stale(tmp_path):
    conn = make_db(tmp_path)
    ledger = {"observations": [observation()]}
    resolve_current(conn, ledger)
    conn.execute("UPDATE songs SET status='無効' WHERE song_id='song_tokyo'")
    conn.commit()

    assert held_reason(conn, ledger) == [{
        "observation_id": "xsong2_guard", "reason": "song_catalog_stale",
    }]


def test_materializer_holds_when_selected_occurrence_snapshot_is_stale(tmp_path):
    conn = make_db(tmp_path)
    ledger = {"observations": [observation()]}
    resolve_current(conn, ledger)
    conn.execute("UPDATE event_occurrences SET display_name='改名された盆踊り' WHERE occurrence_id='occ_guard'")
    conn.commit()

    assert held_reason(conn, ledger) == [{
        "observation_id": "xsong2_guard", "reason": "occurrence_snapshot_stale",
    }]


def test_invalid_song_cannot_be_promoted_by_materialization(tmp_path):
    conn = make_db(tmp_path)
    ledger = {"observations": [observation(song_name="大人の部", evidence_quote="曲目は大人の部です")]}
    resolve_current(conn, ledger, song_id="song_rejected")

    with pytest.raises(ValueError, match="neither active nor a promotable candidate"):
        materialize(conn, ledger, actor_id="oto-test", now=NOW)
    assert conn.execute("SELECT status FROM songs WHERE song_id='song_rejected'").fetchone()[0] == "無効"


def test_prior_active_revision_blocks_current_observation_materialization(tmp_path):
    conn = make_db(tmp_path)
    ledger = {"observations": [observation()]}
    resolve_current(conn, ledger)
    first = materialize(conn, ledger, actor_id="oto-test", now=NOW)
    assert len(first["applied"]) == 1
    conn.execute(
        """
        UPDATE x_song_materializations SET observation_sha256='old-revision-sha'
        WHERE observation_id='xsong2_guard' AND status='active'
        """
    )
    conn.commit()

    assert held_reason(conn, ledger) == [{
        "observation_id": "xsong2_guard", "reason": "prior_revision_active",
    }]
