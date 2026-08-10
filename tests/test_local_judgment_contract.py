import json
import sqlite3

import pytest

from event_model.local_judgment_migration import migrate_local_judgment_contract
from review_inbox_adapters.local_judgment_contract import (
    ACTION_REGISTRY,
    CANONICAL_FIELDS,
    ContractError,
    build_agent_terminal_decision,
    build_canonical_hold,
    build_hold_ledger_entry,
    build_requeue,
    build_user_decision,
    canonicalize_raw_judgment,
    validate_canonical_decision,
)


AGENT = {"actor_type": "agent", "actor_id": "local-llm", "decision_channel": "llm", "decided_at": "2026-06-01T00:00:00+09:00"}
USER = {"actor_type": "user", "actor_id": "uchida-console", "decision_channel": "console", "decided_at": "2026-06-01T00:01:00+09:00"}
SYSTEM = {"actor_type": "system", "actor_id": "retry-scheduler", "decision_channel": "scheduler", "decided_at": "2026-07-20T00:00:00+09:00"}


def raw(action="hold", *, actor=AGENT, packet_id="packet-1", domain="event", lane="event_update", payload=None):
    return canonicalize_raw_judgment({
        "packet_id": packet_id, "inbox_id": "inbox-1", "domain": domain, "lane": lane,
        "source_id": "official_source", "source_key": "source-1", "source_payload_hash": "b" * 64,
        "requested_action": action, "payload": {} if payload is None else payload,
        "actor_type": "user", "actor_id": "uchida",
    }, trusted_actor=actor)


def candidate(**overrides):
    value = {
        "candidate_id": "august-window", "next_eligible_at": "2026-07-20T00:00:00+09:00",
        "window_start": "2026-07-19T00:00:00+09:00", "window_end": "2026-07-21T00:00:00+09:00",
        "occurrence_ids": ["occ-2026"], "evidence_ids": ["evidence-2025"],
        "retrieved_at": "2026-06-01T00:00:00+09:00", "calculation_version": "announcement-window/v1",
        "input_hash": "a" * 64,
    }
    value.update(overrides)
    return value


def user_hold(*, status="open", inbox_id="inbox-1", domain="event", lane="event_update"):
    decision = build_canonical_hold(raw(packet_id="held"), reason_code="requires_policy_judgment")
    entry = build_hold_ledger_entry(decision, hold_id="hold-user")
    entry.update({"status": status, "inbox_id": inbox_id, "domain": domain, "lane": lane,
                  "adjudication_batch_id": "batch-1"})
    return entry


def retry_hold():
    decision = build_canonical_hold(
        raw(packet_id="retry-hold"), reason_code="awaiting_official_announcement",
        retry_candidates=[candidate()], selected_candidate_id="august-window",
    )
    return build_hold_ledger_entry(decision, hold_id="hold-retry")


def requeue_raw(*, released_at="2026-07-20T00:00:00+09:00"):
    return raw("requeue", actor=SYSTEM, packet_id="requeue-1", payload={
        "hold_id": "hold-retry", "released_at": released_at,
        "next_eligible_at": "2026-07-20T00:00:00+09:00",
    })


