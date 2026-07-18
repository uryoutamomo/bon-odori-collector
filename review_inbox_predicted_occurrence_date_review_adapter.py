#!/usr/bin/env python3
"""Adapt predicted-occurrence date review rows into separate inbox items."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Iterable, Mapping

from review_inbox_source_adapter import load_adapted_source, write_adapted_snapshot


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "data" / "predicted_occurrence_date_review.json"
DEFAULT_OUTPUT = ROOT / "data" / "review_inbox_adapted" / "predicted_occurrence_date_review.json"
ACTION_CONFIG = {
    "keep_prediction_queue": ("P1", "review_prediction_queue"),
    "already_matches_curated": ("P2", "verify_prediction_curated_match"),
    "already_superseded_by_curated": ("P2", "verify_prediction_supersession"),
    "mark_matches_curated": ("P1", "verify_prediction_curated_match"),
    "mark_superseded_by_curated": ("P1", "verify_prediction_supersession"),
}


class PredictedOccurrenceDateReviewAdapter:
    source_id = "predicted_occurrence_date_review"

    def adapt(self, payload: Any) -> Iterable[Mapping[str, Any]]:
        if not isinstance(payload, dict) or not isinstance(payload.get("review"), list):
            raise ValueError("predicted occurrence date review payload requires review list")
        return [self.adapt_row(row) for row in payload["review"]]

    def adapt_row(self, row: Any) -> dict[str, Any]:
        if not isinstance(row, dict) or not isinstance(row.get("predicted"), dict):
            raise TypeError("predicted occurrence date review rows require predicted object")
        predicted = row["predicted"]
        source_key = str(row.get("predicted_date_id") or "").strip()
        event_name = str(row.get("event_name") or predicted.get("target_event_name") or "").strip()
        if not source_key or not event_name:
            raise ValueError("predicted occurrence date review row requires id and event_name")
        action = str(row.get("review_action") or "").strip()
        if action not in ACTION_CONFIG:
            raise ValueError(f"unsupported predicted occurrence date review action: {action}")
        priority_label, recommended_action = ACTION_CONFIG[action]
        return {
            "kind": "predicted_date",
            "domain": "開催判断",
            "time_scope": "future",
            "priority_label": priority_label,
            "priority_score": numeric_score(predicted.get("score")),
            "title": event_name,
            "event_name": event_name,
            "venue": str(predicted.get("usual_venue") or ""),
            "event_year": integer_or_none(predicted.get("predicted_year")),
            "source_key": source_key,
            "source_url": "",
            "recommended_action": recommended_action,
            "payload": row,
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
    snapshot = load_adapted_source(PredictedOccurrenceDateReviewAdapter(), input_path)
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
        f"predicted occurrence date review snapshot: items={snapshot['item_count']} "
        f"input_sha256={snapshot['input_sha256']} -> {args.output}"
    )


if __name__ == "__main__":
    main()
