#!/usr/bin/env python3
"""Common, side-effect-free source adapter contract for the review inbox.

Adapters translate one decoded legacy JSON payload into pending inbox items.
They do not write SQLite, stage decisions, or apply domain changes. The loader
records the exact input bytes so later parity reports can distinguish an input
lineage difference from an adapter difference.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

from review_inbox import TIME_SCOPES, inbox_id_for, infer_time_scope


LIFECYCLE_FIELDS = {
    "status",
    "decision",
    "decided_by",
    "decided_at",
    "closed_at",
    "decision_route",
    "source_payload_hash",
    "last_seen_at",
    "created_at",
    "updated_at",
}
REQUIRED_ITEM_FIELDS = {"kind", "title", "source_key"}


class ReviewInboxSourceAdapter(Protocol):
    """Pure transformer implemented by each legacy review source."""

    source_id: str

    def adapt(self, payload: Any) -> Iterable[Mapping[str, Any]]:
        """Return pending inbox item mappings without writing external state."""


def input_sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def normalize_adapter_item(source_id: str, item: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        raise TypeError("review inbox adapter items must be mappings")
    missing = sorted(field for field in REQUIRED_ITEM_FIELDS if not item.get(field))
    if missing:
        raise ValueError(f"review inbox adapter item is missing required fields: {', '.join(missing)}")
    forbidden = sorted(LIFECYCLE_FIELDS.intersection(item))
    if forbidden:
        raise ValueError(
            "review inbox adapters cannot set lifecycle fields: " + ", ".join(forbidden)
        )
    item_source_id = item.get("source_id")
    if item_source_id and item_source_id != source_id:
        raise ValueError(
            f"review inbox adapter source_id mismatch: {item_source_id!r} != {source_id!r}"
        )

    normalized = copy.deepcopy(dict(item))
    normalized["source_id"] = source_id
    normalized["domain"] = normalized.get("domain") or "その他"
    normalized["time_scope"] = normalized.get("time_scope") or infer_time_scope(
        str(normalized["kind"])
    )
    if normalized["time_scope"] not in TIME_SCOPES:
        raise ValueError(f"unsupported review inbox time_scope: {normalized['time_scope']}")
    normalized["recommended_action"] = normalized.get("recommended_action") or ""
    payload = normalized.get("payload")
    normalized["payload"] = copy.deepcopy({} if payload is None else payload)
    normalized["inbox_id"] = inbox_id_for(normalized)
    return normalized


def adapt_source_payload(adapter: ReviewInboxSourceAdapter, payload: Any) -> list[dict[str, Any]]:
    source_id = str(getattr(adapter, "source_id", "") or "").strip()
    if not source_id:
        raise ValueError("review inbox source adapter requires source_id")

    adapter_input = copy.deepcopy(payload)
    items = [normalize_adapter_item(source_id, item) for item in adapter.adapt(adapter_input)]
    inbox_ids = [item["inbox_id"] for item in items]
    duplicates = sorted(inbox_id for inbox_id, count in Counter(inbox_ids).items() if count > 1)
    if duplicates:
        raise ValueError(
            "review inbox adapter emitted duplicate stable ids: " + ", ".join(duplicates)
        )
    return items


def load_adapted_source(
    adapter: ReviewInboxSourceAdapter,
    input_path: Path,
) -> dict[str, Any]:
    """Load one JSON source and return items plus deterministic input lineage."""
    input_path = Path(input_path)
    raw = input_path.read_bytes()
    payload = json.loads(raw)
    items = adapt_source_payload(adapter, payload)
    return {
        "source_id": str(adapter.source_id).strip(),
        "input_path": str(input_path),
        "input_sha256": input_sha256(raw),
        "input_size_bytes": len(raw),
        "item_count": len(items),
        "items": items,
    }


def write_adapted_snapshot(snapshot: dict[str, Any], output_path: Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(snapshot, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    os.replace(temp_path, output_path)
