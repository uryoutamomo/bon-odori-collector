#!/usr/bin/env python3
"""Summarize YouTube backfill threshold calibration candidates."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


DEFAULT_PLAN = Path("data/event_occurrence_backfill_plan.json")
DEFAULT_OUT_JSON = Path("data/backfill_threshold_calibration.json")
DEFAULT_OUT_MD = Path("data/backfill_threshold_calibration.md")


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def bucket(row: dict) -> str:
    videos = int(row.get("source_video_count") or 0)
    channels = len(row.get("source_channels") or [])
    songs = len(row.get("songs") or [])
    if videos >= 2 and channels >= 2:
        return "multi_video_multi_channel"
    if videos >= 3 and songs >= 3:
        return "multi_video_song_rich"
    if videos >= 2 and songs >= 3:
        return "multi_video_song_context"
    if videos >= 2:
        return "multi_video"
    if songs >= 3:
        return "single_video_song_context"
    return "single_weak"


def sample_row(row: dict) -> dict:
    video = next(iter(row.get("source_videos") or []), {})
    return {
        "observation_id": row.get("observation_id"),
        "event_name": row.get("event_name"),
        "venue": row.get("venue"),
        "year": row.get("year"),
        "date_start": row.get("date_start"),
        "date_end": row.get("date_end"),
        "confidence": row.get("confidence"),
        "source_video_count": row.get("source_video_count") or 0,
        "source_channel_count": len(row.get("source_channels") or []),
        "song_count": len(row.get("songs") or []),
        "bucket": bucket(row),
        "sample_title": video.get("title") or "",
        "sample_url": video.get("url") or "",
    }


def build(plan: dict) -> dict:
    accepted = list(plan.get("observations") or [])
    excluded = list(plan.get("excluded_low_observations") or [])
    all_rows = accepted + excluded
    by_confidence = Counter(row.get("confidence") or "unknown" for row in all_rows)
    excluded_by_bucket = Counter(bucket(row) for row in excluded)
    accepted_by_bucket = Counter(bucket(row) for row in accepted)
    promote_candidates = [
        row
        for row in excluded
        if bucket(row) in {"multi_video_multi_channel", "multi_video_song_rich", "multi_video_song_context"}
    ]
    hold_candidates = [
        row
        for row in excluded
        if bucket(row) in {"multi_video", "single_video_song_context", "single_weak"}
    ]
    return {
        "generated_by": "analyze_backfill_thresholds.py",
        "source": str(DEFAULT_PLAN),
        "summary": {
            "accepted_observations": len(accepted),
            "excluded_low_observations": len(excluded),
            "all_observations": len(all_rows),
            "by_confidence": dict(sorted(by_confidence.items())),
            "accepted_by_bucket": dict(sorted(accepted_by_bucket.items())),
            "excluded_by_bucket": dict(sorted(excluded_by_bucket.items())),
            "promote_candidate_count": len(promote_candidates),
            "hold_candidate_count": len(hold_candidates),
        },
        "recommendation": {
            "safe_threshold_change": "none",
            "reason": (
                "Keep automatic promotion unchanged. Review excluded low rows in the "
                "multi_video_* buckets first; single-video rows should stay manual."
            ),
        },
        "promote_candidates": [sample_row(row) for row in promote_candidates[:50]],
        "hold_samples": [sample_row(row) for row in hold_candidates[:30]],
    }


def md_cell(value) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(data: dict) -> str:
    summary = data["summary"]
    lines = [
        "# 裏取りキューv2 閾値較正メモ",
        "",
        f"- source: `{data['source']}`",
        f"- accepted_observations: {summary['accepted_observations']}",
        f"- excluded_low_observations: {summary['excluded_low_observations']}",
        f"- promote_candidate_count: {summary['promote_candidate_count']}",
        f"- recommendation: {data['recommendation']['safe_threshold_change']}",
        f"- reason: {data['recommendation']['reason']}",
        "",
        "## bucket counts",
        "",
        "| bucket | accepted | excluded_low |",
        "| --- | ---: | ---: |",
    ]
    buckets = sorted(set(summary["accepted_by_bucket"]) | set(summary["excluded_by_bucket"]))
    for name in buckets:
        lines.append(
            f"| {name} | {summary['accepted_by_bucket'].get(name, 0)} | "
            f"{summary['excluded_by_bucket'].get(name, 0)} |"
        )
    lines.extend([
        "",
        "## review-first candidates",
        "",
        "| bucket | videos | channels | songs | year | date | event | venue | sample |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
    ])
    for row in data["promote_candidates"]:
        date = row["date_start"] if row["date_start"] == row["date_end"] else f"{row['date_start']}〜{row['date_end']}"
        sample = row["sample_title"]
        if row["sample_url"]:
            sample = f"{sample} {row['sample_url']}".strip()
        lines.append(
            f"| {row['bucket']} | {row['source_video_count']} | {row['source_channel_count']} | "
            f"{row['song_count']} | {row['year']} | {md_cell(date)} | {md_cell(row['event_name'])} | "
            f"{md_cell(row['venue'])} | {md_cell(sample)} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    args = parser.parse_args()

    data = build(load_json(args.plan))
    data["source"] = str(args.plan)
    args.out_json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.out_md.write_text(render_markdown(data), encoding="utf-8")
    print(
        "backfill threshold calibration: "
        f"excluded={data['summary']['excluded_low_observations']} "
        f"review_first={data['summary']['promote_candidate_count']} -> {args.out_md}"
    )


if __name__ == "__main__":
    main()
