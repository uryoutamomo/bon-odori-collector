import sqlite3

import pytest

from event_model.local_judgment_migration import migrate_local_judgment_contract
from review_inbox_adapters.local_judgment_contract import (
    ContractError, build_canonical_hold, build_user_decision, canonicalize_raw_judgment,
    validate_canonical_decision,
)


AGENT = {"actor_type": "agent", "actor_id": "local-llm", "decision_channel": "llm"}
USER = {"actor_type": "user", "actor_id": "uchida-console-session", "decision_channel": "console"}


def raw(packet_id="p1", *, actor=AGENT):
    return canonicalize_raw_judgment({
        "packet_id": packet_id, "inbox_id": "inbox-1", "source_id": "official_source",
        "source_key": "source-1", "requested_action": "hold", "actor_id": "uchida",
        "payload": {"actor_type": "user"},
    }, trusted_actor=actor)


def candidate():
    return {"candidate_id": "august-window", "eligible_at": "2026-07-20T00:00:00+09:00",
            "window_start": "2026-07-19T00:00:00+09:00", "window_end": "2026-07-21T00:00:00+09:00",
            "occurrence_ids": ["occ-2026"], "evidence_ids": ["evidence-2025"],
            "retrieved_at": "2026-06-01T00:00:00+09:00", "calculation_version": "announcement-window/v1",
            "input_hash": "a" * 64}


def awaiting_hold():
    return {"hold_id": "hold-1", "inbox_id": "inbox-1", "status": "open",
            "hold_mode": "awaiting_user", "reason_code": "requires_policy_judgment"}


def test_actor_identity_is_from_trusted_context_not_input_json():
    packet = raw()
    assert packet["actor_id"] == "local-llm"
    assert packet["actor_type"] == "agent"


def test_raw_packet_rejects_actions_outside_the_active_finite_registry():
    with pytest.raises(ContractError, match="active finite registry"):
        canonicalize_raw_judgment({
            "packet_id": "bad", "inbox_id": "inbox-1", "source_id": "source",
            "source_key": "key", "requested_action": "invent_new_action",
        }, trusted_actor=AGENT)


def test_deferred_retry_freezes_machine_candidate_and_rejects_outside_window():
    packet = build_canonical_hold(raw(), reason_code="awaiting_official_announcement",
                                  retry_candidates=[candidate()], selected_candidate_id="august-window")
    assert validate_canonical_decision(packet)["next_eligible_at"] == candidate()["eligible_at"]
    bad = candidate(); bad["eligible_at"] = "2026-07-22T00:00:00+09:00"
    with pytest.raises(ContractError, match="outside"):
        build_canonical_hold(raw(), reason_code="awaiting_official_announcement", retry_candidates=[bad], selected_candidate_id="august-window")


@pytest.mark.parametrize("reason", ["unknown", "awaiting_official_announcement"])
def test_unknown_reason_or_missing_machine_candidate_is_rejected(reason):
    with pytest.raises(ContractError):
        build_canonical_hold(raw(), reason_code=reason)


def test_awaiting_user_has_no_retry_date_and_only_open_hold_allows_console_decision():
    hold = build_canonical_hold(raw(), reason_code="requires_policy_judgment")
    assert hold["queue_state_after"] == "awaiting_user"
    assert hold["next_eligible_at"] is None
    decision = build_user_decision(raw("p2", actor=USER), action="accept", open_hold=awaiting_hold())
    assert validate_canonical_decision(decision)["queue_state_after"] == "closed"
    with pytest.raises(ContractError, match="open awaiting_user"):
        build_user_decision(raw("p3", actor=USER), action="accept", open_hold={})


@pytest.mark.parametrize("before", ["eligible", "deferred_retry"])
def test_forbidden_direct_user_transitions_are_rejected(before):
    packet = build_user_decision(raw("p4", actor=USER), action="reject", open_hold=awaiting_hold())
    packet["queue_state_before"] = before
    with pytest.raises(ContractError, match="awaiting_user"):
        validate_canonical_decision(packet)


def test_user_closed_item_has_no_llm_redecision_route():
    packet = build_canonical_hold(raw("p5"), reason_code="requires_policy_judgment")
    packet["queue_state_before"] = "closed"
    with pytest.raises(ContractError, match="eligible-to-hold"):
        validate_canonical_decision(packet)


def test_hold_mode_mismatch_and_awaiting_user_date_are_rejected():
    packet = build_canonical_hold(raw("p6"), reason_code="requires_policy_judgment")
    packet["hold_mode"] = "deferred_retry"
    with pytest.raises(ContractError, match="reason_code"):
        validate_canonical_decision(packet)
    packet = build_canonical_hold(raw("p7"), reason_code="requires_policy_judgment")
    packet["next_eligible_at"] = candidate()["eligible_at"]
    with pytest.raises(ContractError, match="only deferred"):
        validate_canonical_decision(packet)


def test_deferred_retry_cannot_lose_its_machine_retry_packet():
    packet = build_canonical_hold(raw("p8"), reason_code="awaiting_official_announcement",
                                  retry_candidates=[candidate()], selected_candidate_id="august-window")
    packet["next_eligible_at"] = None
    with pytest.raises(ContractError, match="frozen machine"):
        validate_canonical_decision(packet)


def test_additive_migration_is_idempotent_and_preserves_legacy_inbox_rows():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE review_inbox_items (inbox_id TEXT PRIMARY KEY, status TEXT)")
    conn.execute("INSERT INTO review_inbox_items VALUES ('legacy-1', 'pending')")
    first = migrate_local_judgment_contract(conn)
    second = migrate_local_judgment_contract(conn)
    assert first["legacy_review_inbox_changed"] is False
    assert second["tables_added"] == []
    assert conn.execute("SELECT * FROM review_inbox_items").fetchone() == ("legacy-1", "pending")
    assert conn.execute("SELECT COUNT(*) FROM local_judgment_schema_migrations").fetchone()[0] == 1
