#!/usr/bin/env python3
"""Finite reviewed-action payload contract for song_candidate domain staging.

This module has no database or S3 wiring.  It only defines the finite
reviewed action schema that ``apply_song_candidate_finite_actions.py``
consumes, and a pure builder that turns already-decided review inbox
domain_stage rows into that finite schema.  It never guesses an action:
anything not explicitly reviewed becomes ``hold`` (or fails validation).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from review_inbox_adapters.source_writer import SourceWriterError


EXPECTED_SCHEMA_VERSION = 1
EXPECTED_WRITE_MODE = "reviewed_finite_actions"
EXPECTED_SOURCE_ID = "daily_song_candidate"
DOMAIN_STAGE_TYPE = "song_candidate"
DECISION_STAGE_GENERATOR = "review_inbox_decision_stage.py"
DECISION_STAGE_WRITE_MODE = "reviewed_song_finite_actions"

# This module is the one real, in-repo generator of reviewed finite action
# payloads (build_reviewed_payload_from_domain_stage() below always stamps
# this exact name -- it is never taken as a caller-supplied argument, so a
# payload cannot claim to come from this generator without actually going
# through it). TRUSTED_GENERATORS is a set of one for now; a second CLI-based
# generator could be added to the allowlist later if one is ever built.
GENERATOR_NAME = "song_candidate_finite_actions.py"
TRUSTED_GENERATORS = {GENERATOR_NAME}

ACTIONS = {"register_song", "add_song_alias", "reject_song", "hold"}
ACTIONS_REQUIRING_TARGET = {"add_song_alias"}

_TOP_LEVEL_FIELDS = {"schema_version", "generated_by", "write_mode", "decision_count", "decisions"}
_DECISION_ROW_FIELDS = {
    "source_inbox_id",
    "source_id",
    "source_key",
    "candidate_title",
    "action",
    "reviewed_by",
    "reviewed_at",
    "source_url",
    "note",
    "target_song_id",
}
_REQUIRED_ROW_FIELDS = {
    "source_inbox_id",
    "source_id",
    "source_key",
    "candidate_title",
    "action",
    "reviewed_by",
    "reviewed_at",
}


@dataclass(frozen=True)
class ReviewedSongDecision:
    source_inbox_id: str
    source_id: str
    source_key: str
    candidate_title: str
    action: str
    reviewed_by: str
    reviewed_at: str
    source_url: str
    note: str
    target_song_id: str | None


def _require_timestamp(value: Any, *, context: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise SourceWriterError(f"{context}: reviewed_at is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceWriterError(f"{context}: invalid reviewed_at timestamp: {text!r}") from exc
    if parsed.tzinfo is None:
        raise SourceWriterError(f"{context}: reviewed_at timestamp must include a timezone")
    return text


def _require_nonempty(value: Any, field: str, *, context: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise SourceWriterError(f"{context}: {field} is required")
    return text


def validate_reviewed_payload(payload: dict[str, Any]) -> list[ReviewedSongDecision]:
    """Validate the top-level finite reviewed payload and return normalized rows.

    Fails closed on anything that is not an explicit, fully-specified finite
    action: unknown fields, missing metadata, duplicate source_inbox_id,
    empty titles, wrong write_mode/schema_version, and target_song_id used
    outside add_song_alias (or missing for add_song_alias).
    """

    if not isinstance(payload, dict):
        raise SourceWriterError("reviewed song payload root must be an object")
    unknown_top = set(payload) - _TOP_LEVEL_FIELDS
    if unknown_top:
        raise SourceWriterError(
            f"unknown top-level field(s) {sorted(unknown_top)}; "
            "a generic stage packet cannot be padded into a finite payload"
        )
    if payload.get("schema_version") != EXPECTED_SCHEMA_VERSION:
        raise SourceWriterError("reviewed song payload schema_version must be 1")
    generated_by = str(payload.get("generated_by") or "").strip()
    if generated_by not in TRUSTED_GENERATORS:
        raise SourceWriterError(f"reviewed song payload generated_by is not trusted: {generated_by!r}")
    if payload.get("write_mode") != EXPECTED_WRITE_MODE:
        raise SourceWriterError(
            "reviewed song payload write_mode must be reviewed_finite_actions; "
            "generic stage_song_candidate/accept packets are not trusted"
        )
    raw_rows = payload.get("decisions")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise SourceWriterError("reviewed song payload must contain at least one decision")
    if payload.get("decision_count") != len(raw_rows):
        raise SourceWriterError("decision_count does not match staged decisions")

    decisions: list[ReviewedSongDecision] = []
    seen_ids: list[str] = []
    for index, raw in enumerate(raw_rows):
        context = f"decision[{index}]"
        if not isinstance(raw, dict):
            raise SourceWriterError(f"{context}: decision row must be an object")
        unknown = set(raw) - _DECISION_ROW_FIELDS
        if unknown:
            raise SourceWriterError(
                f"{context}: unknown field(s) {sorted(unknown)}; action cannot be inferred"
            )
        missing = _REQUIRED_ROW_FIELDS - {key for key, value in raw.items() if str(value or "").strip()}
        if missing:
            raise SourceWriterError(f"{context}: missing required field(s) {sorted(missing)}")

        source_inbox_id = _require_nonempty(raw.get("source_inbox_id"), "source_inbox_id", context=context)
        source_id = _require_nonempty(raw.get("source_id"), "source_id", context=context)
        if source_id != EXPECTED_SOURCE_ID:
            raise SourceWriterError(f"{context}: unsupported source_id {source_id!r}")
        source_key = _require_nonempty(raw.get("source_key"), "source_key", context=context)
        candidate_title = _require_nonempty(raw.get("candidate_title"), "candidate_title", context=context)
        action = _require_nonempty(raw.get("action"), "action", context=context)
        if action not in ACTIONS:
            raise SourceWriterError(f"{context}: unsupported action {action!r}")
        reviewed_by = _require_nonempty(raw.get("reviewed_by"), "reviewed_by", context=context)
        reviewed_at = _require_timestamp(raw.get("reviewed_at"), context=context)
        source_url = str(raw.get("source_url") or "").strip()
        note = str(raw.get("note") or "").strip()

        target_song_id_raw = raw.get("target_song_id")
        target_song_id = str(target_song_id_raw or "").strip() or None
        if action in ACTIONS_REQUIRING_TARGET:
            if not target_song_id:
                raise SourceWriterError(f"{context}: {action} requires target_song_id")
        elif target_song_id:
            raise SourceWriterError(f"{context}: target_song_id is only valid for add_song_alias")

        decisions.append(
            ReviewedSongDecision(
                source_inbox_id=source_inbox_id,
                source_id=source_id,
                source_key=source_key,
                candidate_title=candidate_title,
                action=action,
                reviewed_by=reviewed_by,
                reviewed_at=reviewed_at,
                source_url=source_url,
                note=note,
                target_song_id=target_song_id,
            )
        )
        seen_ids.append(source_inbox_id)

    duplicates = sorted({value for value in seen_ids if seen_ids.count(value) > 1})
    if duplicates:
        raise SourceWriterError("duplicate source_inbox_id in reviewed song payload: " + ", ".join(duplicates))
    return decisions


def build_reviewed_payload_from_domain_stage(
    domain_stage_rows: list[dict[str, Any]],
    *,
    reviewed_by: str | None = None,
    reviewed_at: str | None = None,
    actions_by_source_inbox_id: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Pure builder: turn already-staged song_candidate rows into a finite payload.

    ``domain_stage_rows`` are rows already written by
    ``review_inbox_adapters.decision_stage`` (each with a ``domain_candidate``
    of ``domain_stage_type == "song_candidate"``). This builder never infers
    ``register_song``/``add_song_alias``/``reject_song`` on its own: every row
    defaults to ``hold`` unless the caller explicitly supplies a reviewed
    action for that source_inbox_id via ``actions_by_source_inbox_id`` or the
    decision-stage packet's explicit ``domain_candidate.finite_action``. An
    explicit action other than the four finite actions fails validation.

    ``generated_by`` is never a caller-supplied argument: this function is
    the only real generator of finite payloads, so it always stamps its own
    module name (GENERATOR_NAME). A caller cannot forge a different trusted
    generator name by calling through this builder.

    Source URL provenance: the real B4 adapter
    (review_inbox_adapters/low_priority_adapters.py common_item()) puts the
    evidence link on the payload as ``evidence_url`` (falling back to
    ``source_url`` only for older/other rows), not on the top-level
    domain_candidate. For legacy rows where ``domain_candidate.source_url``
    is absent, that payload evidence is used. For canonical decision-stage
    rows, the key is always present and its value is preserved even when
    empty, so the P4 lifecycle guard compares the exact inbox source_url.
    """

    actions_by_source_inbox_id = actions_by_source_inbox_id or {}
    decisions: list[dict[str, Any]] = []
    for row in domain_stage_rows:
        candidate = row.get("domain_candidate") or {}
        if row.get("domain_stage_type") != DOMAIN_STAGE_TYPE or candidate.get("kind") != "song":
            continue
        source_inbox_id = str(candidate.get("source_inbox_id") or "")
        payload = candidate.get("payload") or {}
        candidate_title = str(payload.get("canonical_song_name") or payload.get("term") or "")
        action = actions_by_source_inbox_id.get(
            source_inbox_id,
            str(candidate.get("finite_action") or "hold"),
        )
        update = row.get("inbox_update") if isinstance(row.get("inbox_update"), dict) else {}
        row_reviewed_by = str(update.get("decided_by") or reviewed_by or "")
        row_reviewed_at = str(update.get("decided_at") or reviewed_at or "")
        expected_lifecycle = {
            "register_song": ("accepted", "domain_stage"),
            "add_song_alias": ("accepted", "domain_stage"),
            "reject_song": ("rejected", "no_apply"),
            "hold": ("hold", "no_apply"),
        }.get(action)
        if update and expected_lifecycle != (
            str(update.get("decision") or ""),
            str(update.get("decision_route") or ""),
        ):
            raise SourceWriterError(
                f"song finite action lifecycle mismatch for {source_inbox_id}"
            )
        if "source_url" in candidate:
            source_url = candidate.get("source_url")
        else:
            source_url = payload.get("evidence_url") or payload.get("source_url") or ""
        decision_row: dict[str, Any] = {
            "source_inbox_id": source_inbox_id,
            "source_id": str(candidate.get("source_id") or EXPECTED_SOURCE_ID),
            "source_key": str(candidate.get("source_key") or ""),
            "candidate_title": candidate_title,
            "action": action,
            "reviewed_by": row_reviewed_by,
            "reviewed_at": row_reviewed_at,
            "source_url": str(source_url or ""),
            "note": str(row.get("note") or payload.get("note") or ""),
        }
        target_song_id = (
            actions_by_source_inbox_id.get(f"{source_inbox_id}:target_song_id")
            or candidate.get("target_song_id")
        )
        if target_song_id:
            decision_row["target_song_id"] = target_song_id
        decisions.append(decision_row)

    payload_out = {
        "schema_version": EXPECTED_SCHEMA_VERSION,
        "generated_by": GENERATOR_NAME,
        "write_mode": EXPECTED_WRITE_MODE,
        "decision_count": len(decisions),
        "decisions": decisions,
    }
    validate_reviewed_payload(payload_out)
    return payload_out


