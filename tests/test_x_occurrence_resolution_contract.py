import json

import pytest

from event_model.local_judgment_migration import (
    migrate_event_inbox_candidate,
    migrate_local_judgment_contract,
)
from master_rdb.master_db import init_db, stable_id
from review_inbox_adapters.x_occurrence_resolution_contract import (
    apply_results,
    build_packet_set,
)


NOW = "2026-08-16T00:00:00+00:00"
MODEL = "test-model"
PROMPT_SHA = "1" * 64


def claim(**overrides):
    row = {
        "observation_schema_version": 2,
        "observation_id": "xsong2_1",
        "claim_family_id": "xsclaim_1",
        "tweet_id": "tweet_1",
        "url": "https://x.example/tweet_1",
        "song_name": "東京音頭",
        "claim_type": "announced",
        "evidence_quote": "曲目は東京音頭です",
        "claim_type_conflict": False,
        "event_name": "試験盆踊り",
        "event_name_in_text": True,
        "event_context_valid": True,
        "event_date_start": "2026-08-20",
        "event_date_end": "2026-08-20",
        "event_venue_name": "試験公園",
        "event_ward": "足立区",
        "event_dependency_key": None,
    }
    row.update(overrides)
    return row


def make_db(tmp_path):
    conn = init_db(tmp_path / "master.sqlite")
    conn.execute(
        """
        INSERT INTO venues (
          venue_id, canonical_name, normalized_name, area, review_status, created_at, updated_at
        ) VALUES ('venue_1', '試験公園', '試験公園', '足立区', 'active', ?, ?)
        """,
        (NOW, NOW),
    )
    conn.execute(
        """
        INSERT INTO event_series (
          series_id, series_key, canonical_name, normalized_name, usual_venue_id,
          status, created_at, updated_at
        ) VALUES ('series_1', 'series-1', '試験盆踊り', '試験盆踊り', 'venue_1',
                  'active', ?, ?)
        """,
        (NOW, NOW),
    )
    conn.execute(
        """
        INSERT INTO event_occurrences (
          occurrence_id, series_id, event_year, display_name, venue_id,
          date_start, date_end, date_status, lifecycle_status,
          current_event_state, date_certainty_tier, created_at, updated_at
        ) VALUES ('occ_1', 'series_1', 2026, '試験盆踊り', 'venue_1',
                  '2026-08-20', '2026-08-20', 'confirmed', 'published',
                  'confirmed', 'confirmed', ?, ?)
        """,
        (NOW, NOW),
    )
    conn.commit()
    return conn


def seed_accepted_event_decision(conn, dependency_key, occurrence_match="occ_1"):
    migrate_local_judgment_contract(conn)
    migrate_event_inbox_candidate(conn)
    conn.execute(
        """
        INSERT INTO review_inbox_items (
          inbox_id, kind, domain, title, source_id, source_key, status,
          source_payload_hash, last_seen_at, payload_json, created_at, updated_at,
          contract_domain, contract_lane, revision_family_key, revision
        ) VALUES ('inbox_1', 'event_candidate', 'X', '試験盆踊り', 'report_1', 'report#1',
                  'candidate', ?, ?, '{}', ?, ?, 'event', 'event_create', ?, 1)
        """,
        ("a" * 64, NOW, NOW, NOW, dependency_key),
    )
    identity = {
        "occurrence_match": occurrence_match,
        "series_match": "series_1" if occurrence_match != "none" else "none",
        "venue_match": "venue_1" if occurrence_match != "none" else "none",
    }
    conn.execute(
        """
        INSERT INTO canonical_decision_ledger (
          decision_id, schema_version, packet_id, packet_sha256, inbox_id,
          domain, lane, source_id, source_key, source_payload_hash, action,
          queue_state_before, queue_state_after, payload_json,
          actor_type, actor_id, decision_channel, decided_at, created_at
        ) VALUES ('event_decision_1', 1, 'packet_1', ?, 'inbox_1',
                  'event', 'event_create', 'report_1', 'report#1', ?, 'accept',
                  'eligible', 'closed', ?, 'agent', 'oto', 'llm', ?, ?)
        """,
        ("b" * 64, "a" * 64, json.dumps(identity), NOW, NOW),
    )
    conn.commit()


