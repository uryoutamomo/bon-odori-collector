"""Pure local-judgment v1 packet, transition, registry, and hold contracts.

This module has no database or domain writer.  Existing CAS/source identity
checks remain the responsibility of the established decision writer.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Mapping


SCHEMA_VERSION = 1
REGISTRY_VERSION = "local-judgment-lifecycle/v1"
QUEUE_STATES = {"eligible", "deferred_retry", "awaiting_user", "closed"}
ACTOR_CHANNELS = {"agent": "llm", "user": "console", "system": "scheduler"}
REASON_CODE_HOLD_MODE = {
    "awaiting_official_announcement": "deferred_retry",
    "source_temporarily_unavailable": "deferred_retry",
    "packet_stale": "deferred_retry",
    "insufficient_announcement_history": "awaiting_user",
    "requires_policy_judgment": "awaiting_user",
    "ambiguous_event_series": "awaiting_user",
    "ambiguous_occurrence": "awaiting_user",
    "ambiguous_venue": "awaiting_user",
    "missing_target_id": "awaiting_user",
    "conflicting_sources": "awaiting_user",
    "insufficient_evidence": "awaiting_user",
    "distinct_event_uncertain": "awaiting_user",
    "publication_scope_needed": "awaiting_user",
}
LANES = {
    ("event", "event_create"): "series",
    ("event", "event_update"): "occurrence",
    ("song", "song"): "song",
    ("term", "term"): "term",
}
ACTION_DEFINITIONS = {
    "accept": ("採用", True, {"agent", "user"}),
    "reject": ("却下", True, {"agent", "user"}),
    "hold": ("保留", False, {"agent"}),
    "requeue": ("再投入", False, {"system"}),
}
COMMON_PAYLOAD_FIELDS = {"target_id", "reason_detail", "evidence_class"}
REQUEUE_PAYLOAD_FIELDS = {"hold_id", "released_at", "next_eligible_at"}

# Tuple-keyed data registry. E2a/T2 can append domain actions without changing
# transition validation code.
ACTION_REGISTRY = {
    (domain, lane, action): {
        "label_ja": label,
        "terminal": terminal,
        "allowed_actor_types": frozenset(actors),
        "required_target_type": target_type,
        "allowed_payload_fields": frozenset(
            REQUEUE_PAYLOAD_FIELDS if action == "requeue" else COMMON_PAYLOAD_FIELDS
        ),
    }
    for (domain, lane), target_type in LANES.items()
    for action, (label, terminal, actors) in ACTION_DEFINITIONS.items()
}

TRANSITIONS = frozenset({
    ("eligible", "closed", "agent", "accept"),
    ("eligible", "closed", "agent", "reject"),
    ("eligible", "deferred_retry", "agent", "hold"),
    ("eligible", "awaiting_user", "agent", "hold"),
    ("deferred_retry", "eligible", "system", "requeue"),
    ("awaiting_user", "closed", "user", "accept"),
    ("awaiting_user", "closed", "user", "reject"),
})

CANONICAL_FIELDS = frozenset({
    "schema_version", "packet_type", "decision_id", "packet_id", "packet_sha256",
    "inbox_id", "domain", "lane", "source_id", "source_key", "source_payload_hash",
    "action", "queue_state_before", "queue_state_after", "reason_code", "hold_mode",
    "next_eligible_at", "hold_packet", "payload", "actor_type", "actor_id",
    "decision_channel", "decided_at", "prior_agent_attempt_id", "open_hold_id",
    "adjudication_batch_id",
})


class ContractError(ValueError):
    """Raised before an invalid packet can reach a writer."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ContractError(f"{field} is required")
    return text


def _sha(value: Any, field: str) -> str:
    text = _text(value, field)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text.casefold()):
        raise ContractError(f"{field} must be SHA-256")
    return text.casefold()


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
    if ACTOR_CHANNELS.get(actor_type) != channel:
        raise ContractError("trusted actor_type and decision_channel do not match")
    return {
        "actor_type": actor_type,
        "actor_id": _text(actor.get("actor_id"), "trusted actor_id"),
        "decision_channel": channel,
        "decided_at": _iso(actor.get("decided_at"), "trusted decided_at"),
    }


def registry_entry(domain: str, lane: str, action: str) -> Mapping[str, Any]:
    try:
        return ACTION_REGISTRY[(domain, lane, action)]
    except KeyError as exc:
        raise ContractError(f"unregistered action tuple: {(domain, lane, action)!r}") from exc


