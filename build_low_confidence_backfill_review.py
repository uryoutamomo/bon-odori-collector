"""Render low-confidence YouTube backfill observations for manual review."""

import argparse
import json
from pathlib import Path


DATA = Path("data")
PLAN = DATA / "event_occurrence_backfill_plan.json"
OUT = DATA / "low_confidence_backfill_review.md"


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def md_cell(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def likely_action(row):
    if row["source_video_count"] >= 2 and row.get("songs"):
        return "review_promote"
    return "hold"


def render(plan):
    rows = plan.get("excluded_low_observations") or []
    lines = [
        "# 低信頼バックフィル候補レビュー",
        "",
        f"- source: {plan.get('source') or ''}",
        f"- rows: {len(rows)}",
        "",
        "| action | year | date | event | venue | videos | channels | songs | sample |",
        "| --- | ---: | --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in sorted(rows, key=lambda item: (item["year"], item["event_name"], item["date_start"])):
        sample = ""
        if row.get("source_videos"):
            video = row["source_videos"][0]
            sample = f"{video.get('title') or ''} {video.get('url') or ''}".strip()
        date = row["date_start"] if row["date_start"] == row["date_end"] else f"{row['date_start']}〜{row['date_end']}"
        lines.append(
            f"| {likely_action(row)} | {row['year']} | {date} | {md_cell(row['event_name'])} | "
            f"{md_cell(row['venue'])} | {row['source_video_count']} | {len(row.get('source_channels') or [])} | "
            f"{len(row.get('songs') or [])} | {md_cell(sample)} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default=str(PLAN))
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    plan = load_json(args.plan, {})
    Path(args.out).write_text(render(plan), encoding="utf-8")
    print(f"low confidence backfill review: rows={len(plan.get('excluded_low_observations') or [])} -> {args.out}")


if __name__ == "__main__":
    main()