def test_direct_candidates_require_valid_event_context_and_never_create_occurrence(tmp_path):
    conn = make_db(tmp_path)
    invalid = build_packet_set(
        conn,
        {"observations": [claim(event_context_valid=False)]},
        generated_at=NOW,
    )
    assert invalid["packets"] == []
    assert invalid["excluded"][0]["reason"] == "insufficient_event_context"
    anchorless = build_packet_set(
        conn,
        {"observations": [claim(event_date_start=None, event_date_end=None, event_venue_name=None)]},
        generated_at=NOW,
    )
    assert anchorless["packets"] == []

    ledger = {"observations": [claim()]}
    packet_set = build_packet_set(conn, ledger, generated_at=NOW)
    packet = packet_set["packets"][0]
    assert packet["resolution_source"] == "direct_candidates"
    assert packet["candidate_rows"][0]["occurrence_id"] == "occ_1"
    assert packet["allowed_actions"] == ["match_occurrence", "unresolved"]

    report = apply_results(
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
        actor_id="oto-local",
        model_id=MODEL,
        prompt_sha256=PROMPT_SHA,
        decided_at=NOW,
    )
    assert report["applied"] == 1
    assert conn.execute("SELECT COUNT(*) FROM event_occurrences").fetchone()[0] == 1


def test_unresolved_occurrence_waits_for_snapshot_change(tmp_path):
    conn = make_db(tmp_path)
    ledger = {"observations": [claim()]}
    packet_set = build_packet_set(conn, ledger, generated_at=NOW)
    packet = packet_set["packets"][0]
    apply_results(
        conn,
        ledger,
        packet_set,
        {
            "schema": "x_occurrence_resolution_results_v2",
            "results": [{"packet_id": packet["packet_id"], "action": "unresolved"}],
        },
        actor_id="oto-local",
        model_id=MODEL,
        prompt_sha256=PROMPT_SHA,
        decided_at=NOW,
    )
    unchanged = build_packet_set(conn, ledger, generated_at=NOW)
    assert unchanged["packets"] == []
    assert unchanged["excluded"] == [{
        "observation_id": "xsong2_1",
        "reason": "already_decided_current_snapshot",
    }]

    conn.execute("UPDATE event_occurrences SET display_name=? WHERE occurrence_id='occ_1'", ("試験盆踊り 改訂",))
    changed = build_packet_set(conn, ledger, generated_at=NOW)
    assert len(changed["packets"]) == 1
    assert changed["packets"][0]["packet_id"] != packet["packet_id"]


def test_resolved_occurrence_is_not_reopened_by_unrelated_snapshot_change(tmp_path):
    conn = make_db(tmp_path)
    ledger = {"observations": [claim()]}
    packet_set = build_packet_set(conn, ledger, generated_at=NOW)
    packet = packet_set["packets"][0]
    apply_results(
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
        actor_id="oto-local",
        model_id=MODEL,
        prompt_sha256=PROMPT_SHA,
        decided_at=NOW,
    )
    conn.execute(
        """
        INSERT INTO event_occurrences (
          occurrence_id, series_id, event_year, display_name, venue_id,
          lifecycle_status, created_at, updated_at
        ) VALUES ('occ_unrelated', 'series_1', 2027, '無関係の開催回', 'venue_1',
                  'draft', ?, ?)
        """,
        (NOW, NOW),
    )

    packet_set = build_packet_set(conn, ledger, generated_at=NOW)
    assert packet_set["packets"] == []
    assert packet_set["excluded"] == [{
        "observation_id": "xsong2_1",
        "reason": "identity_already_resolved",
    }]


def test_event_dependency_is_mechanical_and_pending_until_event_decision(tmp_path):
    conn = make_db(tmp_path)
    ledger = {"observations": [claim(event_dependency_key="event-family-1")]}
    migrate_local_judgment_contract(conn)
    migrate_event_inbox_candidate(conn)
    conn.commit()

    pending = build_packet_set(conn, ledger, generated_at=NOW)
    assert pending["machine_results"]["results"][0]["action"] == "dependency_pending"
    assert pending["packets"][0]["candidate_rows"] == []
    apply_results(
        conn,
        ledger,
        pending,
        pending["machine_results"],
        actor_id="system:event-dependency",
        model_id="deterministic-event-dependency",
        prompt_sha256=PROMPT_SHA,
        decided_at=NOW,
    )
    still_pending = build_packet_set(conn, ledger, generated_at=NOW)
    assert still_pending["packets"] == []
    assert still_pending["machine_results"]["results"] == []

    seed_accepted_event_decision(conn, "event-family-1")
    matched = build_packet_set(conn, ledger, generated_at=NOW)
    machine = matched["machine_results"]
    assert machine["results"][0]["selected_occurrence_id"] == "occ_1"
    assert matched["packets"][0]["candidate_rows"][0]["occurrence_id"] == "occ_1"
    apply_results(
        conn,
        ledger,
        matched,
        machine,
        actor_id="system:event-dependency",
        model_id="deterministic-event-dependency",
        prompt_sha256=PROMPT_SHA,
        decided_at=NOW,
    )
    row = conn.execute(
        "SELECT resolution_source, action, selected_occurrence_id "
        "FROM x_occurrence_resolution_decisions WHERE status='active'"
    ).fetchone()
    assert tuple(row) == ("report_dependency", "match_occurrence", "occ_1")


