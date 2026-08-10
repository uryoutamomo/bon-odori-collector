import sqlite3

import pytest

from event_model.local_judgment_migration import migrate_local_judgment_contract
from review_inbox_adapters.local_judgment_contract import (
    ContractError, build_agent_terminal_decision, build_canonical_hold, build_hold_ledger_entry, build_retry_eligibility_transition, build_user_decision, canonicalize_raw_judgment,
    validate_canonical_decision,
)


AGENT = {"actor_type": "agent", "actor_id": "local-llm", "decision_channel": "llm", "decided_at": "2026-06-01T00:00:00+09:00"}
USER = {"actor_type": "user", "actor_id": "uchida-console-session", "decision_channel": "console", "decided_at": "2026-06-01T00:01:00+09:00"}
SYSTEM = {"actor_type": "system", "actor_id": "retry-scheduler", "decision_channel": "scheduler", "decided_at": "2026-07-20T00:00:00+09:00"}


def raw(packet_id="p1", *, actor=AGENT, requested_action="hold"):
    return canonicalize_raw_judgment({
        "packet_id": packet_id, "inbox_id": "inbox-1", "source_id": "official_source", "domain": "event",
        "source_key": "source-1", "requested_action": requested_action, "actor_id": "uchida",
        "source_payload_hash": "b" * 64, "payload": {"actor_type": "user"},
    }, trusted_actor=actor)


def candidate():
    return {"candidate_id": "august-window", "eligible_at": "2026-07-20T00:00:00+09:00",
            "window_start": "2026-07-19T00:00:00+09:00", "window_end": "2026-07-21T00:00:00+09:00",
            "occurrence_ids": ["occ-2026"], "evidence_ids": ["evidence-2025"],
            "retrieved_at": "2026-06-01T00:00:00+09:00", "calculation_version": "announcement-window/v1",
            "input_hash": "a" * 64}


def awaiting_hold():
    return {"hold_id": "hold-1", "inbox_id": "inbox-1", "status": "open", "source_id": "official_source",
            "source_key": "source-1", "domain": "event", "source_payload_hash": "b" * 64, "packet_sha256": "c" * 64,
            "decision_id": "decision:p1:agent:hold", "hold_mode": "awaiting_user", "reason_code": "requires_policy_judgment",
            "adjudication_batch_id": "batch:event-policy:v1", "hold_packet": None}


def test_actor_identity_is_from_trusted_context_not_input_json():
    packet = raw()
    assert packet["actor_id"] == "local-llm"
    assert packet["actor_type"] == "agent"


def test_raw_packet_rejects_actions_outside_the_active_finite_registry():
    with pytest.raises(ContractError, match="active finite registry"):
        canonicalize_raw_judgment({
            "packet_id": "bad", "inbox_id": "inbox-1", "source_id": "source", "domain": "event",
            "source_key": "key", "source_payload_hash": "b" * 64, "payload": {}, "requested_action": "invent_new_action",
        }, trusted_actor=AGENT)


def test_raw_packet_rejects_non_object_payload_instead_of_repairing_it():
    with pytest.raises(ContractError, match="payload must be an object"):
        canonicalize_raw_judgment({
            "packet_id": "bad-payload", "inbox_id": "inbox-1", "source_id": "source", "domain": "event",
            "source_key": "key", "source_payload_hash": "b" * 64, "payload": "not-json-object", "requested_action": "hold",
        }, trusted_actor=AGENT)


def test_deferred_retry_freezes_machine_candidate_and_rejects_outside_window():
    packet = build_canonical_hold(raw(), reason_code="awaiting_official_announcement",
                                  retry_candidates=[candidate()], selected_candidate_id="august-window")
    assert validate_canonical_decision(packet)["next_eligible_at"] == candidate()["eligible_at"]
    bad = candidate(); bad["eligible_at"] = "2026-07-22T00:00:00+09:00"
    with pytest.raises(ContractError, match="outside"):
        build_canonical_hold(raw(), reason_code="awaiting_official_announcement", retry_candidates=[bad], selected_candidate_id="august-window")


def test_agent_can_make_terminal_decisions_without_creating_a_human_queue_item():
    packet = build_agent_terminal_decision(raw("agent-final", requested_action="accept"), action="accept")
    assert validate_canonical_decision(packet)["queue_state_after"] == "closed"


@pytest.mark.parametrize("reason", ["unknown", "awaiting_official_announcement"])
def test_unknown_reason_or_missing_machine_candidate_is_rejected(reason):
    with pytest.raises(ContractError):
        build_canonical_hold(raw(), reason_code=reason)