def insert_decision(conn, packet):
    conn.execute(
        """
        INSERT INTO canonical_decision_ledger(
          decision_id, schema_version, packet_id, packet_sha256, inbox_id, domain, lane,
          source_id, source_key, source_payload_hash, action, queue_state_before,
          queue_state_after, hold_packet_json, payload_json, actor_type, actor_id,
          decision_channel, decided_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (packet["decision_id"], packet["schema_version"], packet["packet_id"], packet["packet_sha256"],
         packet["inbox_id"], packet["domain"], packet["lane"], packet["source_id"], packet["source_key"],
         packet["source_payload_hash"], packet["action"], packet["queue_state_before"], packet["queue_state_after"],
         json.dumps(packet["hold_packet"]), json.dumps(packet["payload"]), packet["actor_type"], packet["actor_id"],
         packet["decision_channel"], packet["decided_at"], packet["decided_at"]),
    )


def test_n01_eligible_to_user_terminal_is_rejected():
    packet = build_user_decision(raw("accept", actor=USER), open_hold=user_hold())
    packet["queue_state_before"] = "eligible"
    with pytest.raises(ContractError, match="transition"):
        validate_canonical_decision(packet)


def test_n02_deferred_retry_to_user_terminal_is_rejected():
    packet = build_user_decision(raw("reject", actor=USER), open_hold=user_hold())
    packet["queue_state_before"] = "deferred_retry"
    with pytest.raises(ContractError, match="transition"):
        validate_canonical_decision(packet)


@pytest.mark.parametrize("actor,action", [(AGENT, "accept"), (USER, "accept")])
def test_n03_closed_redecision_is_rejected_for_agent_and_user(actor, action):
    packet = build_agent_terminal_decision(raw(action, actor=AGENT)) if actor is AGENT else build_user_decision(raw(action, actor=USER), open_hold=user_hold())
    packet["queue_state_before"] = "closed"
    with pytest.raises(ContractError, match="transition"):
        validate_canonical_decision(packet)


def test_n04_awaiting_user_to_eligible_is_rejected():
    packet = build_requeue(requeue_raw(), open_hold=retry_hold())
    packet["queue_state_before"] = "awaiting_user"
    with pytest.raises(ContractError, match="transition"):
        validate_canonical_decision(packet)


def test_n05_console_decision_without_hold_is_rejected():
    with pytest.raises(ContractError, match="status=open"):
        build_user_decision(raw("accept", actor=USER), open_hold={})


def test_n06_console_decision_with_non_open_hold_is_rejected():
    with pytest.raises(ContractError, match="status=open"):
        build_user_decision(raw("accept", actor=USER), open_hold=user_hold(status="resolved"))


def test_n07_console_decision_with_another_inbox_hold_is_rejected():
    with pytest.raises(ContractError, match="inbox_id"):
        build_user_decision(raw("accept", actor=USER), open_hold=user_hold(inbox_id="another"))


@pytest.mark.parametrize("action", ["accept", "reject", "hold"])
def test_n08_system_cannot_accept_reject_or_hold(action):
    with pytest.raises(ContractError, match="trusted actor"):
        raw(action, actor=SYSTEM)


@pytest.mark.parametrize("actor", [AGENT, USER])
def test_n09_agent_and_user_cannot_requeue(actor):
    with pytest.raises(ContractError, match="trusted actor"):
        raw("requeue", actor=actor, payload={"hold_id": "h", "released_at": "x", "next_eligible_at": "x"})


def test_n10_early_requeue_is_rejected():
    with pytest.raises(ContractError, match="before next_eligible_at"):
        build_requeue(requeue_raw(released_at="2026-07-19T23:59:59+09:00"), open_hold=retry_hold())


def test_n11_unknown_reason_code_is_rejected():
    with pytest.raises(ContractError, match="unknown reason_code"):
        build_canonical_hold(raw(), reason_code="invented")


def test_n12_reason_code_and_hold_mode_mismatch_is_rejected():
    packet = build_canonical_hold(raw(), reason_code="requires_policy_judgment")
    packet["hold_mode"] = "deferred_retry"
    with pytest.raises(ContractError, match="do not match"):
        validate_canonical_decision(packet)


def test_n13_awaiting_user_with_retry_time_is_rejected():
    packet = build_canonical_hold(raw(), reason_code="requires_policy_judgment")
    packet["next_eligible_at"] = candidate()["next_eligible_at"]
    with pytest.raises(ContractError, match="null retry"):
        validate_canonical_decision(packet)


@pytest.mark.parametrize("field", ["next_eligible_at", "hold_packet"])
def test_n14_deferred_retry_missing_required_field_is_rejected(field):
    packet = build_canonical_hold(raw(), reason_code="awaiting_official_announcement", retry_candidates=[candidate()], selected_candidate_id="august-window")
    packet[field] = None
    with pytest.raises(ContractError, match="requires"):
        validate_canonical_decision(packet)


def test_n15_retry_time_outside_candidate_window_is_rejected():
    with pytest.raises(ContractError, match="outside"):
        build_canonical_hold(raw(), reason_code="awaiting_official_announcement", retry_candidates=[candidate(next_eligible_at="2026-07-22T00:00:00+09:00")], selected_candidate_id="august-window")


def test_n16_unoffered_candidate_is_rejected():
    with pytest.raises(ContractError, match="not machine-provided"):
        build_canonical_hold(raw(), reason_code="awaiting_official_announcement", retry_candidates=[candidate()], selected_candidate_id="other")


@pytest.mark.parametrize("field", ["occurrence_ids", "evidence_ids"])
def test_n17_retry_packet_requires_occurrences_and_evidence(field):
    with pytest.raises(ContractError, match="occurrence and evidence"):
        build_canonical_hold(raw(), reason_code="awaiting_official_announcement", retry_candidates=[candidate(**{field: []})], selected_candidate_id="august-window")


def test_n18_actor_self_claim_is_ignored():
    packet = raw()
    assert (packet["actor_type"], packet["actor_id"]) == ("agent", "local-llm")


@pytest.mark.parametrize("decided_at", [None, "2026-06-01T00:00:00"])
def test_n19_decided_at_is_required_and_timezone_aware(decided_at):
    actor = AGENT | {"decided_at": decided_at}
    with pytest.raises(ContractError, match="decided_at"):
        raw(actor=actor)


@pytest.mark.parametrize("field", ["prior_agent_attempt_id", "open_hold_id"])
def test_n20_user_terminal_requires_prior_attempt_and_open_hold(field):
    packet = build_user_decision(raw("accept", actor=USER), open_hold=user_hold())
    packet[field] = None
    with pytest.raises(ContractError, match=field):
        validate_canonical_decision(packet)


def test_n21_same_packet_agent_hold_and_user_final_have_distinct_insertable_ids():
    hold = build_canonical_hold(raw(packet_id="shared"), reason_code="requires_policy_judgment")
    open_hold = build_hold_ledger_entry(hold, hold_id="hold-shared") | {"adjudication_batch_id": "batch"}
    final = build_user_decision(raw("accept", actor=USER, packet_id="shared"), open_hold=open_hold)
    assert hold["decision_id"] != final["decision_id"]
    conn = sqlite3.connect(":memory:")
    migrate_local_judgment_contract(conn)
    insert_decision(conn, hold)
    insert_decision(conn, final)
    assert conn.execute("SELECT COUNT(*) FROM canonical_decision_ledger").fetchone()[0] == 2


def test_n22_identical_decision_has_identical_id():
    assert build_agent_terminal_decision(raw("accept"))["decision_id"] == build_agent_terminal_decision(raw("accept"))["decision_id"]


def test_n23_unregistered_domain_lane_action_is_rejected():
    with pytest.raises(ContractError, match="unregistered"):
        raw("accept", domain="song", lane="event_update")


def test_n24_payload_fields_beyond_registry_are_rejected():
    with pytest.raises(ContractError, match="payload fields"):
        raw(payload={"implicit_target_selection": "first"})


def test_n25_non_dict_payload_is_rejected_not_repaired():
    with pytest.raises(ContractError, match="payload must be an object"):
        raw(payload="not-an-object")


def test_n26_every_registry_entry_is_reachable_from_each_allowed_actor():
    for (domain, lane, action), entry in ACTION_REGISTRY.items():
        for actor_type in entry["allowed_actor_types"]:
            actor = {"agent": AGENT, "user": USER, "system": SYSTEM}[actor_type]
            if action in {"accept", "reject"} and actor_type == "agent":
                packet = build_agent_terminal_decision(raw(action, actor=actor, domain=domain, lane=lane))
            elif action in {"accept", "reject"}:
                hold = user_hold(domain=domain, lane=lane)
                packet = build_user_decision(raw(action, actor=actor, domain=domain, lane=lane), open_hold=hold)
            elif action == "hold":
                packet = build_canonical_hold(raw(action, actor=actor, domain=domain, lane=lane), reason_code="requires_policy_judgment")
            else:
                hold = retry_hold() | {"domain": domain, "lane": lane}
                packet = build_requeue(raw(action, actor=actor, domain=domain, lane=lane, payload={"hold_id": "hold-retry", "released_at": "2026-07-20T00:00:00+09:00", "next_eligible_at": "2026-07-20T00:00:00+09:00"}), open_hold=hold)
            assert validate_canonical_decision(packet)["action"] == action


def test_n27_migration_is_idempotent():
    conn = sqlite3.connect(":memory:")
    first = migrate_local_judgment_contract(conn)
    second = migrate_local_judgment_contract(conn)
    assert first["tables_added"]
    assert second["tables_added"] == []
    assert conn.execute("SELECT COUNT(*) FROM local_judgment_schema_migrations").fetchone()[0] == 1


def test_n28_migration_preserves_legacy_review_inbox_rows_and_columns():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE review_inbox_items (inbox_id TEXT PRIMARY KEY, status TEXT)")
    conn.execute("INSERT INTO review_inbox_items VALUES ('legacy-1', 'pending')")
    before_columns = conn.execute("PRAGMA table_info(review_inbox_items)").fetchall()
    before_rows = conn.execute("SELECT * FROM review_inbox_items").fetchall()
    migrate_local_judgment_contract(conn)
    assert conn.execute("PRAGMA table_info(review_inbox_items)").fetchall() == before_columns
    assert conn.execute("SELECT * FROM review_inbox_items").fetchall() == before_rows
    hold_columns = {row[1] for row in conn.execute("PRAGMA table_info(review_hold_ledger)")}
    assert len(hold_columns) == 22
    assert set(build_hold_ledger_entry(build_canonical_hold(raw(), reason_code="requires_policy_judgment"), hold_id="h")) == hold_columns
    assert CANONICAL_FIELDS <= set(build_agent_terminal_decision(raw("accept")))


def test_n29_validator_alone_rejects_early_requeue_packet():
    packet = build_requeue(requeue_raw(), open_hold=retry_hold())
    packet["payload"]["released_at"] = "2026-01-01T00:00:00+09:00"
    with pytest.raises(ContractError, match="before payload.next_eligible_at"):
        validate_canonical_decision(packet)


def test_n30_awaiting_user_hold_freezes_all_presented_candidates():
    decision = build_canonical_hold(raw(), reason_code="ambiguous_event_series")
    entry = build_hold_ledger_entry(
        decision, hold_id="hold-candidates", candidate_ids=["series-b", "series-a", "series-c"]
    )
    assert entry["candidate_ids"] == ["series-a", "series-b", "series-c"]
    assert entry["candidate_set_sha256"] is not None