def test_event_dependency_never_reuses_accept_from_an_older_revision(tmp_path):
    conn = make_db(tmp_path)
    dependency_key = "event-family-revised"
    seed_accepted_event_decision(conn, dependency_key)
    ledger = {"observations": [claim(event_dependency_key=dependency_key)]}
    accepted = build_packet_set(conn, ledger, generated_at=NOW)
    assert accepted["machine_results"]["results"][0]["action"] == "match_occurrence"
    apply_results(
        conn,
        ledger,
        accepted,
        accepted["machine_results"],
        actor_id="system:event-dependency",
        model_id="deterministic-event-dependency",
        prompt_sha256=PROMPT_SHA,
        decided_at=NOW,
    )
    conn.execute(
        """
        INSERT INTO review_inbox_items (
          inbox_id, kind, domain, title, source_id, source_key, status,
          source_payload_hash, last_seen_at, payload_json, created_at, updated_at,
          contract_domain, contract_lane, revision_family_key, revision
        ) VALUES ('inbox_2', 'event_candidate', 'X', '試験盆踊り 改訂', 'report_2', 'report#2',
                  'candidate', ?, ?, '{}', ?, ?, 'event', 'event_create', ?, 2)
        """,
        ("c" * 64, NOW, NOW, NOW, dependency_key),
    )
    conn.execute(
        "UPDATE review_inbox_items SET superseded_by_inbox_id='inbox_2' WHERE inbox_id='inbox_1'"
    )
    conn.commit()

    packet_set = build_packet_set(conn, ledger, generated_at=NOW)
    result = packet_set["machine_results"]["results"][0]
    assert result["action"] == "dependency_pending"
    assert result["reason_code"] == "event_decision_pending"


def test_none_identity_resolves_only_after_change_request_evidence_is_linked(tmp_path):
    conn = make_db(tmp_path)
    dependency_key = "event-family-new"
    ledger = {"observations": [claim(event_dependency_key=dependency_key)]}
    seed_accepted_event_decision(conn, dependency_key, occurrence_match="none")

    before = build_packet_set(conn, ledger, generated_at=NOW)
    assert before["machine_results"]["results"][0]["action"] == "dependency_pending"

    request_id = stable_id("chrq", "event_decision_1")
    conn.execute(
        """
        INSERT INTO evidence_items (
          evidence_id, platform, evidence_type, source_key, raw_json
        ) VALUES ('event_evidence_1', 'web', 'official_current_year', 'source', ?)
        """,
        (json.dumps({"request_id": request_id, "change_type": "create_event_series"}),),
    )
    conn.execute(
        """
        INSERT INTO occurrence_evidence_links (
          occurrence_id, evidence_id, target, link_status
        ) VALUES ('occ_1', 'event_evidence_1', 'date_and_venue', 'accepted')
        """
    )
    conn.commit()
    after = build_packet_set(conn, ledger, generated_at=NOW)
    assert after["machine_results"]["results"][0]["selected_occurrence_id"] == "occ_1"


def test_dependency_result_cannot_override_machine_target(tmp_path):
    conn = make_db(tmp_path)
    seed_accepted_event_decision(conn, "event-family-1")
    ledger = {"observations": [claim(event_dependency_key="event-family-1")]}
    packet_set = build_packet_set(conn, ledger, generated_at=NOW)
    packet = packet_set["packets"][0]
    with pytest.raises(ValueError, match="frozen candidate set|not allowed"):
        apply_results(
            conn,
            ledger,
            packet_set,
            {
                "schema": "x_occurrence_resolution_results_v2",
                "results": [{
                    "packet_id": packet["packet_id"],
                    "action": "unresolved",
                }],
            },
            actor_id="untrusted",
            model_id=MODEL,
            prompt_sha256=PROMPT_SHA,
            decided_at=NOW,
        )
