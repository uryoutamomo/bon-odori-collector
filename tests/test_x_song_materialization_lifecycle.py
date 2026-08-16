import json
from unittest.mock import patch

import pytest

import report_apply.materialize_x_song_resolutions as materializer_module
from export_public_events import load_rdb_occurrence_songs
from master_rdb.master_db import init_db
from report_apply.event_report_helpers import link_resolved_occurrence_song
from report_apply.materialize_x_song_resolutions import materialize, run as materializer_run
from report_apply.retract_x_song_materializations import retract, run as retraction_run
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

    # An X-shaped fact without an active materialization ledger entry is not
    # authorized merely because an accepted link exists.
    conn.execute("UPDATE evidence_items SET evidence_type='x_song_claim_v2' WHERE evidence_id='evid_1'")
    assert load_rdb_occurrence_songs(conn) == {}

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


def resolved_observation(**overrides):
    row = {
        "observation_schema_version": 2,
        "observation_id": "xsong2_materialize",
        "claim_family_id": "xsclaim_materialize",
        "tweet_id": "tweet_1",
        "url": "https://x.example/tweet_1",
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


def decide_song(conn, ledger, *, action, selected_song_id=None):
    retrieval = build_song_packets(conn, ledger, phase="retrieval", generated_at=NOW)
    packet = retrieval["packets"][0]
    apply_song_results(
        conn,
        ledger,
        {packet["packet_id"]: {"packet": packet, "packet_set": retrieval}},
        {
            "schema": "x_song_resolution_results_v2",
            "results": [{
                "packet_id": packet["packet_id"],
                "action": "candidate_missing" if action == "new_song" else action,
                "selected_song_id": selected_song_id,
            }],
        },
        actor_id="oto-test",
        model_id=MODEL,
        prompt_sha256=PROMPT_SHA,
        decided_at=NOW,
    )
    if action != "new_song":
        return
    novelty = build_song_packets(conn, ledger, phase="novelty", generated_at=NOW)
    novelty_packet = novelty["packets"][0]
    apply_song_results(
        conn,
        ledger,
        {novelty_packet["packet_id"]: {"packet": novelty_packet, "packet_set": novelty}},
        {
            "schema": "x_song_resolution_results_v2",
            "results": [{"packet_id": novelty_packet["packet_id"], "action": "new_song"}],
        },
        actor_id="oto-test",
        model_id=MODEL,
        prompt_sha256=PROMPT_SHA,
        decided_at=NOW,
    )


def decide_occurrence(conn, ledger):
    packet_set = build_occurrence_packets(conn, ledger, generated_at=NOW)
    packet = packet_set["packets"][0]
    apply_occurrence_results(
        conn,
        ledger,
        packet_set,
        {
            "schema": "x_occurrence_resolution_results_v2",
            "results": [{
                "packet_id": packet["packet_id"],
                "action": "match_occurrence",
                "selected_occurrence_id": "occ_1",
            }],
        },
        actor_id="oto-test",
        model_id=MODEL,
        prompt_sha256=PROMPT_SHA,
        decided_at=NOW,
    )


def test_materializer_rolls_back_earlier_batch_writes_when_later_fact_collides(tmp_path):
    conn = init_db(tmp_path / "master.sqlite")
    seed_domain(conn)
    conn.execute(
        """
        INSERT INTO songs (
          song_id, canonical_title, normalized_title, status, created_at, updated_at
        ) VALUES ('song_daitokyo', '大東京音頭', '大東京音頭', 'active', ?, ?)
        """,
        (NOW, NOW),
    )
    conn.commit()

    first = resolved_observation(
        observation_id="xsong2_batch_a",
        claim_family_id="xsclaim_batch_a",
    )
    second = resolved_observation(
        observation_id="xsong2_batch_z",
        claim_family_id="xsclaim_batch_z",
        song_name="大東京音頭",
        evidence_quote="曲目は大東京音頭です",
    )
    for row, song_id in ((first, "song_tokyo"), (second, "song_daitokyo")):
        single = {"observations": [row]}
        decide_song(conn, single, action="match_song", selected_song_id=song_id)
        decide_occurrence(conn, single)

    conn.execute(
        """
        INSERT INTO occurrence_songs (
          occurrence_song_id, origin, occurrence_id, song_id, song_title_raw,
          normalized_title, role, evidence_status, confidence, created_at, updated_at
        ) VALUES ('osong_collision', 'curated', 'occ_1', 'song_tokyo', '大東京音頭',
                  '大東京音頭', 'setlist', 'announced', 'high', ?, ?)
        """,
        (NOW, NOW),
    )
    conn.commit()
    before = {
        "facts": conn.execute("SELECT COUNT(*) FROM occurrence_songs").fetchone()[0],
        "evidence": conn.execute("SELECT COUNT(*) FROM evidence_items").fetchone()[0],
        "materializations": conn.execute(
            "SELECT COUNT(*) FROM x_song_materializations"
        ).fetchone()[0],
    }

    with pytest.raises(ValueError, match="conflicts"):
        materialize(
            conn,
            {"observations": [first, second]},
            actor_id="oto-test",
            now=NOW,
        )

    assert conn.execute("SELECT COUNT(*) FROM occurrence_songs").fetchone()[0] == before["facts"]
    assert conn.execute("SELECT COUNT(*) FROM evidence_items").fetchone()[0] == before["evidence"]
    assert conn.execute(
        "SELECT COUNT(*) FROM x_song_materializations"
    ).fetchone()[0] == before["materializations"]
    assert conn.execute(
        "SELECT COUNT(*) FROM occurrence_songs WHERE normalized_title='東京音頭'"
    ).fetchone()[0] == 0


def test_materializer_promotes_candidate_maps_announced_to_setlist_and_retracts(tmp_path):
    conn = init_db(tmp_path / "master.sqlite")
    seed_domain(conn, song_status="候補")
    conn.commit()
    ledger = {"observations": [resolved_observation()]}
    decide_song(conn, ledger, action="match_song", selected_song_id="song_tokyo")
    decide_occurrence(conn, ledger)
    conn.execute(
        """
        INSERT INTO songs (
          song_id, canonical_title, normalized_title, status, created_at, updated_at
        ) VALUES ('song_unrelated', '無関係音頭', '無関係音頭', '候補', ?, ?)
        """,
        (NOW, NOW),
    )
    conn.execute(
        """
        INSERT INTO event_occurrences (
          occurrence_id, series_id, event_year, display_name,
          lifecycle_status, created_at, updated_at
        ) VALUES ('occ_unrelated', 'series_1', 2027, '無関係の開催回',
                  'draft', ?, ?)
        """,
        (NOW, NOW),
    )
    conn.commit()

    observation_path = tmp_path / "observations.json"
    observation_path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    conn.close()
    dry_run = materializer_run(
        db_path=tmp_path / "master.sqlite",
        observation_path=observation_path,
        actor_id="oto-test",
        now=NOW,
    )
    assert dry_run["mode"] == "dry_run"
    conn = __import__("sqlite3").connect(tmp_path / "master.sqlite")
    assert conn.execute("SELECT COUNT(*) FROM x_song_materializations").fetchone()[0] == 0

    original_catalog_snapshot = materializer_module.catalog_snapshot

    def locked_catalog_snapshot(active_conn):
        assert active_conn.in_transaction, "snapshot must be validated after BEGIN IMMEDIATE"
        return original_catalog_snapshot(active_conn)

    with patch.object(materializer_module, "catalog_snapshot", side_effect=locked_catalog_snapshot):
        report = materialize(conn, ledger, actor_id="oto-test", now=NOW)
    materialization_id = report["applied"][0]["materialization_id"]
    song = conn.execute("SELECT status FROM songs WHERE song_id='song_tokyo'").fetchone()[0]
    fact = conn.execute(
        "SELECT role, evidence_status, origin FROM occurrence_songs"
    ).fetchone()
    assert song == "active"
    assert tuple(fact) == ("setlist", "announced", "observed_x_post")
    conn.row_factory = __import__("sqlite3").Row
    assert [row["name"] for row in load_rdb_occurrence_songs(conn)["occ_1"]] == ["東京音頭"]

    conn.close()
    dry_retract = retraction_run(
        db_path=tmp_path / "master.sqlite",
        materialization_ids=[materialization_id],
        actor_id="oto-test",
        reason_code="source_correction",
        reason_detail=None,
        now="2026-08-17T00:00:00+00:00",
    )
    assert dry_retract["mode"] == "dry_run"
    conn = __import__("sqlite3").connect(tmp_path / "master.sqlite")
    assert conn.execute(
        "SELECT status FROM x_song_materializations WHERE materialization_id=?",
        (materialization_id,),
    ).fetchone()[0] == "active"

    retracted = retract(
        conn,
        [materialization_id],
        actor_id="oto-test",
        reason_code="source_correction",
        reason_detail=None,
        now="2026-08-17T00:00:00+00:00",
    )
    assert retracted["retracted"][0]["song_action"] == "restored_candidate"
    assert conn.execute("SELECT status FROM songs WHERE song_id='song_tokyo'").fetchone()[0] == "候補"
    conn.row_factory = __import__("sqlite3").Row
    assert load_rdb_occurrence_songs(conn) == {}

    exact_retry = retract(
        conn,
        [materialization_id],
        actor_id="oto-test",
        reason_code="source_correction",
        reason_detail=None,
        now="2026-08-17T00:00:00+00:00",
    )
    assert exact_retry["no_op"] == [materialization_id]


def test_materializer_rechecks_event_dependency_before_writing(tmp_path):
    conn = init_db(tmp_path / "master.sqlite")
    seed_domain(conn)
    conn.commit()
    ledger = {"observations": [resolved_observation()]}
    decide_song(conn, ledger, action="match_song", selected_song_id="song_tokyo")
    decide_occurrence(conn, ledger)
    conn.execute(
        """
        UPDATE x_occurrence_resolution_decisions
        SET resolution_source='report_dependency',
            event_dependency_key='event-family-new-revision',
            dependency_decision_id='event-decision-old'
        WHERE observation_id='xsong2_materialize' AND status='active'
        """
    )
    conn.commit()

    with patch.object(
        materializer_module,
        "resolve_event_dependency",
        return_value={"action": "dependency_pending", "reason_code": "event_decision_pending"},
    ):
        report = materialize(conn, ledger, actor_id="oto-test", now=NOW)
    assert report["applied"] == []
    assert report["held"] == [{
        "observation_id": "xsong2_materialize",
        "reason": "event_dependency_stale",
    }]
    assert conn.execute("SELECT COUNT(*) FROM occurrence_songs").fetchone()[0] == 0


def test_new_song_requires_novelty_decision_and_is_tombstoned_on_retraction(tmp_path):
    conn = init_db(tmp_path / "master.sqlite")
    seed_domain(conn)
    conn.commit()
    ledger = {
        "observations": [resolved_observation(song_name="新しい盆唄", evidence_quote="曲目は新しい盆唄です")]
    }
    decide_song(conn, ledger, action="new_song")
    decide_occurrence(conn, ledger)
    report = materialize(conn, ledger, actor_id="oto-test", now=NOW)
    materialization = report["applied"][0]
    assert materialization["song_change_kind"] == "created"
    assert conn.execute(
        "SELECT status FROM songs WHERE song_id=?", (materialization["song_id"],)
    ).fetchone()[0] == "active"

    retracted = retract(
        conn,
        [materialization["materialization_id"]],
        actor_id="oto-test",
        reason_code="claim_removed",
        reason_detail=None,
        now="2026-08-17T00:00:00+00:00",
    )
    assert retracted["retracted"][0]["song_action"] == "tombstoned_created"
    assert conn.execute(
        "SELECT status FROM songs WHERE song_id=?", (materialization["song_id"],)
    ).fetchone()[0] == "無効"


def test_other_accepted_evidence_keeps_shared_fact_public_on_x_retraction(tmp_path):
    conn = init_db(tmp_path / "master.sqlite")
    seed_domain(conn)
    conn.commit()
    ledger = {"observations": [resolved_observation(claim_type="observed")]}
    decide_song(conn, ledger, action="match_song", selected_song_id="song_tokyo")
    decide_occurrence(conn, ledger)
    report = materialize(conn, ledger, actor_id="oto-test", now=NOW)
    materialization_id = report["applied"][0]["materialization_id"]
    occurrence_song_id = conn.execute(
        "SELECT occurrence_song_id FROM x_song_materializations WHERE materialization_id=?",
        (materialization_id,),
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO evidence_items (evidence_id, platform, evidence_type, source_key, raw_json)
        VALUES ('evid_other', 'web', 'official_setlist', 'other', '{}')
        """
    )
    conn.execute(
        """
        INSERT INTO occurrence_song_evidence_links (
          occurrence_song_id, evidence_id, link_status
        ) VALUES (?, 'evid_other', 'accepted')
        """,
        (occurrence_song_id,),
    )
    conn.commit()

    retracted = retract(
        conn,
        [materialization_id],
        actor_id="oto-test",
        reason_code="x_deleted",
        reason_detail=None,
        now="2026-08-17T00:00:00+00:00",
    )
    assert retracted["retracted"][0]["occurrence_song_action"] == "retained_shared_evidence"
    conn.row_factory = __import__("sqlite3").Row
    assert [row["name"] for row in load_rdb_occurrence_songs(conn)["occ_1"]] == ["東京音頭"]


def test_candidate_cleanup_is_independent_of_shared_retraction_order(tmp_path):
    conn = init_db(tmp_path / "master.sqlite")
    seed_domain(conn, song_status="候補")
    conn.commit()
    ledger = {
        "observations": [
            resolved_observation(),
            resolved_observation(
                observation_id="xsong2_materialize_2",
                claim_family_id="xsclaim_materialize_2",
                tweet_id="tweet_2",
                url="https://x.example/tweet_2",
            ),
        ]
    }
    song_packets = build_song_packets(conn, ledger, phase="retrieval", generated_at=NOW)
    song_entries = {
        packet["packet_id"]: {"packet": packet, "packet_set": song_packets}
        for packet in song_packets["packets"]
    }
    apply_song_results(
        conn,
        ledger,
        song_entries,
        {
            "schema": "x_song_resolution_results_v2",
            "results": [
                {
                    "packet_id": packet["packet_id"],
                    "action": "match_song",
                    "selected_song_id": "song_tokyo",
                }
                for packet in song_packets["packets"]
            ],
        },
        actor_id="oto-test",
        model_id=MODEL,
        prompt_sha256=PROMPT_SHA,
        decided_at=NOW,
    )
    occurrence_packets = build_occurrence_packets(conn, ledger, generated_at=NOW)
    apply_occurrence_results(
        conn,
        ledger,
        occurrence_packets,
        {
            "schema": "x_occurrence_resolution_results_v2",
            "results": [
                {
                    "packet_id": packet["packet_id"],
                    "action": "match_occurrence",
                    "selected_occurrence_id": "occ_1",
                }
                for packet in occurrence_packets["packets"]
            ],
        },
        actor_id="oto-test",
        model_id=MODEL,
        prompt_sha256=PROMPT_SHA,
        decided_at=NOW,
    )
    report = materialize(conn, ledger, actor_id="oto-test", now=NOW)
    changes = {row["song_change_kind"]: row["materialization_id"] for row in report["applied"]}
    assert set(changes) == {"promoted_candidate", "none"}

    first = retract(
        conn,
        [changes["promoted_candidate"]],
        actor_id="oto-test",
        reason_code="test",
        reason_detail=None,
        now="2026-08-17T00:00:00+00:00",
    )
    assert first["retracted"][0]["song_action"] == "retained_shared_or_changed"
    second = retract(
        conn,
        [changes["none"]],
        actor_id="oto-test",
        reason_code="test",
        reason_detail=None,
        now="2026-08-18T00:00:00+00:00",
    )
    assert second["retracted"][0]["song_action"] == "restored_candidate"
    assert conn.execute("SELECT status FROM songs WHERE song_id='song_tokyo'").fetchone()[0] == "候補"
