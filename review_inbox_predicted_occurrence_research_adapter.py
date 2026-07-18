#!/usr/bin/env python3
"""Adapt predicted-occurrence research work into review inbox items."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Iterable, Mapping

from review_inbox_source_adapter import load_adapted_source, write_adapted_snapshot


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "data" / "predicted_occurrence_research_queue.json"
DEFAULT_OUTPUT = ROOT / "data" / "review_inbox_adapted" / "predicted_occurrence_research.json"
ALLOWED_ACTIONS = {
    "source_recheck_before_promotion",
    "queue_for_source_recheck",
    "keep_prediction_queue_only",
}


class PredictedOccurrenceResearchAdapter:
    source_id = "predicted_occurrence_research"

    def adapt(self, payload: Any) -> Iterable[Mapping[str, Any]]:
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise ValueError("predicted occurrence research payload requires items list")
        return [self.adapt_item(item) for item in payload["items"]]

    def adapt_item(self, item: Any) -> dict[str, Any]:
        if not isinstance(item, dict):
            raise TypeError("predicted occurrence research items must be objects")
        source_key = str(item.get("predicted_date_id") or "").strip()
        event_name = str(item.get("event_name") or "").strip()
        if not source_key or not event_name:
            raise ValueError("predicted occurrence research item requires id and event_name")
        action = str(item.get("recommended_action") or "").strip()
        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"unsupported predicted occurrence research action: {action}")
        return {
            "kind": "predicted_date",
            "domain": "開催判断",
            "time_scope": "future",
            "priority_label": str(item.get("priority_label") or ""),
            "priority_score": numeric_score(item.get("priority_score")),
            "title": event_name,
            "event_name": event_name,
            "venue": str(item.get("usual_venue") or ""),
            "event_year": integer_or_none(item.get("predicted_year")),
            "source_key": source_key,
            "source_url": str(item.get("source_url") or ""),
            "recommended_action": action,
            "payload": item,
        }


def integer_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def numeric_score(value: Any) -> float | None:
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def build_snapshot(input_path: Path) -> dict[str, Any]:
    snapshot = load_adapted_source(PredictedOccurrenceResearchAdapter(), input_path)
    snapshot["selection"] = {
        "mode": "all",
        "source_keys": [item["source_key"] for item in snapshot["items"]],
    }
    snapshot["write_mode"] = "snapshot_only_default_off"
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    snapshot = build_snapshot(args.input)
    write_adapted_snapshot(snapshot, args.output)
    print(
        f"predicted occurrence research snapshot: items={snapshot['item_count']} "
        f"input_sha256={snapshot['input_sha256']} -> {args.output}"
    )


if __name__ == "__main__":
    main()
