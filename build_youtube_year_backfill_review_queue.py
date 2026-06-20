#!/usr/bin/env python3
"""Group status=review YouTube year-backfill candidates for human decisions."""

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


DATA = Path("data")
CANDIDATES = DATA / "youtube_year_backfill_candidates.json"
DECISION_FILES = [
    DATA / "youtube_year_backfill_review_decisions_koto_2026-06-20.json",
    DATA / "youtube_year_backfill_review_decisions_oto_2026-06-20.json",
]
OUT_JSON = DATA / "youtube_year_backfill_review_queue.json"
OUT_MD = DATA / "youtube_year_backfill_review_queue.md"


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def norm(value):
    return re.sub(r"\s+", "", str(value or "")).casefold()


def group_key(row):
    return (norm(row.get("event_name")), norm(row.get("venue")), int(row.get("target_year") or 0))


def decision_index(paths):
    index = {}
    for path in paths:
        payload = load_json(path, {})
        for row in payload.get("decisions") or []:
            key = (norm(row.get("event_name")), norm(row.get("venue")), int(row.get("target_year") or 0))
            index[key] = {
                "decision": row.get("decision") or "",
                "reason": row.get("reason") or "",
                "source": str(path),
            }
    return index


def years_in_text(text):
    return sorted({int(value) for value in re.findall(r"20\d{2}", str(text or ""))})


def has_other_year(row, target_year):
    years = years_in_text(row.get("title") or "")
    return bool(years and target_year not in years)


def recommended_action(rows, existing):
    if existing:
        return "already_decided"
    target_year = int(rows[0].get("target_year") or 0)
    if any(has_other_year(row, target_year) for row in rows):
        return "review_year_mismatch"
    song_count = sum(int(row.get("setlist_count") or 0) for row in rows)
    if song_count >= 10:
        return "song_evidence_candidate_needs_event_date"
    if len(rows) >= 2 and max(int(row.get("score") or 0) for row in rows) >= 65:
        return "merge_to_existing_candidate"
    if len(rows) == 1 and max(int(row.get("score") or 0) for row in rows) >= 65:
        return "single_video_hold"
    return "hold_or_reject"


def build(candidates, decision_paths):
    decisions = decision_index(decision_paths)
    grouped = defaultdict(list)
    for row in candidates.get("candidates") or []:
        if row.get("status") == "review":
            grouped[group_key(row)].append(row)

    groups = []
    for key, rows in sorted(grouped.items(), key=lambda item: (item[0][2], rows_sort_label(item[1]))):
        rows = sorted(rows, key=lambda row: (-(row.get("score") or 0), row.get("title") or ""))
        existing = decisions.get(key)
        group = {
            "event_name": rows[0].get("event_name") or "",
            "venue": rows[0].get("venue") or "",
            "target_year": rows[0].get("target_year"),
            "video_count": len(rows),
            "song_candidate_count": sum(int(row.get("setlist_count") or 0) for row in rows),
            "max_score": max(int(row.get("score") or 0) for row in rows),
            "channels": sorted({row.get("channel_title") for row in rows if row.get("channel_title")}),
            "detected_dates": sorted({row.get("detected_event_date") for row in rows if row.get("detected_event_date")}),
            "candidate_action": recommended_action(rows, existing),
            "existing_decision": existing,
            "videos": [
                {
                    "title": row.get("title") or "",
                    "url": row.get("video_url") or "",
                    "score": row.get("score") or 0,
                    "setlist_count": row.get("setlist_count") or 0,
                    "published_at": row.get("published_at") or "",
                    "query": row.get("query") or "",
                }
                for row in rows
            ],
        }
        groups.append(group)

    counts = Counter(group["candidate_action"] for group in groups)
    undecided = [group for group in groups if group["candidate_action"] != "already_decided"]
    return {
        "generated_by": "build_youtube_year_backfill_review_queue.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(CANDIDATES),
        "decision_sources": [str(path) for path in decision_paths],
        "summary": {
            "group_count": len(groups),
            "video_count": sum(group["video_count"] for group in groups),
            "undecided_group_count": len(undecided),
            "undecided_video_count": sum(group["video_count"] for group in undecided),
            "action_counts": dict(sorted(counts.items())),
        },
        "groups": groups,
    }


def rows_sort_label(rows):
    row = rows[0]
    return (row.get("event_name") or "", row.get("venue") or "")


def md_cell(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(data):
    lines = [
        "# YouTube年バックフィル review キュー",
        "",
        f"- generated_at: {data['generated_at']}",
        f"- groups: {data['summary']['group_count']}",
        f"- undecided_groups: {data['summary']['undecided_group_count']}",
        f"- videos: {data['summary']['video_count']}",
        f"- action_counts: {data['summary']['action_counts']}",
        "",
        "| action | existing | year | videos | songs | score | event | venue | sample |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for group in data["groups"]:
        existing = group.get("existing_decision") or {}
        sample = ""
        if group.get("videos"):
            video = group["videos"][0]
            sample = f"{video.get('title') or ''} {video.get('url') or ''}".strip()
        lines.append(
            f"| {group['candidate_action']} | {existing.get('decision') or ''} | "
            f"{group['target_year']} | {group['video_count']} | {group['song_candidate_count']} | "
            f"{group['max_score']} | {md_cell(group['event_name'])} | {md_cell(group['venue'])} | "
            f"{md_cell(sample)} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, default=CANDIDATES)
    parser.add_argument("--decision", type=Path, action="append", default=DECISION_FILES)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    args = parser.parse_args()

    data = build(load_json(args.candidates, {}), args.decision)
    write_json(args.out_json, data)
    args.out_md.write_text(render_markdown(data), encoding="utf-8")
    print(
        "youtube year backfill review queue: "
        f"groups={data['summary']['group_count']} "
        f"undecided={data['summary']['undecided_group_count']} -> {args.out_md}"
    )


if __name__ == "__main__":
    main()
