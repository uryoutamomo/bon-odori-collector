#!/usr/bin/env python3
"""Adapt undecided YouTube user-confirmation items into the unified inbox."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from review_inbox_adapters.source_adapter import load_adapted_source, write_adapted_snapshot
from review_inbox_adapters.youtube_adapter import video_id_from_url


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "data" / "youtube_user_confirmation_queue.json"
DEFAULT_OUTPUT = ROOT / "data" / "review_inbox_adapted" / "youtube_user_confirmation.json"
DECISION_ACTIONS = {
    "include_in_main_event_db": "add_song_evidence",
    "allow_registration_from_multiple_youtube_evidence": "add_song_evidence",
    "include_in_current_public_db": "add_song_evidence",
    "start_nationwide_event_db_flow": "needs_research",
    "hold_as_adjacent_dance_event": "hold",
    "hold_for_nationwide_or_adjacent_scope": "hold",
    "keep_as_song_phenomenon_only": "hold",
    "hold_until_official_confirmation": "hold",
    "hold_main_registration_keep_unofficial_evidence_candidate": "hold",
    "hold_for_nationwide_expansion_only": "hold",
    "exclude_from_main_event_db_keep_as_song_phenomenon": "hold",
    "exclude": "reject",
}


class YouTubeUserConfirmationAdapter:
    source_id = "youtube_evidence"

    def adapt(self, payload: Any) -> Iterable[Mapping[str, Any]]:
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise ValueError("YouTube user confirmation payload requires items list")
        items = []
        for row in payload["items"]:
            if not isinstance(row, dict):
                raise TypeError("YouTube user confirmation items must be objects")
            if self.is_decided(row):
                continue
            items.append(self.adapt_row(row))
        return items

    def is_decided(self, row: Mapping[str, Any]) -> bool:
        current = str(row.get("current_decision") or "").strip()
        decided_by = str(row.get("decided_by") or "").strip()
        decided_at = str(row.get("decided_at") or "").strip()
        if current and decided_by and decided_at:
            if current not in DECISION_ACTIONS:
                raise ValueError(f"unsupported decided YouTube confirmation: {current}")
            return True
        if current or decided_by or decided_at:
            raise ValueError("partial YouTube confirmation decision is not allowed")
        return False

    def adapt_row(self, row: Mapping[str, Any]) -> dict[str, Any]:
        recommendation = str(row.get("recommended_decision") or "").strip()
        if recommendation not in DECISION_ACTIONS:
            raise ValueError(
                f"unsupported YouTube confirmation recommendation: {recommendation or 'missing'}"
            )
        options = row.get("options")
        if not isinstance(options, list) or not options:
            raise ValueError("pending YouTube confirmation requires finite options")
        unsupported = sorted(
            str(option) for option in options if str(option) not in DECISION_ACTIONS
        )
        if unsupported:
            raise ValueError("unsupported YouTube confirmation options: " + ", ".join(unsupported))
        source_url = str(row.get("video_url") or "").strip()
        video_id = video_id_from_url(source_url)
        if not video_id:
            raise ValueError("pending YouTube confirmation requires a YouTube video URL")
        supplied_video_id = str(row.get("video_id") or "").strip()
        if supplied_video_id and supplied_video_id != video_id:
            raise ValueError("YouTube confirmation video_id does not match video_url")
        year = event_year(row)
        if year is None:
            raise ValueError("pending YouTube confirmation requires a target year")
        title = str(row.get("label") or row.get("id") or "").strip()
        if not title:
            raise ValueError("pending YouTube confirmation requires a label")
        return {
            "kind": "youtube_evidence",
            "domain": "YouTube",
            "time_scope": "historical",
            "priority_label": "P2",
            "priority_score": None,
            "title": title,
            "event_name": title,
            "venue": str(row.get("venue") or "").strip(),
            "event_year": year,
            "source_key": f"video:{video_id}|year:{year}",
            "source_url": f"https://www.youtube.com/watch?v={video_id}",
            "recommended_action": DECISION_ACTIONS[recommendation],
            "payload": {
                **dict(row),
                "origin_queue": "youtube_user_confirmation",
                "video_id": video_id,
            },
        }


def event_year(row: Mapping[str, Any]) -> int | None:
    for value in (row.get("detected_event_date"), row.get("id"), row.get("label")):
        match = re.search(r"\b(20\d{2})\b", str(value or ""))
        if match:
            return int(match.group(1))
    return None


def build_snapshot(input_path: Path) -> dict[str, Any]:
    snapshot = load_adapted_source(YouTubeUserConfirmationAdapter(), input_path)
    snapshot["write_mode"] = "snapshot_only_default_off"
    snapshot["upstream_boundary"] = "undecided_user_confirmation_items_only"
    snapshot["selection"] = {
        "mode": "all",
        "source_keys": [item["source_key"] for item in snapshot["items"]],
    }
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    snapshot = build_snapshot(args.input)
    write_adapted_snapshot(snapshot, args.output)
    print(
        f"YouTube user confirmation snapshot: items={snapshot['item_count']} "
        f"input_sha256={snapshot['input_sha256']} -> {args.output}"
    )


if __name__ == "__main__":
    main()
