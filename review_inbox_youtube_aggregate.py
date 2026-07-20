#!/usr/bin/env python3
"""Build the complete YouTube review-inbox snapshot from all legacy queues."""

from __future__ import annotations

import argparse
import hashlib
import json
import string
from pathlib import Path
from typing import Any, Callable

from review_inbox_parity import item_payload_hash
from review_inbox_source_adapter import write_adapted_snapshot
from review_inbox_youtube_adapter import DEFAULT_INPUT as ACTIVE_INPUT
from review_inbox_youtube_adapter import build_snapshot as build_active_snapshot
from review_inbox_youtube_user_confirmation_adapter import DEFAULT_INPUT as USER_INPUT
from review_inbox_youtube_user_confirmation_adapter import build_snapshot as build_user_snapshot
from review_inbox_youtube_year_backfill_adapter import DEFAULT_INPUT as YEAR_INPUT
from review_inbox_youtube_year_backfill_adapter import build_snapshot as build_year_snapshot


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "data" / "review_inbox_adapted" / "youtube_aggregate.json"
QUEUE_ORDER = ("active_video", "year_backfill", "user_confirmation")
PRECEDENCE = tuple(reversed(QUEUE_ORDER))


def lineage(queue: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "queue": queue,
        "path": snapshot.get("input_path") or "",
        "sha256": snapshot.get("input_sha256") or "",
        "size_bytes": snapshot.get("input_size_bytes"),
        "item_count": snapshot.get("item_count"),
        "supporting_inputs": snapshot.get("supporting_input_lineage") or [],
    }


def composite_sha256(entries: list[dict[str, Any]]) -> str:
    raw = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def build_aggregate_snapshot(
    active_input: Path,
    year_input: Path,
    user_input: Path,
    *,
    active_builder: Callable[[Path], dict[str, Any]] = build_active_snapshot,
    year_builder: Callable[[Path], dict[str, Any]] = build_year_snapshot,
    user_builder: Callable[[Path], dict[str, Any]] = build_user_snapshot,
) -> dict[str, Any]:
    snapshots = {
        "active_video": active_builder(Path(active_input)),
        "year_backfill": year_builder(Path(year_input)),
        "user_confirmation": user_builder(Path(user_input)),
    }
    for queue in QUEUE_ORDER:
        snapshot = snapshots[queue]
        if snapshot.get("source_id") != "youtube_evidence":
            raise ValueError(f"YouTube aggregate queue has wrong source_id: {queue}")
        if snapshot.get("selection", {}).get("mode") != "all":
            raise ValueError(f"YouTube aggregate queue must select all pending items: {queue}")

    selected: dict[str, tuple[str, dict[str, Any]]] = {}
    duplicates: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for queue in QUEUE_ORDER:
        for item in snapshots[queue].get("items") or []:
            inbox_id = str(item.get("inbox_id") or "")
            if not inbox_id:
                raise ValueError(f"YouTube aggregate item is missing inbox_id: {queue}")
            if inbox_id in selected:
                duplicates.setdefault(inbox_id, [selected[inbox_id]]).append((queue, item))
            selected[inbox_id] = (queue, item)

    resolutions = []
    for inbox_id, candidates in sorted(duplicates.items()):
        winner_queue, winner = selected[inbox_id]
        resolutions.append(
            {
                "inbox_id": inbox_id,
                "selected_queue": winner_queue,
                "selected_payload_sha256": item_payload_hash(winner),
                "dropped": [
                    {"queue": queue, "payload_sha256": item_payload_hash(item)}
                    for queue, item in candidates
                    if queue != winner_queue
                ],
            }
        )

    entries = [lineage(queue, snapshots[queue]) for queue in QUEUE_ORDER]
    items = [selected[inbox_id][1] for inbox_id in sorted(selected)]
    return {
        "source_id": "youtube_evidence",
        "input_path": "youtube_aggregate://active_video+year_backfill+user_confirmation",
        "input_sha256": composite_sha256(entries),
        "input_size_bytes": sum(int(entry["size_bytes"] or 0) for entry in entries),
        "item_count": len(items),
        "items": items,
        "write_mode": "snapshot_only_default_off",
        "upstream_boundary": "all_pending_youtube_review_queues",
        "selection": {"mode": "all", "source_keys": [item["source_key"] for item in items]},
        "input_lineage": entries,
        "aggregate": {
            "schema_version": 1,
            "complete": True,
            "required_queues": list(QUEUE_ORDER),
            "precedence_high_to_low": list(PRECEDENCE),
            "duplicate_count": len(resolutions),
            "duplicate_resolutions": resolutions,
        },
    }


