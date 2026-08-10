"""Pure contracts for local judgment packets; this module never writes a domain table.

The legacy review inbox remains the runtime projection in J0.  These contracts
make the future decision/hold ledger explicit without changing that runtime.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping


SCHEMA_VERSION = 1
QUEUE_STATES = {"eligible", "deferred_retry", "awaiting_user", "closed"}
ACTOR_TYPES = {"agent", "user"}
DECISION_CHANNELS = {"llm", "console"}
FINAL_ACTIONS = {"accept", "reject"}
HOLD_ACTION = "hold"

# Persisted values are deliberately English.  A console can use the Japanese
# labels without making its presentation strings part of the durable protocol.
ACTIVE_ACTION_REGISTRY = {
    "accept": {"label_ja": "採用", "terminal": True},
    "reject": {"label_ja": "却下", "terminal": True},
    "hold": {"label_ja": "保留", "terminal": False},
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
    if (actor_type, channel) not in {("agent", "llm"), ("user", "console")}:
        raise ContractError("trusted actor_type and decision_channel do not match")
    return {"actor_type": actor_type, "actor_id": _text(actor.get("actor_id"), "trusted actor_id"), "decision_channel": channel}


def canonicalize_raw_judgment(raw: Mapping[str, Any], *, trusted_actor: Mapping[str, Any]) -> dict[str, Any]:
    """Build the UI-independent raw packet, ignoring actor self-claims in JSON."""
    actor = _trusted_actor(trusted_actor)
    requested_action = _text(raw.get("requested_action"), "requested_action")
    if requested_action not in ACTIVE_ACTION_REGISTRY:
        raise ContractError("requested_action is not in the active finite registry")
    return {
        "schema_version": SCHEMA_VERSION,
        "packet_type": "raw_judgment",
        "packet_id": _text(raw.get("packet_id"), "packet_id"),
        "inbox_id": _text(raw.get("inbox_id"), "inbox_id"),
        "source_id": _text(raw.get("source_id"), "source_id"),
        "source_key": _text(raw.get("source_key"), "source_key"),
        "requested_action": requested_action,
        "payload": raw.get("payload") if isinstance(raw.get("payload"), dict) else {},
        **actor,
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
    hold_packet: dict[str, Any] | None = None
    next_eligible_at: str | None = None
    if hold_mode == "deferred_retry":
        if not selected_candidate_id:
            raise ContractError("deferred_retry requires a selected machine retry candidate")
        next_eligible_at, hold_packet = _retry_hold_packet(retry_candidates or [], selected_candidate_id)
    return {
        "schema_version": SCHEMA_VERSION,
        "packet_type": "canonical_decision",
        "decision_id": f"decision:{raw_packet['packet_id']}",
        "inbox_id": raw_packet["inbox_id"],
        "source_id": raw_packet["source_id"],
        "source_key": raw_packet["source_key"],
        "queue_state_before": "eligible",
        "queue_state_after": hold_mode,
        "action": HOLD_ACTION,
        "reason_code": reason_code,
        "hold_mode": hold_mode,
        "next_eligible_at": next_eligible_at,
        "hold_packet": hold_packet,
        "actor_type": raw_packet["actor_type"],
        "actor_id": raw_packet["actor_id"],
        "decision_channel": raw_packet["decision_channel"],
    }


def build_user_decision(raw_packet: Mapping[str, Any], *, action: str, open_hold: Mapping[str, Any]) -> dict[str, Any]:
    """A console decision is possible only from an existing awaiting-user hold."""
    if raw_packet.get("actor_type") != "user" or raw_packet.get("decision_channel") != "console":
        raise ContractError("only the trusted console lane can create a user decision")
    if action not in FINAL_ACTIONS:
        raise ContractError("user decision action must be finite accept or reject")
    if open_hold.get("status") != "open" or open_hold.get("hold_mode") != "awaiting_user":
        raise ContractError("console decision requires an open awaiting_user hold")
    if open_hold.get("inbox_id") != raw_packet.get("inbox_id"):
        raise ContractError("open hold belongs to another inbox item")
    return {
        "schema_version": SCHEMA_VERSION, "packet_type": "canonical_decision",
        "decision_id": f"decision:{raw_packet['packet_id']}", "inbox_id": raw_packet["inbox_id"],
        "source_id": raw_packet["source_id"], "source_key": raw_packet["source_key"],
        "queue_state_before": "awaiting_user", "queue_state_after": "closed", "action": action,
        "reason_code": open_hold.get("reason_code"), "hold_mode": "awaiting_user",
        "next_eligible_at": None, "hold_packet": None,
        "actor_type": raw_packet["actor_type"], "actor_id": raw_packet["actor_id"],
        "decision_channel": raw_packet["decision_channel"], "open_hold_id": _text(open_hold.get("hold_id"), "open hold_id"),
    }


def validate_canonical_decision(packet: Mapping[str, Any]) -> dict[str, Any]:
    """Validate only; intentionally has no database or domain-write dependency."""
    if packet.get("schema_version") != SCHEMA_VERSION or packet.get("packet_type") != "canonical_decision":
        raise ContractError("unsupported canonical decision schema")
    for field in ("decision_id", "inbox_id", "source_id", "source_key", "actor_id"):
        _text(packet.get(field), field)
    before, after = packet.get("queue_state_before"), packet.get("queue_state_after")
    if before not in QUEUE_STATES or after not in QUEUE_STATES:
        raise ContractError("unsupported queue state")
    action = packet.get("action")
    if action not in ACTIVE_ACTION_REGISTRY:
        raise ContractError("action is not in the active finite registry")
    actor_type, channel = packet.get("actor_type"), packet.get("decision_channel")
    if (actor_type, channel) not in {("agent", "llm"), ("user", "console")}:
        raise ContractError("actor lineage is invalid")
    if actor_type == "agent":
        if action != HOLD_ACTION or before != "eligible" or after not in {"deferred_retry", "awaiting_user"}:
            raise ContractError("agent may only create an eligible-to-hold transition")
        reason = packet.get("reason_code")
        if REASON_CODE_HOLD_MODE.get(reason) != after or packet.get("hold_mode") != after:
            raise ContractError("reason_code and hold_mode do not match")
    else:
        if action not in FINAL_ACTIONS or before != "awaiting_user" or after != "closed":
            raise ContractError("user decision requires an awaiting_user hold and closes it")
        _text(packet.get("open_hold_id"), "open_hold_id")
    next_at, hold_packet = packet.get("next_eligible_at"), packet.get("hold_packet")
    if after == "deferred_retry":
        if not next_at or not isinstance(hold_packet, dict) or hold_packet.get("next_eligible_at") != next_at:
            raise ContractError("deferred_retry requires a frozen machine retry packet")
    elif next_at is not None:
        raise ContractError("only deferred_retry may have next_eligible_at")
    if after == "awaiting_user" and next_at is not None:
        raise ContractError("awaiting_user requires next_eligible_at = null")
    return dict(packet)