def test_awaiting_user_has_no_retry_date_and_only_open_hold_allows_console_decision():
    hold = build_canonical_hold(raw(), reason_code="requires_policy_judgment")
    assert hold["queue_state_after"] == "awaiting_user"
    assert hold["next_eligible_at"] is None
    decision = build_user_decision(raw("p2", actor=USER, requested_action="accept"), action="accept", open_hold=awaiting_hold())
    assert validate_canonical_decision(decision)["queue_state_after"] == "closed"
    with pytest.raises(ContractError, match="open awaiting_user"):
        build_user_decision(raw("p3", actor=USER, requested_action="accept"), action="accept", open_hold={})


@pytest.mark.parametrize("before", ["eligible", "deferred_retry"])
def test_forbidden_direct_user_transitions_are_rejected(before):
    packet = build_user_decision(raw("p4", actor=USER, requested_action="reject"), action="reject", open_hold=awaiting_hold())
    packet["queue_state_before"] = before
    with pytest.raises(ContractError, match="awaiting_user"):
        validate_canonical_decision(packet)


def test_user_closed_item_has_no_llm_redecision_route():
    packet = build_canonical_hold(raw("p5"), reason_code="requires_policy_judgment")
    packet["queue_state_before"] = "closed"
    with pytest.raises(ContractError, match="eligible item"):
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


def test_deferred_retry_returns_to_eligible_only_through_system_transition():
    held = build_canonical_hold(raw("retry"), reason_code="awaiting_official_announcement",
                                retry_candidates=[candidate()], selected_candidate_id="august-window")
    hold = {"hold_id": "hold-retry", "status": "open", **held}
    transition = build_retry_eligibility_transition(hold, trusted_actor=SYSTEM)
    assert validate_canonical_decision(transition)["queue_state_after"] == "eligible"


def test_same_packet_id_has_distinct_agent_hold_and_user_final_decision_ids():
    hold = build_canonical_hold(raw("shared"), reason_code="requires_policy_judgment")
    open_hold = awaiting_hold() | {"decision_id": hold["decision_id"], "packet_sha256": hold["packet_sha256"]}
    final = build_user_decision(raw("shared", actor=USER, requested_action="accept"), action="accept", open_hold=open_hold)
    assert hold["decision_id"] != final["decision_id"]
    conn = sqlite3.connect(":memory:")
    migrate_local_judgment_contract(conn)
    for packet in (hold, final):
        conn.execute(
            """
            INSERT INTO canonical_decision_ledger(
              decision_id, inbox_id, source_id, domain, source_key, source_payload_hash,
              packet_sha256, decided_at, action, actor_type, actor_id, decision_channel,
              queue_state_before, queue_state_after, packet_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?)
            """,
            tuple(packet[field] for field in (
                "decision_id", "inbox_id", "source_id", "domain", "source_key",
                "source_payload_hash", "packet_sha256", "decided_at", "action",
                "actor_type", "actor_id", "decision_channel", "queue_state_before",
                "queue_state_after",
            )) + (packet["decided_at"],),
        )
    assert conn.execute("SELECT COUNT(*) FROM canonical_decision_ledger").fetchone()[0] == 2


def test_hold_ledger_entry_freezes_grouping_safety_fields():
    hold = build_canonical_hold(raw("group"), reason_code="requires_policy_judgment")
    entry = build_hold_ledger_entry(hold, hold_id="hold-group", expires_at="2026-08-01T00:00:00+09:00")
    assert entry["allowed_actions"] == ["accept", "reject"]
    assert entry["grouping_fingerprint"]
    assert entry["adjudication_batch_id"].endswith(entry["grouping_fingerprint"])


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
    decision_columns = {row[1] for row in conn.execute("PRAGMA table_info(canonical_decision_ledger)")}
    hold_columns = {row[1] for row in conn.execute("PRAGMA table_info(review_hold_ledger)")}
    assert {"domain", "decided_at", "source_payload_hash", "packet_sha256", "prior_agent_attempt_id", "supersedes_hold_id", "adjudication_batch_id"} <= decision_columns
    assert {"domain", "lane", "allowed_actions_json", "required_resolution_type", "candidate_ids_json", "candidate_set_sha256", "expires_at", "prior_agent_attempt_id", "resolved_by_decision_id", "grouping_fingerprint", "source_id", "source_key", "source_payload_hash", "packet_sha256", "adjudication_batch_id"} <= hold_columns