def canonicalize_raw_judgment(
    raw: Mapping[str, Any], *, trusted_actor: Mapping[str, Any]
) -> dict[str, Any]:
    """Normalize untrusted JSON while stamping lineage from the local entrypoint."""
    actor = _trusted_actor(trusted_actor)
    domain = _text(raw.get("domain"), "domain")
    lane = _text(raw.get("lane"), "lane")
    action = _text(raw.get("requested_action"), "requested_action")
    entry = registry_entry(domain, lane, action)
    if actor["actor_type"] not in entry["allowed_actor_types"]:
        raise ContractError("action is not allowed for the trusted actor")
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        raise ContractError("payload must be an object")
    extra = set(payload) - set(entry["allowed_payload_fields"])
    if extra:
        raise ContractError(f"payload fields are not allowed: {sorted(extra)}")
    packet = {
        "schema_version": SCHEMA_VERSION,
        "packet_type": "raw_judgment",
        "packet_id": _text(raw.get("packet_id"), "packet_id"),
        "inbox_id": _text(raw.get("inbox_id"), "inbox_id"),
        "domain": domain,
        "lane": lane,
        "source_id": _text(raw.get("source_id"), "source_id"),
        "source_key": _text(raw.get("source_key"), "source_key"),
        "source_payload_hash": _sha(raw.get("source_payload_hash"), "source_payload_hash"),
        "requested_action": action,
        "payload": dict(payload),
        **actor,
    }
    packet["packet_sha256"] = sha256_hex(packet)
    return packet


def decision_id_for(packet: Mapping[str, Any], action: str) -> str:
    identity = {
        "schema_version": packet["schema_version"],
        "domain": packet["domain"],
        "inbox_id": packet["inbox_id"],
        "packet_id": packet["packet_id"],
        "actor_type": packet["actor_type"],
        "action": action,
        "source_payload_hash": packet["source_payload_hash"],
    }
    return "decision:" + sha256_hex(identity)


def _base(raw: Mapping[str, Any], *, before: str, after: str) -> dict[str, Any]:
    action = raw["requested_action"]
    return {
        "schema_version": SCHEMA_VERSION,
        "packet_type": "canonical_decision",
        "decision_id": decision_id_for(raw, action),
        "packet_id": raw["packet_id"],
        "packet_sha256": raw["packet_sha256"],
        "inbox_id": raw["inbox_id"],
        "domain": raw["domain"],
        "lane": raw["lane"],
        "source_id": raw["source_id"],
        "source_key": raw["source_key"],
        "source_payload_hash": raw["source_payload_hash"],
        "action": action,
        "queue_state_before": before,
        "queue_state_after": after,
        "reason_code": None,
        "hold_mode": None,
        "next_eligible_at": None,
        "hold_packet": None,
        "payload": dict(raw["payload"]),
        "actor_type": raw["actor_type"],
        "actor_id": raw["actor_id"],
        "decision_channel": raw["decision_channel"],
        "decided_at": raw["decided_at"],
        "prior_agent_attempt_id": None,
        "open_hold_id": None,
        "adjudication_batch_id": None,
    }


def build_agent_terminal_decision(raw: Mapping[str, Any]) -> dict[str, Any]:
    if raw.get("actor_type") != "agent" or raw.get("requested_action") not in {"accept", "reject"}:
        raise ContractError("agent terminal decision requires agent accept or reject")
    packet = _base(raw, before="eligible", after="closed")
    return validate_canonical_decision(packet)


def _retry_hold_packet(
    retry_candidates: list[Mapping[str, Any]], selected_candidate_id: str
) -> tuple[str, dict[str, Any]]:
    selected = next(
        (row for row in retry_candidates if str(row.get("candidate_id") or "") == selected_candidate_id),
        None,
    )
    if selected is None:
        raise ContractError("selected retry candidate is not machine-provided")
    eligible = _iso(selected.get("next_eligible_at"), "candidate next_eligible_at")
    start = _iso(selected.get("window_start"), "candidate window_start")
    end = _iso(selected.get("window_end"), "candidate window_end")
    parsed = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not parsed(start) <= parsed(eligible) <= parsed(end):
        raise ContractError("candidate next_eligible_at is outside its machine-calculated window")
    frozen = {
        "candidate_id": selected_candidate_id,
        "next_eligible_at": eligible,
        "window_start": start,
        "window_end": end,
        "occurrence_ids": list(selected.get("occurrence_ids") or []),
        "evidence_ids": list(selected.get("evidence_ids") or []),
        "retrieved_at": _iso(selected.get("retrieved_at"), "candidate retrieved_at"),
        "calculation_version": _text(selected.get("calculation_version"), "candidate calculation_version"),
        "input_hash": _sha(selected.get("input_hash"), "candidate input_hash"),
    }
    if not frozen["occurrence_ids"] or not frozen["evidence_ids"]:
        raise ContractError("retry candidate must freeze occurrence and evidence IDs")
    return eligible, frozen


