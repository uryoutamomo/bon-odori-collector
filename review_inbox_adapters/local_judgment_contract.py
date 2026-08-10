"""Pure contracts for local judgment packets; this module never writes a domain table.

The legacy review inbox remains the runtime projection in J0.  These contracts
make the future decision/hold ledger explicit without changing that runtime.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Mapping


SCHEMA_VERSION = 1
QUEUE_STATES = {"eligible", "deferred_retry", "awaiting_user", "closed"}
ACTOR_TYPES = {"agent", "user", "system"}
DECISION_CHANNELS = {"llm", "console", "scheduler"}
DOMAINS = {"event", "song", "term"}
FINAL_ACTIONS = {"accept", "reject"}
HOLD_ACTION = "hold"

# Persisted values are deliberately English.  A console can use the Japanese
# labels without making its presentation strings part of the durable protocol.
ACTIVE_ACTION_REGISTRY = {
    "accept": {"label_ja": "採用", "terminal": True, "domains": DOMAINS, "lanes": {"agent", "user"}},
    "reject": {"label_ja": "却下", "terminal": True, "domains": DOMAINS, "lanes": {"agent", "user"}},
    "hold": {"label_ja": "保留", "terminal": False, "domains": DOMAINS, "lanes": {"agent"}},
    "retry_eligible": {"label_ja": "再判定可能", "terminal": False, "domains": DOMAINS, "lanes": {"system"}},
}
REASON_CODE_HOLD_MODE = {
    "awaiting_official_announcement": "deferred_retry",
    "insufficient_announcement_history": "awaiting_user",
    "requires_policy_judgment": "awaiting_user",
    "ambiguous_semantic_meaning": "awaiting_user",
}


class ContractError(ValueError):
    """A packet is invalid before any writer is allowed to see it."""


def _text(value: Any, field: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ContractError(f"{field} is required")
    return value


def _iso(value: Any, field: str) -> str:
    text = _text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ContractError(f"{field} must include a timezone")
    return text


def _trusted_actor(actor: Mapping[str, Any]) -> dict[str, str]:
    actor_type = _text(actor.get("actor_type"), "trusted actor_type")
    channel = _text(actor.get("decision_channel"), "trusted decision_channel")
    if actor_type not in ACTOR_TYPES or channel not in DECISION_CHANNELS:
        raise ContractError("trusted actor has unsupported type or channel")
    if (actor_type, channel) not in {("agent", "llm"), ("user", "console"), ("system", "scheduler")}:
        raise ContractError("trusted actor_type and decision_channel do not match")
    return {"actor_type": actor_type, "actor_id": _text(actor.get("actor_id"), "trusted actor_id"), "decision_channel": channel, "decided_at": _iso(actor.get("decided_at"), "trusted decided_at")}


def canonicalize_raw_judgment(raw: Mapping[str, Any], *, trusted_actor: Mapping[str, Any]) -> dict[str, Any]:
    """Build the UI-independent raw packet, ignoring actor self-claims in JSON."""
    actor = _trusted_actor(trusted_actor)
    requested_action = _text(raw.get("requested_action"), "requested_action")
    domain = _text(raw.get("domain"), "domain")
    if domain not in DOMAINS:
        raise ContractError("unsupported domain")
    if requested_action not in ACTIVE_ACTION_REGISTRY:
        raise ContractError("requested_action is not in the active finite registry")
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        raise ContractError("payload must be an object")
    source_payload_hash = _text(raw.get("source_payload_hash"), "source_payload_hash")
    if len(source_payload_hash) != 64:
        raise ContractError("source_payload_hash must be SHA-256")
    packet = {
        "schema_version": SCHEMA_VERSION,
        "packet_type": "raw_judgment",
        "packet_id": _text(raw.get("packet_id"), "packet_id"),
        "inbox_id": _text(raw.get("inbox_id"), "inbox_id"),
        "source_id": _text(raw.get("source_id"), "source_id"),
        "source_key": _text(raw.get("source_key"), "source_key"),
        "domain": domain,
        "source_payload_hash": source_payload_hash,
        "requested_action": requested_action,
        "payload": payload,
        **actor,
    }
    packet["packet_sha256"] = hashlib.sha256(json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return packet


def _base(raw_packet: Mapping[str, Any], *, action: str, before: str, after: str) -> dict[str, Any]:
    actor_type = raw_packet["actor_type"]
    return {
        "schema_version": SCHEMA_VERSION, "packet_type": "canonical_decision",
        "decision_id": f"decision:{raw_packet['packet_id']}:{actor_type}",
        "inbox_id": raw_packet["inbox_id"], "source_id": raw_packet["source_id"],
        "source_key": raw_packet["source_key"], "domain": raw_packet["domain"],
        "source_payload_hash": raw_packet["source_payload_hash"], "packet_sha256": raw_packet["packet_sha256"],
        "decided_at": raw_packet["decided_at"], "queue_state_before": before, "queue_state_after": after,
        "action": action, "actor_type": actor_type, "actor_id": raw_packet["actor_id"],
        "decision_channel": raw_packet["decision_channel"], "prior_agent_attempt_id": None,
        "supersedes_hold_id": None, "adjudication_batch_id": None,
    }


def _retry_hold_packet(retry_candidates: list[Mapping[str, Any]], selected_candidate_id: str) -> tuple[str, dict[str, Any]]:
    selected = next((row for row in retry_candidates if str(row.get("candidate_id") or "") == selected_candidate_id), None)
    if selected is None:
        raise ContractError("selected retry candidate is not machine-provided")
    eligible = _iso(selected.get("eligible_at"), "candidate eligible_at")
    start = _iso(selected.get("window_start"), "candidate window_start")
    end = _iso(selected.get("window_end"), "candidate window_end")
    if not (datetime.fromisoformat(start.replace("Z", "+00:00")) <= datetime.fromisoformat(eligible.replace("Z", "+00:00")) <= datetime.fromisoformat(end.replace("Z", "+00:00"))):
        raise ContractError("candidate eligible_at is outside its machine-calculated window")
    frozen = {
        "candidate_id": selected_candidate_id,
        "next_eligible_at": eligible,
        "window_start": start,
        "window_end": end,
        "occurrence_ids": list(selected.get("occurrence_ids") or []),
        "evidence_ids": list(selected.get("evidence_ids") or []),
        "retrieved_at": _iso(selected.get("retrieved_at"), "candidate retrieved_at"),
        "calculation_version": _text(selected.get("calculation_version"), "candidate calculation_version"),
        "input_hash": _text(selected.get("input_hash"), "candidate input_hash"),
    }
    if not frozen["occurrence_ids"] or not frozen["evidence_ids"]:
        raise ContractError("retry candidate must freeze occurrence and evidence IDs")
    return eligible, frozen


def build_canonical_hold(
    raw_packet: Mapping[str, Any], *, reason_code: str,
    retry_candidates: list[Mapping[str, Any]] | None = None,
    selected_candidate_id: str | None = None,
) -> dict[str, Any]:
    """Convert an agent raw judgment into the only legal open-hold transition."""
    reason_code = _text(reason_code, "reason_code")
    hold_mode = REASON_CODE_HOLD_MODE.get(reason_code)
    if hold_mode is None:
        raise ContractError(f"unknown reason_code: {reason_code}")
    if raw_packet.get("actor_type") != "agent" or raw_packet.get("decision_channel") != "llm":
        raise ContractError("only the trusted agent lane can create an agent hold")
    if raw_packet.get("requested_action") != HOLD_ACTION:
        raise ContractError("canonical hold requires requested_action=hold")
    hold_packet: dict[str, Any] | None = None
    next_eligible_at: str | None = None
    if hold_mode == "deferred_retry":
        if not selected_candidate_id:
            raise ContractError("deferred_retry requires a selected machine retry candidate")
        next_eligible_at, hold_packet = _retry_hold_packet(retry_candidates or [], selected_candidate_id)
    packet = _base(raw_packet, action=HOLD_ACTION, before="eligible", after=hold_mode)
    packet.update({
        "reason_code": reason_code,
        "hold_mode": hold_mode,
        "next_eligible_at": next_eligible_at,
        "hold_packet": hold_packet,
    })
    return packet


def build_agent_terminal_decision(raw_packet: Mapping[str, Any], *, action: str) -> dict[str, Any]:
    """An agent may close an eligible item it can decide without human adjudication."""
    if raw_packet.get("actor_type") != "agent" or raw_packet.get("decision_channel") != "llm":
        raise ContractError("only the trusted agent lane can create an agent terminal decision")
    if action not in FINAL_ACTIONS:
        raise ContractError("agent terminal action must be finite accept or reject")
    if raw_packet.get("requested_action") != action:
        raise ContractError("agent terminal action differs from the raw judgment")
    packet = _base(raw_packet, action=action, before="eligible", after="closed")
    packet.update({"reason_code": None, "hold_mode": None, "next_eligible_at": None, "hold_packet": None})
    return packet


def build_retry_eligibility_transition(hold: Mapping[str, Any], *, trusted_actor: Mapping[str, Any]) -> dict[str, Any]:
    """J1 may schedule this later; J0 owns the validation contract for the return edge."""
    actor = _trusted_actor(trusted_actor)
    if hold.get("status") != "open" or hold.get("hold_mode") != "deferred_retry":
        raise ContractError("retry eligibility requires an open deferred_retry hold")
    next_at = _iso(hold.get("next_eligible_at"), "hold next_eligible_at")
    return {
        "schema_version": SCHEMA_VERSION, "packet_type": "canonical_decision",
        "decision_id": f"decision:{_text(hold.get('hold_id'), 'hold_id')}:system:retry_eligible",
        "inbox_id": _text(hold.get("inbox_id"), "hold inbox_id"), "source_id": _text(hold.get("source_id"), "hold source_id"),
        "source_key": _text(hold.get("source_key"), "hold source_key"), "domain": _text(hold.get("domain"), "hold domain"),
        "source_payload_hash": _text(hold.get("source_payload_hash"), "hold source_payload_hash"), "packet_sha256": _text(hold.get("packet_sha256"), "hold packet_sha256"),
        "decided_at": actor["decided_at"], "queue_state_before": "deferred_retry", "queue_state_after": "eligible",
        "action": "retry_eligible", "reason_code": hold.get("reason_code"), "hold_mode": "deferred_retry",
        "next_eligible_at": next_at, "hold_packet": hold.get("hold_packet"), **actor,
        "prior_agent_attempt_id": _text(hold.get("decision_id"), "hold decision_id"), "supersedes_hold_id": _text(hold.get("hold_id"), "hold_id"), "adjudication_batch_id": None,
    }


def build_user_decision(raw_packet: Mapping[str, Any], *, action: str, open_hold: Mapping[str, Any]) -> dict[str, Any]:
    """A console decision is possible only from an existing awaiting-user hold."""
    if raw_packet.get("actor_type") != "user" or raw_packet.get("decision_channel") != "console":
        raise ContractError("only the trusted console lane can create a user decision")
    if action not in FINAL_ACTIONS:
        raise ContractError("user decision action must be finite accept or reject")
    if raw_packet.get("requested_action") != action:
        raise ContractError("user action differs from the raw judgment")
    if open_hold.get("status") != "open" or open_hold.get("hold_mode") != "awaiting_user":
        raise ContractError("console decision requires an open awaiting_user hold")
    if open_hold.get("inbox_id") != raw_packet.get("inbox_id"):
        raise ContractError("open hold belongs to another inbox item")
    for field in ("source_id", "source_key", "domain", "source_payload_hash"):
        if open_hold.get(field) != raw_packet.get(field):
            raise ContractError(f"open hold {field} differs from the decision target")
    packet = _base(raw_packet, action=action, before="awaiting_user", after="closed")
    packet.update({
        "reason_code": open_hold.get("reason_code"), "hold_mode": "awaiting_user",
        "next_eligible_at": None, "hold_packet": None,
        "open_hold_id": _text(open_hold.get("hold_id"), "open hold_id"),
        "prior_agent_attempt_id": _text(open_hold.get("decision_id"), "open hold decision_id"),
        "supersedes_hold_id": _text(open_hold.get("hold_id"), "open hold_id"),
        "adjudication_batch_id": _text(open_hold.get("adjudication_batch_id"), "open hold adjudication_batch_id"),
    })
    return packet


def build_hold_ledger_entry(canonical_hold: Mapping[str, Any], *, hold_id: str, expires_at: str) -> dict[str, Any]:
    """Create the frozen open-hold record and its safe bulk-grouping fingerprint."""
    validated = validate_canonical_decision(canonical_hold)
    if validated["actor_type"] != "agent" or validated["action"] != HOLD_ACTION:
        raise ContractError("hold ledger entry requires an agent hold decision")
    mode = validated["hold_mode"]
    lane = "scheduled_retry" if mode == "deferred_retry" else "user_adjudication"
    allowed_actions = ["retry_eligible"] if mode == "deferred_retry" else sorted(FINAL_ACTIONS)
    hold_packet = validated.get("hold_packet") or {}
    candidate_ids = [hold_packet["candidate_id"]] if hold_packet.get("candidate_id") else []
    candidate_set_sha256 = hashlib.sha256(json.dumps(candidate_ids, separators=(",", ":")).encode()).hexdigest()
    grouping_basis = {
        "domain": validated["domain"], "lane": lane, "reason_code": validated["reason_code"],
        "hold_mode": mode, "allowed_actions": allowed_actions,
        "required_resolution_type": lane, "candidate_set_sha256": candidate_set_sha256,
        "source_id": validated["source_id"],
    }
    grouping_fingerprint = hashlib.sha256(json.dumps(grouping_basis, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    hold_id = _text(hold_id, "hold_id")
    return {
        "hold_id": hold_id, "decision_id": validated["decision_id"], "inbox_id": validated["inbox_id"],
        "source_id": validated["source_id"], "source_key": validated["source_key"],
        "source_payload_hash": validated["source_payload_hash"], "packet_sha256": validated["packet_sha256"],
        "domain": validated["domain"], "lane": lane, "reason_code": validated["reason_code"],
        "hold_mode": mode, "status": "open", "allowed_actions": allowed_actions,
        "required_resolution_type": lane, "candidate_ids": candidate_ids,
        "candidate_set_sha256": candidate_set_sha256, "next_eligible_at": validated["next_eligible_at"],
        "expires_at": _iso(expires_at, "expires_at"), "prior_agent_attempt_id": validated["decision_id"],
        "resolved_by_decision_id": None, "grouping_fingerprint": grouping_fingerprint,
        "adjudication_batch_id": f"batch:{grouping_fingerprint}", "hold_packet": validated.get("hold_packet"),
        "opened_at": validated["decided_at"], "closed_at": None,
    }


def validate_canonical_decision(packet: Mapping[str, Any]) -> dict[str, Any]:
    """Validate only; intentionally has no database or domain-write dependency."""
    if packet.get("schema_version") != SCHEMA_VERSION or packet.get("packet_type") != "canonical_decision":
        raise ContractError("unsupported canonical decision schema")
    for field in ("decision_id", "inbox_id", "source_id", "source_key", "domain", "actor_id", "source_payload_hash", "packet_sha256"):
        _text(packet.get(field), field)
    _iso(packet.get("decided_at"), "decided_at")
    if packet.get("domain") not in DOMAINS:
        raise ContractError("unsupported domain")
    before, after = packet.get("queue_state_before"), packet.get("queue_state_after")
    if before not in QUEUE_STATES or after not in QUEUE_STATES:
        raise ContractError("unsupported queue state")
    action = packet.get("action")
    if action not in ACTIVE_ACTION_REGISTRY:
        raise ContractError("action is not in the active finite registry")
    actor_type, channel = packet.get("actor_type"), packet.get("decision_channel")
    if (actor_type, channel) not in {("agent", "llm"), ("user", "console"), ("system", "scheduler")}:
        raise ContractError("actor lineage is invalid")
    definition = ACTIVE_ACTION_REGISTRY[action]
    if packet["domain"] not in definition["domains"] or actor_type not in definition["lanes"]:
        raise ContractError("action is not allowed for this domain and actor lane")
    if actor_type == "agent":
        if before != "eligible":
            raise ContractError("agent may only decide an eligible item")
        if action == HOLD_ACTION:
            if after not in {"deferred_retry", "awaiting_user"}:
                raise ContractError("agent hold must enter a hold queue state")
            reason = packet.get("reason_code")
            if REASON_CODE_HOLD_MODE.get(reason) != after or packet.get("hold_mode") != after:
                raise ContractError("reason_code and hold_mode do not match")
        elif action not in FINAL_ACTIONS or after != "closed":
            raise ContractError("agent terminal decision must close the eligible item")
    else:
        if actor_type == "user" and (action not in FINAL_ACTIONS or before != "awaiting_user" or after != "closed"):
            raise ContractError("user decision requires an awaiting_user hold and closes it")
        if actor_type == "user":
            _text(packet.get("open_hold_id"), "open_hold_id")
            _text(packet.get("prior_agent_attempt_id"), "prior_agent_attempt_id")
            _text(packet.get("supersedes_hold_id"), "supersedes_hold_id")
            _text(packet.get("adjudication_batch_id"), "adjudication_batch_id")
        if actor_type == "system" and not (action == "retry_eligible" and before == "deferred_retry" and after == "eligible"):
            raise ContractError("system may only return deferred_retry to eligible")
    next_at, hold_packet = packet.get("next_eligible_at"), packet.get("hold_packet")
    if after == "deferred_retry":
        if not next_at or not isinstance(hold_packet, dict) or hold_packet.get("next_eligible_at") != next_at:
            raise ContractError("deferred_retry requires a frozen machine retry packet")
    elif next_at is not None and not (actor_type == "system" and before == "deferred_retry" and after == "eligible"):
        raise ContractError("only deferred_retry may have next_eligible_at")
    if after == "awaiting_user" and next_at is not None:
        raise ContractError("awaiting_user requires next_eligible_at = null")
    return dict(packet)
