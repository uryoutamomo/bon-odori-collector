#!/usr/bin/env python3
"""Adapt registered-event investigation tasks into review inbox snapshot items.

This module is intentionally side-effect free apart from writing an adapter
snapshot requested by the CLI. It does not open the Master RDB, update legacy
review files, stage decisions, or enable dual-write.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Iterable, Mapping

from review_inbox_adapters.source_adapter import load_adapted_source, write_adapted_snapshot


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "data" / "registered_event_investigation_queue.json"
DEFAULT_OUTPUT = ROOT / "data" / "review_inbox_adapted" / "registered_event_investigation.json"
SHIROKANE_CANARY_SOURCE_KEY = "evtinv_d7b5f534c8b3ddd8"


class RegisteredEventInvestigationAdapter:
    source_id = "registered_event_investigation"

    def __init__(self, source_keys: Iterable[str] | None = None):
        selected = {str(value).strip() for value in (source_keys or []) if str(value).strip()}
        self.source_keys = frozenset(selected)

    def adapt(self, payload: Any) -> Iterable[Mapping[str, Any]]:
        if not isinstance(payload, dict) or not isinstance(payload.get("tasks"), list):
            raise ValueError("registered event investigation payload requires tasks list")
        items = [self.adapt_task(task) for task in payload["tasks"]]
        if not self.source_keys:
            return items
        selected = [item for item in items if item["source_key"] in self.source_keys]
        missing = sorted(self.source_keys - {item["source_key"] for item in selected})
        if missing:
            raise ValueError(
                "registered event investigation selection is missing source keys: "
                + ", ".join(missing)
            )
        return selected

    def adapt_task(self, task: Any) -> dict[str, Any]:
        if not isinstance(task, dict):
            raise TypeError("registered event investigation tasks must be objects")
        source_key = str(task.get("task_id") or "").strip()
        if not source_key:
            raise ValueError("registered event investigation task requires task_id")
        event_name = str(task.get("event_name") or "").strip()
        venue = first_text(task.get("known_venue_names"))
        if not event_name:
            raise ValueError(f"registered event investigation task has no event_name: {source_key}")
        return {
            "kind": task_kind(task),
            "domain": "開催判断",
            "time_scope": task_time_scope(task),
            "priority_label": str(task.get("priority_label") or ""),
            "priority_score": numeric_score(task.get("priority_score")),
            "title": event_name,
            "event_name": event_name,
            "venue": venue,
            "event_year": integer_or_none(task.get("event_year")),
            "source_key": source_key,
            "source_url": str(task.get("source_url") or ""),
            "recommended_action": str(task.get("recommended_action") or ""),
            "payload": task,
        }


def task_kind(task: Mapping[str, Any]) -> str:
    if task.get("needs_name_review") or task.get("needs_occurrence_split"):
        return "occurrence_creation"
    if task.get("missing_venue"):
        return "venue_review"
    if task.get("missing_date"):
        return "current_year_confirmation"
    return "occurrence_creation"


def task_time_scope(task: Mapping[str, Any]) -> str:
    if str(task.get("scope") or "") == "primary_unconfirmed":
        return "future"
    year = integer_or_none(task.get("event_year"))
    return "historical" if year is not None and year < 2026 else "future"


def first_text(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    return next((str(item).strip() for item in value if str(item).strip()), "")


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


def build_snapshot(input_path: Path, *, canary: bool = False) -> dict[str, Any]:
    source_keys = [SHIROKANE_CANARY_SOURCE_KEY] if canary else []
    snapshot = load_adapted_source(
        RegisteredEventInvestigationAdapter(source_keys),
        input_path,
    )
    snapshot["selection"] = {
        "mode": "canary" if canary else "all",
        "source_keys": source_keys,
    }
    snapshot["write_mode"] = "snapshot_only_default_off"
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--canary",
        action="store_true",
        help="select only the fixed Shirokane deferred item; still records the full input hash",
    )
    args = parser.parse_args()

    snapshot = build_snapshot(args.input, canary=args.canary)
    write_adapted_snapshot(snapshot, args.output)
    print(
        "registered investigation inbox snapshot: "
        f"mode={snapshot['selection']['mode']} items={snapshot['item_count']} "
        f"input_sha256={snapshot['input_sha256']} -> {args.output}"
    )


if __name__ == "__main__":
    main()