def build_reviewed_payload_from_decision_stage(
    stage_payload: dict[str, Any],
) -> dict[str, Any]:
    """Build the trusted P4 payload from one console decision-stage artifact.

    The stage artifact must be the dedicated song finite-action file emitted
    by ``write_decision_stage``.  It carries the exact inbox lifecycle and
    explicit finite action for every row; this function never guesses either.
    """

    if not isinstance(stage_payload, dict):
        raise SourceWriterError("song decision stage root must be an object")
    if stage_payload.get("schema_version") != 1:
        raise SourceWriterError("song decision stage schema_version must be 1")
    if stage_payload.get("generated_by") != DECISION_STAGE_GENERATOR:
        raise SourceWriterError("song decision stage generated_by is not trusted")
    if stage_payload.get("write_mode") != DECISION_STAGE_WRITE_MODE:
        raise SourceWriterError(
            "song decision stage write_mode must be reviewed_song_finite_actions"
        )
    rows = stage_payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise SourceWriterError("song decision stage must contain at least one row")
    if stage_payload.get("decision_count") != len(rows):
        raise SourceWriterError("song decision stage decision_count mismatch")
    if any(
        (row.get("domain_candidate") or {}).get("finite_action") == "hold"
        for row in rows
        if isinstance(row, dict)
    ):
        raise SourceWriterError(
            "hold is review-only and must remain pending; it cannot enter the P4 action packet"
        )
    return build_reviewed_payload_from_domain_stage(rows)