def build_canonical_hold(
    raw: Mapping[str, Any], *, reason_code: str,
    retry_candidates: list[Mapping[str, Any]] | None = None,
    selected_candidate_id: str | None = None,
) -> dict[str, Any]:
    if raw.get("actor_type") != "agent" or raw.get("requested_action") != "hold":
        raise ContractError("only agent hold may open a hold")
    mode = REASON_CODE_HOLD_MODE.get(reason_code)
    if mode is None:
        raise ContractError(f"unknown reason_code: {reason_code}")
    packet = _base(raw, before="eligible", after=mode)
    packet["reason_code"] = reason_code
    packet["hold_mode"] = mode
    if mode == "deferred_retry":
        if not selected_candidate_id:
            raise ContractError("deferred_retry requires a selected machine candidate")
        packet["next_eligible_at"], packet["hold_packet"] = _retry_hold_packet(
            retry_candidates or [], selected_candidate_id
        )
    return validate_canonical_decision(packet)


def build_user_decision(
    raw: Mapping[str, Any], *, open_hold: Mapping[str, Any]
) -> dict[str, Any]:
    if raw.get("actor_type") != "user" or raw.get("requested_action") not in {"accept", "reject"}:
        raise ContractError("user terminal decision requires user accept or reject")
    if open_hold.get("status") != "open":
        raise ContractError("console decision requires status=open hold")
    if open_hold.get("hold_mode") != "awaiting_user":
        raise ContractError("console decision requires an awaiting_user hold")
    for field in ("inbox_id", "domain", "lane"):
        if open_hold.get(field) != raw.get(field):
            raise ContractError(f"open hold {field} differs from the decision target")
    packet = _base(raw, before="awaiting_user", after="closed")
    packet["prior_agent_attempt_id"] = _text(
        open_hold.get("prior_agent_attempt_id"), "prior_agent_attempt_id"
    )
    packet["open_hold_id"] = _text(open_hold.get("hold_id"), "open_hold_id")
    packet["adjudication_batch_id"] = open_hold.get("adjudication_batch_id")
    return validate_canonical_decision(packet)


def build_requeue(raw: Mapping[str, Any], *, open_hold: Mapping[str, Any]) -> dict[str, Any]:
    if raw.get("actor_type") != "system" or raw.get("requested_action") != "requeue":
        raise ContractError("requeue requires the system scheduler lane")
    if open_hold.get("status") != "open" or open_hold.get("hold_mode") != "deferred_retry":
        raise ContractError("requeue requires an open deferred_retry hold")
    payload = raw.get("payload") or {}
    if payload.get("hold_id") != open_hold.get("hold_id"):
        raise ContractError("requeue targets another hold")
    released_at = _iso(payload.get("released_at"), "released_at")
    next_at = _iso(open_hold.get("next_eligible_at"), "next_eligible_at")
    if datetime.fromisoformat(released_at.replace("Z", "+00:00")) < datetime.fromisoformat(next_at.replace("Z", "+00:00")):
        raise ContractError("released_at is before next_eligible_at")
    if payload.get("next_eligible_at") != next_at:
        raise ContractError("requeue next_eligible_at differs from the open hold")
    packet = _base(raw, before="deferred_retry", after="eligible")
    return validate_canonical_decision(packet)


