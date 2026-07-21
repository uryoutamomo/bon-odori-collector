#!/usr/bin/env python3
"""Adapt official-source review candidates into review inbox snapshot items."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from review_inbox_adapters.source_adapter import load_adapted_source, write_adapted_snapshot


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "data" / "official_source_review_candidates.json"
DEFAULT_OUTPUT = ROOT / "data" / "review_inbox_adapted" / "official_source.json"
YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


class OfficialSourceAdapter:
    source_id = "official_source"

    def __init__(self, target_year: int = 2026):
        self.target_year = target_year

    def adapt(self, payload: Any) -> Iterable[Mapping[str, Any]]:
        if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
            raise ValueError("official source review payload requires rows list")
        return [self.adapt_row(row) for row in payload["rows"]]

    def adapt_row(self, row: Any) -> dict[str, Any]:
        if not isinstance(row, dict):
            raise TypeError("official source review rows must be objects")
        source_key = str(row.get("id") or "").strip()
        if not source_key:
            source_key = "|".join(
                str(row.get(field) or "").strip()
                for field in ("source_url", "venue", "event_name")
            ).strip("|")
        if not source_key:
            raise ValueError("official source review row requires id or stable source fields")
        event_year = row_event_year(row)
        time_scope = (
            "historical"
            if event_year is not None and event_year < self.target_year
            else "future"
        )
        title = str(row.get("event_name") or row.get("venue") or row.get("source_url") or "").strip()
        if not title:
            raise ValueError(f"official source review row has no display title: {source_key}")
        priority_score = numeric_score(row.get("suggested_score"))
        return {
            "kind": "official_source",
            "domain": "根拠URL",
            "time_scope": time_scope,
            "priority_label": "P0" if time_scope == "future" else "P2",
            "priority_score": priority_score,
            "title": title,
            "event_name": str(row.get("event_name") or ""),
            "venue": str(row.get("venue") or ""),
            "event_year": event_year,
            "source_key": source_key,
            "source_url": str(row.get("source_url") or ""),
            "recommended_action": "review_official_source",
            "payload": row,
        }


def numeric_score(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def row_event_year(row: dict[str, Any]) -> int | None:
    explicit = row.get("event_year")
    try:
        if explicit is not None and explicit != "":
            return int(explicit)
    except (TypeError, ValueError):
        pass
    for field in ("event_date_text", "event_name", "memo"):
        years = [int(value) for value in YEAR_RE.findall(str(row.get(field) or ""))]
        if years:
            return max(years)
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--target-year", type=int, default=2026)
    args = parser.parse_args()

    snapshot = load_adapted_source(OfficialSourceAdapter(args.target_year), args.input)
    write_adapted_snapshot(snapshot, args.output)
    print(
        f"official source inbox snapshot: items={snapshot['item_count']} "
        f"input_sha256={snapshot['input_sha256']} -> {args.output}"
    )


if __name__ == "__main__":
    main()
