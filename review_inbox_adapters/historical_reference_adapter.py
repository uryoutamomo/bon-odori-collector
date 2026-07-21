#!/usr/bin/env python3
"""Adapt current-identity historical candidates into review-only inbox rows."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Iterable, Mapping

from review_inbox_adapters.source_adapter import load_adapted_source, write_adapted_snapshot


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "data" / "review_inbox_inputs" / "historical_reference_current_identity.json"
DEFAULT_OUTPUT = ROOT / "data" / "review_inbox_adapted" / "historical_reference.json"
ACTION_CONFIG = {
    "auto_promote_historical_reference": "review_historical_reference",
    "manual_review_multi_year_history": "research_multi_year_history",
    "manual_predicted_date_review": "review_prediction_queue",
}


class HistoricalReferenceAdapter:
    source_id = "historical_reference"

    def adapt(self, payload: Any) -> Iterable[Mapping[str, Any]]:
        if not isinstance(payload, dict) or not isinstance(payload.get("candidates"), list):
            raise ValueError("historical reference payload requires candidates list")
        selection = payload.get("selection")
        if not isinstance(selection, dict) or selection.get("mode") != "current_identity":
            raise ValueError("historical reference payload requires current_identity selection")
        return [self.adapt_candidate(candidate) for candidate in payload["candidates"]]

    def adapt_candidate(self, candidate: Any) -> dict[str, Any]:
        if not isinstance(candidate, dict):
            raise TypeError("historical reference candidates must be objects")
        source_key = str(candidate.get("target_occurrence_id") or "").strip()
        event_name = str(
            candidate.get("target_event_name")
            or candidate.get("occurrence_event_name")
            or ""
        ).strip()
        target_series_id = str(candidate.get("target_series_id") or "").strip()
        occurrence_series_id = str(candidate.get("occurrence_series_id") or "").strip()
        if not source_key or not target_series_id or not event_name:
            raise ValueError(
                "historical reference candidate requires target series, occurrence, and event name"
            )
        identity = candidate.get("current_identity")
        if not isinstance(identity, dict) or not all(
            identity.get(field)
            for field in (
                "series_resolved",
                "occurrence_resolved",
                "occurrence_series_matches",
            )
        ):
            raise ValueError("historical reference candidate is not current-identity resolved")
        if occurrence_series_id != target_series_id:
            raise ValueError("historical reference occurrence does not belong to target series")
        action = str(candidate.get("recommended_action") or "").strip()
        if action not in ACTION_CONFIG:
            raise ValueError(f"unsupported historical reference action: {action}")
        return {
            "kind": "historical_reference",
            "domain": "過去実績",
            "time_scope": "reference",
            "priority_label": priority_label(candidate),
            "priority_score": numeric_score(candidate.get("match_score")),
            "title": event_name,
            "event_name": event_name,
            "venue": str(candidate.get("venue") or ""),
            "event_year": integer_or_none(candidate.get("event_year")),
            "source_key": source_key,
            "source_url": str(candidate.get("source_url") or ""),
            "recommended_action": ACTION_CONFIG[action],
            "payload": candidate,
        }


def priority_label(candidate: Mapping[str, Any]) -> str:
    action = str(candidate.get("recommended_action") or "")
    if action == "manual_predicted_date_review":
        return "P1"
    return "P1" if str(candidate.get("promotion_confidence") or "") != "high" else "P2"


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
    snapshot = load_adapted_source(HistoricalReferenceAdapter(), input_path)
    snapshot["selection"] = {
        "mode": "all",
        "source_keys": [item["source_key"] for item in snapshot["items"]],
    }
    snapshot["source_database_sha256"] = source_database_sha256(input_path)
    snapshot["write_mode"] = "snapshot_only_default_off"
    return snapshot


def source_database_sha256(input_path: Path) -> str:
    import json

    payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
    source = payload.get("source") if isinstance(payload, dict) else None
    checksum = str((source or {}).get("database_sha256") or "")
    if len(checksum) != 64:
        raise ValueError("historical reference input requires source database SHA-256")
    return checksum


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    snapshot = build_snapshot(args.input)
    write_adapted_snapshot(snapshot, args.output)
    print(
        f"historical reference snapshot: items={snapshot['item_count']} "
        f"input_sha256={snapshot['input_sha256']} -> {args.output}"
    )


if __name__ == "__main__":
    main()