def require_complete_aggregate(snapshot: dict[str, Any]) -> None:
    if snapshot.get("source_id") != "youtube_evidence":
        raise ValueError("scheduled YouTube write requires source_id youtube_evidence")
    if snapshot.get("selection", {}).get("mode") != "all":
        raise ValueError("scheduled YouTube write requires all pending items")
    aggregate = snapshot.get("aggregate")
    if not isinstance(aggregate, dict) or aggregate.get("complete") is not True:
        raise ValueError("scheduled YouTube write requires a complete aggregate snapshot")
    if aggregate.get("schema_version") != 1:
        raise ValueError("scheduled YouTube write requires aggregate schema version 1")
    if aggregate.get("required_queues") != list(QUEUE_ORDER):
        raise ValueError("scheduled YouTube write requires all YouTube queues")
    if aggregate.get("precedence_high_to_low") != list(PRECEDENCE):
        raise ValueError("scheduled YouTube write requires the audited queue precedence")
    entries = snapshot.get("input_lineage") or []
    if [entry.get("queue") for entry in entries] != list(QUEUE_ORDER):
        raise ValueError("scheduled YouTube write requires complete input lineage")
    for entry in entries:
        sha256 = str(entry.get("sha256") or "")
        if len(sha256) != 64 or any(char not in string.hexdigits for char in sha256):
            raise ValueError("scheduled YouTube write requires valid input lineage hashes")
        if not str(entry.get("path") or ""):
            raise ValueError("scheduled YouTube write requires input lineage paths")
        if not isinstance(entry.get("size_bytes"), int) or entry["size_bytes"] < 0:
            raise ValueError("scheduled YouTube write requires input lineage sizes")
        if not isinstance(entry.get("item_count"), int) or entry["item_count"] < 0:
            raise ValueError("scheduled YouTube write requires input lineage item counts")
    if snapshot.get("input_sha256") != composite_sha256(entries):
        raise ValueError("scheduled YouTube write aggregate input hash does not match lineage")
    if snapshot.get("input_size_bytes") != sum(entry["size_bytes"] for entry in entries):
        raise ValueError("scheduled YouTube write aggregate input size does not match lineage")
    items = snapshot.get("items")
    if not isinstance(items, list) or snapshot.get("item_count") != len(items):
        raise ValueError("scheduled YouTube write aggregate item count is invalid")
    inbox_ids = [str(item.get("inbox_id") or "") for item in items if isinstance(item, dict)]
    if len(inbox_ids) != len(items) or any(not inbox_id for inbox_id in inbox_ids):
        raise ValueError("scheduled YouTube write aggregate items require inbox ids")
    if len(set(inbox_ids)) != len(inbox_ids):
        raise ValueError("scheduled YouTube write aggregate contains duplicate inbox ids")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-input", type=Path, default=ACTIVE_INPUT)
    parser.add_argument("--year-input", type=Path, default=YEAR_INPUT)
    parser.add_argument("--user-input", type=Path, default=USER_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    snapshot = build_aggregate_snapshot(args.active_input, args.year_input, args.user_input)
    require_complete_aggregate(snapshot)
    write_adapted_snapshot(snapshot, args.output)
    print(
        f"YouTube aggregate snapshot: items={snapshot['item_count']} "
        f"duplicates={snapshot['aggregate']['duplicate_count']} -> {args.output}"
    )


if __name__ == "__main__":
    main()
