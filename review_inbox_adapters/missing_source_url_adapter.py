#!/usr/bin/env python3
"""Adapt missing-source-URL review rows into pending inbox research items."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Iterable, Mapping

from review_inbox_adapters.source_adapter import load_adapted_source, write_adapted_snapshot


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "data" / "missing_source_url_review.json"
DEFAULT_OUTPUT = ROOT / "data" / "review_inbox_adapted" / "missing_source_url.json"
ACTION_CONFIG = {
    "source_research_required": "research_missing_source_url",
    "ready_source_url_candidate": "stage_source_url_change_request",
}


class MissingSourceUrlAdapter:
    source_id = "missing_source_url"

    def __init__(self, target_year: int = 2026):
        self.target_year = target_year

    def adapt(self, payload: Any) -> Iterable[Mapping[str, Any]]:
        if not isinstance(payload, dict) or not isinstance(payload.get("review"), list):
            raise ValueError("missing source URL payload requires review list")
        return [self.adapt_row(row) for row in payload["review"]]

    def adapt_row(self, row: Any) -> dict[str, Any]:
        if not isinstance(row, dict):
            raise TypeError("missing source URL rows must be objects")
        source_key = str(row.get("occurrence_id") or "").strip()
        event_name = str(row.get("event_name") or "").strip()
        if not source_key or not event_name:
            raise ValueError("missing source URL row requires occurrence_id and event_name")
        action = str(row.get("review_action") or "").strip()
        if action not in ACTION_CONFIG:
            raise ValueError(f"unsupported missing source URL action: {action}")
        event_year = integer_or_none(row.get("event_year"))
        time_scope = (
            "historical"
            if event_year is not None and event_year < self.target_year
            else "future"
        )
        return {
            "kind": "source_url",
            "domain": "根拠URL",
            "time_scope": time_scope,
            "priority_label": "P2" if time_scope == "historical" else "P1",
            "priority_score": None,
            "title": event_name,
            "event_name": event_name,
            "venue": "",
            "event_year": event_year,
            "source_key": source_key,
            "source_url": str(row.get("candidate_source_url") or ""),
            "recommended_action": ACTION_CONFIG[action],
            "payload": row,
        }


def integer_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def build_snapshot(input_path: Path, *, target_year: int = 2026) -> dict[str, Any]:
    snapshot = load_adapted_source(MissingSourceUrlAdapter(target_year), input_path)
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
    parser.add_argument("--target-year", type=int, default=2026)
    args = parser.parse_args()
    snapshot = build_snapshot(args.input, target_year=args.target_year)
    write_adapted_snapshot(snapshot, args.output)
    print(
        f"missing source URL snapshot: items={snapshot['item_count']} "
        f"input_sha256={snapshot['input_sha256']} -> {args.output}"
    )


if __name__ == "__main__":
    main()
