"""Validate frozen LLM resolutions for stale awaiting-user event holds.

The overlay is projection-only.  It may hide a hold from the human lane only
when the hold, prior agent answer, source payload, and current canonical
occurrence still describe the exact record that was judged.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1
REQUIRED_FIELDS = {
    "hold_id",
    "inbox_id",
    "title",
    "classification",
    "confidence",
    "recommended_action",
    "reason_detail",
    "source_payload_hash",
    "prior_agent_attempt_id",
    "duplicate_target_occurrence_id",
    "target_series_id",
    "target_venue_id",
    "target_date_start",
    "checked_at",
}


class EventHoldOverlayError(ValueError):
    """Raised when an overlay could hide an unrelated human-review hold."""


def load_event_hold_overlay(path: Path | None) -> dict[str, Any] | None:
    if path is None or not Path(path).exists():
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise EventHoldOverlayError("unsupported event hold overlay schema")
    if not isinstance(payload.get("decisions"), list):
        raise EventHoldOverlayError("event hold overlay requires decisions list")
    return payload


def validated_event_hold_index(
    overlay: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if overlay is None:
        return {}
    actor_id = str(overlay.get("generated_by") or "").strip()
    generated_at = str(overlay.get("generated_at") or "").strip()
    if not actor_id or not generated_at:
        raise EventHoldOverlayError("event hold overlay actor lineage is required")
    try:
        generated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EventHoldOverlayError("event hold generated_at must be ISO-8601") from exc
    if generated.tzinfo is None:
        raise EventHoldOverlayError("event hold generated_at must include a timezone")
    indexed: dict[str, dict[str, Any]] = {}
    for raw in overlay.get("decisions") or []:
        if not isinstance(raw, dict):
            raise EventHoldOverlayError("event hold decisions must be objects")
        missing = sorted(REQUIRED_FIELDS - set(raw))
        if missing:
            raise EventHoldOverlayError("event hold decision fields are missing: " + ", ".join(missing))
        row = dict(raw)
        if row["classification"] != "duplicate_or_alias" or row["recommended_action"] != "merge":
            raise EventHoldOverlayError("event hold overlay only accepts exact duplicate resolutions")
        if row["confidence"] not in {"high", "medium"}:
            raise EventHoldOverlayError("event hold duplicate confidence must be high or medium")
        for field in (
            "hold_id",
            "inbox_id",
            "title",
            "reason_detail",
            "source_payload_hash",
            "prior_agent_attempt_id",
            "duplicate_target_occurrence_id",
            "target_series_id",
            "target_venue_id",
            "checked_at",
        ):
            if not str(row.get(field) or "").strip():
                raise EventHoldOverlayError(f"event hold decision {field} is required")
        source_hash = str(row["source_payload_hash"])
        if len(source_hash) != 64 or any(char not in "0123456789abcdef" for char in source_hash.casefold()):
            raise EventHoldOverlayError("event hold source_payload_hash must be SHA-256")
        try:
            checked_at = datetime.fromisoformat(str(row["checked_at"]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise EventHoldOverlayError("event hold checked_at must be ISO-8601") from exc
        if checked_at.tzinfo is None:
            raise EventHoldOverlayError("event hold checked_at must include a timezone")
        hold_id = str(row["hold_id"])
        if hold_id in indexed:
            raise EventHoldOverlayError(f"duplicate event hold decision: {hold_id}")
        row["actor_id"] = actor_id
        indexed[hold_id] = row
    return indexed


def exact_event_hold_resolution(
    hold: Mapping[str, Any],
    occurrence: Mapping[str, Any] | None,
    decision: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Return an audit record only when every frozen/current identity matches."""
    if decision is None or occurrence is None:
        return None
    exact_hold_fields = {
        "hold_id": hold.get("hold_id"),
        "inbox_id": hold.get("inbox_id"),
        "title": hold.get("title"),
        "source_payload_hash": hold.get("inbox_source_payload_hash"),
        "prior_agent_attempt_id": hold.get("prior_agent_attempt_id"),
    }
    if any(decision.get(field) != value for field, value in exact_hold_fields.items()):
        return None
    if hold.get("decision_source_payload_hash") != hold.get("inbox_source_payload_hash"):
        return None

    try:
        prior = json.loads(str(hold.get("prior_payload_json") or "{}"))
        candidate = json.loads(str(hold.get("inbox_payload_json") or "{}"))
    except (TypeError, ValueError):
        return None
    target_id = decision["duplicate_target_occurrence_id"]
    proposal = candidate.get("proposal") if isinstance(candidate, dict) else {}
    resolved = candidate.get("resolved_target") if isinstance(candidate, dict) else {}
    if not isinstance(proposal, dict) or not isinstance(resolved, dict):
        return None
    if proposal.get("explicit_occurrence_id") != target_id or resolved.get("occurrence_id") != target_id:
        return None
    if prior.get("occurrence_match") != target_id:
        return None
    if prior.get("series_match") != decision["target_series_id"] or prior.get("venue_match") != "none":
        return None

    occurrence_fields = {
        "occurrence_id": target_id,
        "series_id": decision["target_series_id"],
        "venue_id": decision["target_venue_id"],
        "date_start": decision["target_date_start"],
        "display_name": hold.get("event_name"),
        "event_year": hold.get("event_year"),
        "venue_name": hold.get("venue"),
    }
    if any(occurrence.get(field) != value for field, value in occurrence_fields.items()):
        return None
    return {
        "decision": "auto_existing_occurrence_duplicate_hold",
        "label": "既存開催回に統合済み",
        "reason": decision["reason_detail"],
        "actor_id": decision["actor_id"],
        "checked_at": decision["checked_at"],
        "target_occurrence_id": target_id,
    }
