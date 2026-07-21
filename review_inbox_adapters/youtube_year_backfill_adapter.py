#!/usr/bin/env python3
"""Adapt undecided YouTube year-backfill groups into video evidence items."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Iterable, Mapping

from review_inbox_adapters.source_adapter import load_adapted_source, write_adapted_snapshot
from review_inbox_adapters.youtube_adapter import video_id_from_url


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "data" / "youtube_year_backfill_review_queue.json"
DEFAULT_OUTPUT = ROOT / "data" / "review_inbox_adapted" / "youtube_year_backfill.json"
ACTION_CONFIG = {
    "review_year_mismatch": "needs_research",
    "song_evidence_candidate_needs_event_date": "needs_research",
    "merge_to_existing_candidate": "add_song_evidence",
    "single_video_hold": "hold",
    "hold_or_reject": "hold",
}


class YouTubeYearBackfillAdapter:
    source_id = "youtube_evidence"

    def adapt(self, payload: Any) -> Iterable[Mapping[str, Any]]:
        if not isinstance(payload, dict) or not isinstance(payload.get("groups"), list):
            raise ValueError("YouTube year backfill payload requires groups list")
        items = []
        for group in payload["groups"]:
            if not isinstance(group, dict):
                raise TypeError("YouTube year backfill groups must be objects")
            action = str(group.get("candidate_action") or "").strip()
            existing = group.get("existing_decision")
            if action == "already_decided":
                if not isinstance(existing, dict) or not str(existing.get("decision") or "").strip():
                    raise ValueError("already_decided YouTube year group requires existing_decision")
                continue
            if existing:
                raise ValueError("undecided YouTube year group cannot contain existing_decision")
            if action not in ACTION_CONFIG:
                raise ValueError(f"unsupported YouTube year backfill action: {action or 'missing'}")
            videos = group.get("videos")
            if not isinstance(videos, list) or not videos:
                raise ValueError("undecided YouTube year group requires videos")
            items.extend(self.adapt_video(group, video, action) for video in videos)
        return items

    def adapt_video(self, group: Mapping[str, Any], video: Any, action: str) -> dict[str, Any]:
        if not isinstance(video, dict):
            raise TypeError("YouTube year backfill videos must be objects")
        url = str(video.get("url") or "").strip()
        video_id = video_id_from_url(url)
        if not video_id:
            raise ValueError("YouTube year backfill video requires a YouTube URL")
        try:
            year = int(group.get("target_year"))
        except (TypeError, ValueError) as exc:
            raise ValueError("YouTube year backfill group requires target_year") from exc
        if year < 2000 or year > 2100:
            raise ValueError(f"unsupported YouTube target year: {year}")
        event_name = str(group.get("event_name") or "").strip()
        if not event_name:
            raise ValueError("YouTube year backfill group requires event_name")
        title = str(video.get("title") or event_name).strip()
        return {
            "kind": "youtube_evidence",
            "domain": "YouTube",
            "time_scope": "historical",
            "priority_label": "P2",
            "priority_score": integer_or_none(video.get("score")),
            "title": title,
            "event_name": event_name,
            "venue": str(group.get("venue") or "").strip(),
            "event_year": year,
            "source_key": f"video:{video_id}|year:{year}",
            "source_url": f"https://www.youtube.com/watch?v={video_id}",
            "recommended_action": ACTION_CONFIG[action],
            "payload": {
                "origin_queue": "youtube_year_backfill_review",
                "video_id": video_id,
                "candidate_action": action,
                "group": dict(group),
                "video": dict(video),
            },
        }


def integer_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def build_snapshot(input_path: Path) -> dict[str, Any]:
    snapshot = load_adapted_source(YouTubeYearBackfillAdapter(), input_path)
    snapshot["write_mode"] = "snapshot_only_default_off"
    snapshot["upstream_boundary"] = "undecided_year_backfill_groups_only"
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
        f"YouTube year backfill snapshot: items={snapshot['item_count']} "
        f"input_sha256={snapshot['input_sha256']} -> {args.output}"
    )


if __name__ == "__main__":
    main()
