"""Apply frozen human/agent decisions to complete low-priority snapshots.

The overlay is deliberately projection-only: it does not write review lifecycle
columns or domain facts.  A decision closes a current-source item only when its
stable identity and payload hash still match the item that was judged.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from review_inbox_adapters.parity import item_payload_hash
from review_inbox_adapters.source_adapter import input_sha256


SCHEMA_VERSION = 1
ALLOWED_ACTOR_TYPES = {"agent", "user"}
ALLOWED_DECISIONS = {
    "daily_song_candidate": {"曲として採用", "曲ではない", "分割", "用語集へ", "保留"},
    "daily_term_candidate": {"採用", "不採用", "保留"},
    "accepted_venue_song_missing_venue": {"会場追加", "既存に統合", "不採用", "保留"},
}
REQUIRED_FIELDS = {
    "source_id",
    "source_key",
    "inbox_id",
    "source_payload_hash",
    "decision",
    "actor_type",
    "actor_id",
    "decided_at",
    "reason_detail",
}


class DecisionOverlayError(ValueError):
    """Raised when a decision overlay could hide the wrong inbox item."""


def load_overlay(path: Path | None) -> dict[str, Any] | None:
    if path is None or not Path(path).exists():
        return None
    raw = Path(path).read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise DecisionOverlayError("unsupported backlog decision overlay schema")
    rows = payload.get("decisions")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise DecisionOverlayError("backlog decision overlay requires decisions list")
    payload = dict(payload)
    payload["overlay_sha256"] = input_sha256(raw)
    return payload


def _validated_index(overlay: Mapping[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in overlay.get("decisions") or []:
        missing = sorted(REQUIRED_FIELDS - set(raw))
        if missing:
            raise DecisionOverlayError("decision fields are missing: " + ", ".join(missing))
        row = dict(raw)
        source_id = str(row["source_id"] or "").strip()
        source_key = str(row["source_key"] or "").strip()
        if not source_id or not source_key:
            raise DecisionOverlayError("decision source identity is required")
        if row["decision"] not in ALLOWED_DECISIONS.get(source_id, set()):
            raise DecisionOverlayError(f"unsupported decision for {source_id}: {row['decision']}")
        if row["actor_type"] not in ALLOWED_ACTOR_TYPES or not str(row["actor_id"] or "").strip():
            raise DecisionOverlayError("decision actor lineage is invalid")
        for field in ("inbox_id", "decided_at", "reason_detail"):
            if not str(row[field] or "").strip():
                raise DecisionOverlayError(f"decision {field} is required")
        try:
            decided_at = datetime.fromisoformat(str(row["decided_at"]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise DecisionOverlayError("decision decided_at must be ISO-8601") from exc
        if decided_at.tzinfo is None:
            raise DecisionOverlayError("decision decided_at must include a timezone")
        payload_hash = str(row["source_payload_hash"] or "")
        if len(payload_hash) != 64 or any(char not in "0123456789abcdef" for char in payload_hash.casefold()):
            raise DecisionOverlayError("decision source_payload_hash must be SHA-256")
        key = (source_id, source_key)
        if key in indexed:
            raise DecisionOverlayError(f"duplicate decision identity: {key!r}")
        indexed[key] = row
    return indexed


def apply_overlay(snapshot: Mapping[str, Any], overlay: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return the still-pending complete snapshot plus decision audit metadata."""
    result = dict(snapshot)
    items = [dict(item) for item in snapshot.get("items") or []]
    if overlay is None:
        return result

    indexed = _validated_index(overlay)
    source_id = str(snapshot.get("source_id") or "")
    kept: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    for item in items:
        key = (source_id, str(item.get("source_key") or ""))
        decision = indexed.get(key)
        if decision is None:
            kept.append(item)
            continue
        if decision["inbox_id"] != item.get("inbox_id"):
            raise DecisionOverlayError(f"decision inbox identity mismatch: {item.get('inbox_id')}")
        current_hash = item_payload_hash(item)
        if decision["source_payload_hash"] != current_hash:
            kept.append(item)
            stale.append({
                "inbox_id": item["inbox_id"],
                "source_key": item["source_key"],
                "judged_hash": decision["source_payload_hash"],
                "current_hash": current_hash,
                "reason": "source_payload_changed",
            })
            continue
        applied.append({
            "inbox_id": item["inbox_id"],
            "source_key": item["source_key"],
            "decision": decision["decision"],
            "actor_type": decision["actor_type"],
            "actor_id": decision["actor_id"],
            "decided_at": decision["decided_at"],
        })

    result["items"] = kept
    result["item_count"] = len(kept)
    result["decision_overlay"] = {
        "schema_version": overlay["schema_version"],
        "path": str(overlay.get("source_path") or ""),
        "sha256": str(overlay.get("overlay_sha256") or ""),
        "applied_count": len(applied),
        "stale_count": len(stale),
        "applied": applied,
        "stale": stale,
    }
    return result
