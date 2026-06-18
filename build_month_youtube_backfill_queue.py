"""Build a month-focused YouTube backfill queue from the yearly queue."""

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


DATA = Path("data")
DEFAULT_QUEUE = DATA / "youtube_year_backfill_queue.json"
DEFAULT_CANDIDATES = DATA / "youtube_year_backfill_candidates.json"
DEFAULT_OUT_JSON = DATA / "june_youtube_backfill_queue.json"
DEFAULT_OUT_MD = DATA / "june_youtube_backfill_queue.md"


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data):
    with Path(path).open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def event_dates(row):
    dates = []
    for key in ["public_date", "public_date_end"]:
        if row.get(key):
            dates.append(row[key])
    dates.extend(row.get("last_seen_dates") or [])
    return list(dict.fromkeys(dates))


def has_month(row, month):
    pattern = re.compile(rf"^\d{{4}}-{month:02d}-\d{{2}}$")
    return any(isinstance(date, str) and pattern.match(date) for date in event_dates(row))


def estimated_search_calls(row):
    return min(len(row.get("search_queries") or []), 2)


def selected_queue_ids(candidates):
    return {
        row.get("queue_id")
        for row in candidates.get("selected_queue_rows") or []
        if row.get("queue_id")
    }


def sort_key(row):
    priority_order = {"high": 0, "medium": 1, "low": 2}
    return (
        priority_order.get(row.get("priority"), 9),
        -row.get("priority_score", 0),
        row.get("target_year", 9999),
        row.get("event_name") or "",
        row.get("venue") or "",
    )


def build_month_queue(queue, candidates, month):
    seen = selected_queue_ids(candidates)
    rows = [
        row
        for row in queue.get("rows") or []
        if row.get("queue_id") not in seen and has_month(row, month)
    ]
    rows.sort(key=sort_key)
    priority_counts = Counter(row.get("priority") for row in rows)
    target_year_counts = Counter(str(row.get("target_year")) for row in rows)
    return {
        "generated_by": "build_month_youtube_backfill_queue.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "queue": str(DEFAULT_QUEUE),
            "candidates": str(DEFAULT_CANDIDATES),
        },
        "month": month,
        "summary": {
            "items": len(rows),
            "priority_counts": dict(sorted(priority_counts.items())),
            "target_year_counts": dict(sorted(target_year_counts.items())),
            "estimated_search_calls": sum(estimated_search_calls(row) for row in rows),
        },
        "rows": rows,
    }


def md_cell(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(data):
    lines = [
        f"# {data['month']}月 YouTube 過去年バックフィルキュー",
        "",
        f"- 生成: {data['generated_at']}",
        f"- items: {data['summary']['items']}",
        f"- estimated_search_calls: {data['summary']['estimated_search_calls']}",
        "",
        "## priority_counts",
        "",
    ]
    for key, value in data["summary"]["priority_counts"].items():
        lines.append(f"- {key}: {value}")
    lines.extend([
        "",
        "## queue",
        "",
        "| priority | score | year | event | venue | dates | reasons |",
        "| --- | ---: | ---: | --- | --- | --- | --- |",
    ])
    for row in data["rows"]:
        dates = ", ".join(event_dates(row))
        reasons = ", ".join(row.get("priority_reasons") or [])
        lines.append(
            f"| {row.get('priority')} | {row.get('priority_score')} | {row.get('target_year')} | "
            f"{md_cell(row.get('event_name'))} | {md_cell(row.get('venue'))} | "
            f"{md_cell(dates)} | {md_cell(reasons)} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", default=str(DEFAULT_QUEUE))
    parser.add_argument("--candidates", default=str(DEFAULT_CANDIDATES))
    parser.add_argument("--month", type=int, default=6)
    parser.add_argument("--out-json", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--out-md", default=str(DEFAULT_OUT_MD))
    args = parser.parse_args()

    queue = load_json(args.queue, {})
    candidates = load_json(args.candidates, {})
    data = build_month_queue(queue, candidates, args.month)
    write_json(args.out_json, data)
    Path(args.out_md).write_text(render_markdown(data), encoding="utf-8")
    print(
        "month youtube backfill queue: "
        f"month={data['month']} items={data['summary']['items']} "
        f"search_calls={data['summary']['estimated_search_calls']}"
    )


if __name__ == "__main__":
    main()
