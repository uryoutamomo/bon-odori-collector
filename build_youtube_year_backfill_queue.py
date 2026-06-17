"""Build a YouTube backfill queue for past event occurrence years.

The queue is intentionally a research plan, not evidence. It lists event/year
pairs where past YouTube searches can improve the event occurrence model.
"""

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from build_event_occurrence_observations import norm, series_key


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DEFAULT_PUBLIC_EVENTS = DATA / "public" / "events_public.json"
DEFAULT_OBSERVATIONS = DATA / "event_occurrence_observations.json"
DEFAULT_OUT_JSON = DATA / "youtube_year_backfill_queue.json"
DEFAULT_OUT_MD = DATA / "youtube_year_backfill_queue.md"
DEFAULT_TARGET_YEARS = "2024,2023"


def read_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data):
    with Path(path).open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def compact(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def digest(*parts, length=16):
    raw = "\0".join(str(part or "") for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def parse_target_years(value):
    years = []
    for raw in str(value or "").split(","):
        raw = raw.strip()
        if raw:
            years.append(int(raw))
    return years


def source_url_count(event):
    return len([row for row in event.get("source_urls") or [] if row.get("url")])


def public_event_years(event):
    years = set()
    for key in ["date", "date_end"]:
        date = event.get(key)
        if isinstance(date, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            years.add(int(date[:4]))
    for year in event.get("last_seen_year"),:
        if isinstance(year, int):
            years.add(year)
    return years


def observations_index(observations):
    by_series = defaultdict(list)
    for row in observations:
        by_series[row["series_key"]].append(row)
    return by_series


def priority_for(event, observed_rows, target_year):
    score = 0
    reasons = []
    observed_years = {row["year"] for row in observed_rows}
    if observed_rows:
        score += 50
        reasons.append("youtube_observed_series")
    if 2025 in observed_years or 2026 in observed_years:
        score += 20
        reasons.append("recent_youtube_observation")
    urls = source_url_count(event)
    if urls:
        score += min(20, urls * 8)
        reasons.append("has_source_url")
    recurrence_score = event.get("recurrence_score") or 0
    if recurrence_score >= 0.8:
        score += 15
        reasons.append("high_recurrence_score")
    elif recurrence_score >= 0.5:
        score += 8
        reasons.append("medium_recurrence_score")
    if event.get("songs") or event.get("song_occurrence"):
        score += 8
        reasons.append("has_song_data")
    if target_year in public_event_years(event):
        score -= 40
        reasons.append("target_year_already_in_public_event")
    score += min(10, sum(row.get("source_video_count") or 0 for row in observed_rows) // 20)
    if score >= 85:
        tier = "high"
    elif score >= 55:
        tier = "medium"
    else:
        tier = "low"
    return score, tier, reasons


def search_queries(event_name, venue, area, year):
    adjusted_event_name = event_name_for_target_year(event_name, year)
    parts = [adjusted_event_name, venue, area]
    base = " ".join(compact(part) for part in parts if compact(part))
    queries = [
        f"{base} {year} 盆踊り",
        f"{compact(adjusted_event_name)} {year} YouTube 盆踊り",
    ]
    if venue:
        queries.append(f"{compact(venue)} {year} 盆踊り")
    return list(dict.fromkeys(queries))


def event_name_for_target_year(event_name, target_year):
    name = compact(event_name)
    if re.search(r"20\d{2}", name):
        return re.sub(r"20\d{2}", str(target_year), name)
    return name


def public_event_seed_score(event):
    return (
        source_url_count(event) * 10
        + int((event.get("recurrence_score") or 0) * 10)
        + len(event.get("songs") or [])
    )


def build_queue(public_events, observations_payload, target_years):
    observations = observations_payload.get("observations") or []
    by_series = observations_index(observations)
    year_order = {year: index for index, year in enumerate(target_years)}
    rows = []
    seen = set()

    for event in sorted(public_events, key=public_event_seed_score, reverse=True):
        event_name = compact(event.get("name"))
        venue = compact(event.get("venue"))
        if not event_name or not venue:
            continue
        skey = series_key(event_name, venue)
        observed_rows = by_series.get(skey) or []
        observed_years = sorted({row["year"] for row in observed_rows})
        for target_year in target_years:
            dedupe_key = (norm(event_name), norm(venue), target_year)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            if target_year in observed_years:
                continue
            score, tier, reasons = priority_for(event, observed_rows, target_year)
            rows.append({
                "queue_id": "youtube-year-backfill:" + digest(event_name, venue, target_year),
                "target_year": target_year,
                "priority_score": score,
                "priority": tier,
                "event_name": event_name,
                "venue": venue,
                "area": compact(event.get("area")),
                "series_key": skey,
                "observed_years": observed_years,
                "observed_source_video_count": sum(row.get("source_video_count") or 0 for row in observed_rows),
                "public_date": event.get("date") or "",
                "public_date_end": event.get("date_end") or "",
                "last_seen_year": event.get("last_seen_year"),
                "last_seen_dates": event.get("last_seen_dates") or [],
                "recurrence_label": event.get("recurrence_label") or "",
                "recurrence_score": event.get("recurrence_score") or 0,
                "source_url_count": source_url_count(event),
                "song_count": len(event.get("songs") or []),
                "priority_reasons": reasons,
                "search_queries": search_queries(event_name, venue, event.get("area"), target_year),
                "next_action": "YouTubeで過去年動画を検索し、開催日・曜日・曲目を観測データへ追加する",
            })

    rows.sort(key=lambda row: (-row["priority_score"], year_order.get(row["target_year"], 999), row["event_name"], row["venue"]))
    counts = Counter(row["priority"] for row in rows)
    years = Counter(str(row["target_year"]) for row in rows)
    return {
        "generated_by": "build_youtube_year_backfill_queue.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "public_events": str(DEFAULT_PUBLIC_EVENTS),
            "event_occurrence_observations": str(DEFAULT_OBSERVATIONS),
        },
        "target_years": target_years,
        "summary": {
            "items": len(rows),
            "priority_counts": dict(sorted(counts.items())),
            "target_year_counts": dict(sorted(years.items())),
            "observed_seed_items": sum(1 for row in rows if row["observed_years"]),
        },
        "rows": rows,
    }


def render_markdown(data, limit=80):
    lines = [
        "# YouTube 過去年バックフィルキュー",
        "",
        f"- 生成: {data['generated_at']}",
        f"- items: {data['summary']['items']}",
        f"- target_years: {', '.join(str(year) for year in data['target_years'])}",
        f"- observed_seed_items: {data['summary']['observed_seed_items']}",
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
        "| priority | score | year | event | venue | observed | sources | queries |",
        "| --- | ---: | ---: | --- | --- | --- | ---: | --- |",
    ])
    for row in data["rows"][:limit]:
        observed = ",".join(str(year) for year in row["observed_years"]) or "-"
        event_name = md_cell(row["event_name"])
        venue = md_cell(row["venue"])
        query = md_cell(row["search_queries"][0])
        lines.append(
            f"| {row['priority']} | {row['priority_score']} | {row['target_year']} | "
            f"{event_name} | {venue} | "
            f"{observed} | {row['source_url_count']} | {query} |"
        )
    lines.append("")
    return "\n".join(lines)


def md_cell(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-events", default=str(DEFAULT_PUBLIC_EVENTS))
    parser.add_argument("--observations", default=str(DEFAULT_OBSERVATIONS))
    parser.add_argument("--target-years", default=DEFAULT_TARGET_YEARS)
    parser.add_argument("--out-json", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--out-md", default=str(DEFAULT_OUT_MD))
    args = parser.parse_args()

    public_events = read_json(args.public_events, [])
    observations = read_json(args.observations, {})
    target_years = parse_target_years(args.target_years)
    data = build_queue(public_events, observations, target_years)
    write_json(args.out_json, data)
    Path(args.out_md).write_text(render_markdown(data), encoding="utf-8")
    print(
        "youtube year backfill queue: "
        f"items={data['summary']['items']} "
        f"observed_seed_items={data['summary']['observed_seed_items']} "
        f"priorities={data['summary']['priority_counts']}"
    )


if __name__ == "__main__":
    main()