def validate_canonical_decision(packet: Mapping[str, Any]) -> dict[str, Any]:
    missing = CANONICAL_FIELDS - set(packet)
    if missing:
        raise ContractError(f"canonical decision fields are missing: {sorted(missing)}")
    if packet.get("schema_version") != SCHEMA_VERSION or packet.get("packet_type") != "canonical_decision":
        raise ContractError("unsupported canonical decision schema")
    for field in ("decision_id", "packet_id", "inbox_id", "domain", "lane", "source_id", "source_key", "actor_id"):
        _text(packet.get(field), field)
    _sha(packet.get("packet_sha256"), "packet_sha256")
    _sha(packet.get("source_payload_hash"), "source_payload_hash")
    _iso(packet.get("decided_at"), "decided_at")
    if not isinstance(packet.get("payload"), dict):
        raise ContractError("payload must be an object")
    action = packet.get("action")
    entry = registry_entry(packet["domain"], packet["lane"], action)
    actor_type = packet.get("actor_type")
    if ACTOR_CHANNELS.get(actor_type) != packet.get("decision_channel"):
        raise ContractError("actor lineage is invalid")
    if actor_type not in entry["allowed_actor_types"]:
        raise ContractError("action is not allowed for actor_type")
    extra = set(packet["payload"]) - set(entry["allowed_payload_fields"])
    if extra:
        raise ContractError(f"payload fields are not allowed: {sorted(extra)}")
    transition = (
        packet.get("queue_state_before"), packet.get("queue_state_after"), actor_type, action
    )
    if transition not in TRANSITIONS:
        raise ContractError(f"transition is not allowed: {transition!r}")
    if packet["decision_id"] != decision_id_for(packet, action):
        raise ContractError("decision_id does not match canonical identity")

    is_hold = action == "hold"
    if is_hold:
        expected_mode = REASON_CODE_HOLD_MODE.get(packet.get("reason_code"))
        if expected_mode is None:
            raise ContractError("unknown reason_code")
        if packet.get("hold_mode") != expected_mode or packet.get("queue_state_after") != expected_mode:
            raise ContractError("reason_code and hold_mode do not match")
        if expected_mode == "deferred_retry":
            hold_packet = packet.get("hold_packet")
            if not packet.get("next_eligible_at") or not isinstance(hold_packet, dict):
                raise ContractError("deferred_retry requires next_eligible_at and hold_packet")
            if hold_packet.get("next_eligible_at") != packet["next_eligible_at"]:
                raise ContractError("hold packet next_eligible_at mismatch")
        elif packet.get("next_eligible_at") is not None or packet.get("hold_packet") is not None:
            raise ContractError("awaiting_user requires null retry fields")
    elif any(packet.get(field) is not None for field in ("reason_code", "hold_mode", "next_eligible_at", "hold_packet")):
        raise ContractError("non-hold decision requires null hold fields")

    if actor_type == "user":
        _text(packet.get("prior_agent_attempt_id"), "prior_agent_attempt_id")
        _text(packet.get("open_hold_id"), "open_hold_id")
    elif packet.get("prior_agent_attempt_id") is not None or packet.get("open_hold_id") is not None:
        raise ContractError("non-user decision requires null user lineage fields")
    if action == "requeue":
        released_at = _iso(packet["payload"].get("released_at"), "payload.released_at")
        payload_next = _iso(packet["payload"].get("next_eligible_at"), "payload.next_eligible_at")
        if datetime.fromisoformat(released_at.replace("Z", "+00:00")) < datetime.fromisoformat(payload_next.replace("Z", "+00:00")):
            raise ContractError("released_at is before payload.next_eligible_at")
    return dict(packet)


def build_hold_ledger_entry(
    decision: Mapping[str, Any], *, hold_id: str, reason_detail: str | None = None,
    expires_at: str | None = None, candidate_ids: list[str] | None = None,
) -> dict[str, Any]:
    decision = validate_canonical_decision(decision)
    if decision["action"] != "hold":
        raise ContractError("hold ledger entry requires a hold decision")
    entry = registry_entry(decision["domain"], decision["lane"], "accept")
    mode = decision["hold_mode"]
    allowed_actions = ["requeue"] if mode == "deferred_retry" else ["accept", "reject"]
    hold_packet = decision.get("hold_packet") or {}
    if candidate_ids is None:
        frozen_candidates = [hold_packet["candidate_id"]] if hold_packet.get("candidate_id") else []
    else:
        frozen_candidates = sorted(_text(candidate_id, "candidate_id") for candidate_id in candidate_ids)
        if len(set(frozen_candidates)) != len(frozen_candidates):
            raise ContractError("candidate_ids must not contain duplicates")
    candidate_set_sha256 = sha256_hex(frozen_candidates) if frozen_candidates else None
    evidence_class = str(decision["payload"].get("evidence_class") or "") or None
    grouping_fingerprint = sha256_hex({
        "domain": decision["domain"], "lane": decision["lane"],
        "reason_code": decision["reason_code"], "registry_version": REGISTRY_VERSION,
        "allowed_actions": sorted(allowed_actions),
        "required_target_type": entry["required_target_type"],
        "evidence_class": evidence_class,
    })
    return {
        "hold_id": _text(hold_id, "hold_id"),
        "decision_id": decision["decision_id"],
        "inbox_id": decision["inbox_id"],
        "domain": decision["domain"],
        "lane": decision["lane"],
        "hold_mode": mode,
        "reason_code": decision["reason_code"],
        "reason_detail": reason_detail,
        "required_resolution_type": "scheduled_requeue" if mode == "deferred_retry" else "user_terminal_decision",
        "allowed_actions": sorted(allowed_actions),
        "candidate_ids": frozen_candidates or None,
        "candidate_set_sha256": candidate_set_sha256,
        "prior_agent_attempt_id": decision["decision_id"],
        "grouping_fingerprint": grouping_fingerprint,
        "status": "open",
        "queue_state": mode,
        "next_eligible_at": decision["next_eligible_at"],
        "hold_packet_json": decision["hold_packet"],
        "opened_at": decision["decided_at"],
        "expires_at": _iso(expires_at, "expires_at") if expires_at else None,
        "closed_at": None,
        "resolved_by_decision_id": None,
    }
