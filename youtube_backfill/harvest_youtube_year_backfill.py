"""Harvest YouTube candidates for past-year event occurrence backfill."""

import argparse
import json
import re
import tempfile
import urllib.parse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from youtube_channels.backfill_youtube_descriptions import best_thumbnail_url, load_env_value
from youtube_channels.discover_youtube_channels import VIDEOS_API_URL, SEARCH_API_URL, enrich_video_candidate, youtube_get
from event_series.normalization import series_event_name
from youtube_channels.extract_youtube_setlists import BON_CONTEXT_RE, parse_youtube_event_date


DATA = Path("data")
QUEUE = DATA / "youtube_year_backfill_queue.json"
OUT = DATA / "youtube_year_backfill_candidates.json"
MD_OUT = DATA / "youtube_year_backfill_candidates.md"


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".tmp-", suffix=".json", delete=False
    ) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        tmp_name = handle.name
    Path(tmp_name).replace(path)


def atomic_write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".tmp-", suffix=".md", delete=False
    ) as handle:
        handle.write(text)
        tmp_name = handle.name
    Path(tmp_name).replace(path)


def chunks(items, size):
    for idx in range(0, len(items), size):
        yield items[idx:idx + size]


def norm(text):
    return re.sub(r"[^0-9A-Za-zぁ-んァ-ン一-龥]", "", str(text or "")).lower()


def year_of(date):
    match = re.match(r"^(\d{4})-\d{2}-\d{2}$", str(date or ""))
    return int(match.group(1)) if match else None


def queue_rows(queue, limit, priorities, offset=0):
    priorities = set(priorities)
    rows = [row for row in queue.get("rows") or [] if row.get("priority") in priorities]
    rows.sort(key=lambda row: (-row.get("priority_score", 0), row.get("target_year", 9999), row.get("event_name", "")))
    return rows[offset:offset + limit]


def search_videos_for_row(row, api_key, max_results):
    published_after = f"{row['target_year']}-01-01T00:00:00Z"
    published_before = f"{row['target_year'] + 2}-01-01T00:00:00Z"
    results = []
    for query in (row.get("search_queries") or [])[:2]:
        payload = youtube_get(SEARCH_API_URL, {
            "part": "snippet",
            "type": "video",
            "q": query,
            "maxResults": max_results,
            "order": "relevance",
            "publishedAfter": published_after,
            "publishedBefore": published_before,
            "key": api_key,
        })
        for item in payload.get("items", []):
            video_id = ((item.get("id") or {}).get("videoId") or "").strip()
            snippet = item.get("snippet") or {}
            if not video_id:
                continue
            results.append({
                "video_id": video_id,
                "query": query,
                "title": snippet.get("title") or "",
                "description": snippet.get("description") or "",
                "channel_id": snippet.get("channelId") or "",
                "channel_title": snippet.get("channelTitle") or "",
                "published_at": snippet.get("publishedAt") or "",
                "thumbnail_url": best_thumbnail_url(snippet.get("thumbnails") or {}),
            })
    return results


def fetch_video_snippets(video_ids, api_key):
    snippets = {}
    for batch in chunks(video_ids, 50):
        payload = youtube_get(VIDEOS_API_URL, {
            "part": "snippet",
            "id": ",".join(batch),
            "key": api_key,
        })
        for item in payload.get("items", []):
            video_id = item.get("id") or ""
            snippet = item.get("snippet") or {}
            if video_id:
                snippets[video_id] = snippet
    return snippets


def evidence_score(row, video):
    text = "\n".join([video.get("title") or "", video.get("description") or ""])
    title_text = norm(text)
    event_key = norm(series_event_name(row.get("event_name")))
    venue_key = norm(row.get("venue"))
    target_year = row.get("target_year")
    parsed_date = parse_youtube_event_date(text)
    score = 0
    reasons = []
    if event_key and event_key in title_text:
        score += 35
        reasons.append("event_name_in_video")
    if venue_key and venue_key in title_text:
        score += 25
        reasons.append("venue_in_video")
    if str(target_year) in text:
        score += 18
        reasons.append("target_year_in_video")
    if year_of(parsed_date) == target_year:
        score += 30
        reasons.append("target_year_date_detected")
    elif parsed_date:
        reasons.append("other_year_date_detected")
    if BON_CONTEXT_RE.search(text) or re.search(r"bon\s*odori", text, re.I):
        score += 12
        reasons.append("bon_context")
    if video.get("setlist_count", 0) >= 2:
        score += 15
        reasons.append("setlist_detected")
    if video.get("channel_title"):
        score += 3
    if "event_name_in_video" not in reasons and "venue_in_video" not in reasons:
        score = min(score, 45)
    if parsed_date and year_of(parsed_date) != target_year:
        score = min(score, 49)
    elif not parsed_date and "target_year_in_video" not in reasons:
        score = min(score, 65)
    if score >= 80:
        status = "strong"
    elif score >= 50:
        status = "review"
    else:
        status = "weak"
    return min(score, 100), status, reasons, parsed_date or ""


def candidate_row(queue_row, video):
    score, status, reasons, detected_date = evidence_score(queue_row, video)
    return {
        "status": status,
        "score": score,
        "reasons": reasons,
        "queue_id": queue_row.get("queue_id"),
        "target_year": queue_row.get("target_year"),
        "event_name": series_event_name(queue_row.get("event_name")),
        "venue": queue_row.get("venue"),
        "area": queue_row.get("area"),
        "detected_event_date": detected_date,
        "video_id": video.get("video_id"),
        "video_url": video.get("url") or f"https://www.youtube.com/watch?v={video.get('video_id')}",
        "title": video.get("title") or "",
        "channel_id": video.get("channel_id") or "",
        "channel_title": video.get("channel_title") or "",
        "published_at": video.get("published_at") or "",
        "thumbnail_url": video.get("thumbnail_url") or "",
        "query": video.get("query") or "",
        "setlist_count": video.get("setlist_count") or 0,
        "setlist_sample": video.get("setlist_sample") or [],
        "description_excerpt": video.get("description_excerpt") or "",
    }


def harvest(queue, api_key, limit=12, max_results=5, priorities=("high",), offset=0):
    selected = queue_rows(queue, limit=limit, priorities=priorities, offset=offset)
    search_rows = []
    seen_video_query = set()
    for row in selected:
        for video in search_videos_for_row(row, api_key=api_key, max_results=max_results):
            key = (row.get("queue_id"), video["video_id"])
            if key in seen_video_query:
                continue
            seen_video_query.add(key)
            search_rows.append({"queue_row": row, "video": video})

    snippets = fetch_video_snippets(sorted({item["video"]["video_id"] for item in search_rows}), api_key)
    candidates = []
    seen_candidate = set()
    for item in search_rows:
        video = item["video"]
        snippet = snippets.get(video["video_id"]) or {}
        if snippet:
            video = {
                **video,
                "title": snippet.get("title") or video.get("title") or "",
                "description": snippet.get("description") or video.get("description") or "",
                "channel_id": snippet.get("channelId") or video.get("channel_id") or "",
                "channel_title": snippet.get("channelTitle") or video.get("channel_title") or "",
                "published_at": snippet.get("publishedAt") or video.get("published_at") or "",
                "thumbnail_url": best_thumbnail_url(snippet.get("thumbnails") or {}) or video.get("thumbnail_url") or "",
            }
        video["url"] = f"https://www.youtube.com/watch?v={video['video_id']}"
        enriched = enrich_video_candidate(video)
        candidate = candidate_row(item["queue_row"], enriched)
        dedupe_key = (candidate["queue_id"], candidate["video_id"])
        if dedupe_key in seen_candidate:
            continue
        seen_candidate.add(dedupe_key)
        candidates.append(candidate)

    candidates.sort(key=lambda row: (-row["score"], row["target_year"], row["event_name"], row["title"]))
    counts = Counter(row["status"] for row in candidates)
    return {
        "generated_by": "harvest_youtube_year_backfill.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(QUEUE),
        "selected_queue_count": len(selected),
        "queue_offset": offset,
        "max_results_per_query": max_results,
        "api_request_count_estimate": len(selected) * 2 + ((len(snippets) + 49) // 50),
        "summary": {
            "candidate_count": len(candidates),
            "status_counts": dict(sorted(counts.items())),
            "strong_count": counts.get("strong", 0),
            "review_count": counts.get("review", 0),
        },
        "selected_queue_rows": selected,
        "candidates": candidates,
    }


def merge_harvests(existing, fresh):
    if not existing:
        return fresh
    selected = {}
    for row in (existing.get("selected_queue_rows") or []) + (fresh.get("selected_queue_rows") or []):
        item = dict(row)
        item["event_name"] = series_event_name(item.get("event_name"))
        selected[item.get("queue_id")] = item
    candidates = {}
    for row in (existing.get("candidates") or []) + (fresh.get("candidates") or []):
        item = dict(row)
        item["event_name"] = series_event_name(item.get("event_name"))
        candidates[(item.get("queue_id"), item.get("video_id"))] = item
    merged_candidates = sorted(
        candidates.values(),
        key=lambda row: (-row["score"], row["target_year"], row["event_name"], row["title"]),
    )
    counts = Counter(row["status"] for row in merged_candidates)
    return {
        **fresh,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selected_queue_count": len(selected),
        "merged_from": existing.get("generated_at") or "",
        "summary": {
            "candidate_count": len(merged_candidates),
            "status_counts": dict(sorted(counts.items())),
            "strong_count": counts.get("strong", 0),
            "review_count": counts.get("review", 0),
        },
        "selected_queue_rows": sorted(
            selected.values(),
            key=lambda row: (-row.get("priority_score", 0), row.get("target_year", 9999), row.get("event_name", "")),
        ),
        "candidates": merged_candidates,
    }


def md_cell(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def md_truncate(value, limit=100):
    value = md_cell(value)
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def render_markdown(data, limit=80):
    lines = [
        "# YouTube 過去年バックフィル候補",
        "",
        f"- 生成: {data['generated_at']}",
        f"- selected_queue_count: {data['selected_queue_count']}",
        f"- candidate_count: {data['summary']['candidate_count']}",
        f"- strong: {data['summary']['strong_count']}",
        f"- review: {data['summary']['review_count']}",
        "",
        "| status | score | year | event | venue | detected | channel | title | url |",
        "| --- | ---: | ---: | --- | --- | --- | --- | --- | --- |",
    ]
    for row in data["candidates"][:limit]:
        lines.append(
            f"| {row['status']} | {row['score']} | {row['target_year']} | "
            f"{md_cell(row['event_name'])} | {md_cell(row['venue'])} | "
            f"{md_cell(row['detected_event_date'])} | {md_cell(row['channel_title'])} | "
            f"{md_truncate(row['title'])} | {md_cell(row['video_url'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", default=str(QUEUE))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--md-out", default=str(MD_OUT))
    parser.add_argument("--env", default=".env")
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--priority", action="append", dest="priorities")
    parser.add_argument("--append-existing", action="store_true")
    args = parser.parse_args()

    api_key = load_env_value("YOUTUBE_DATA_API_KEY", args.env)
    if not api_key:
        raise SystemExit("YOUTUBE_DATA_API_KEY is not set")
    queue = load_json(args.queue, {})
    data = harvest(
        queue,
        api_key=api_key,
        limit=args.limit,
        offset=args.offset,
        max_results=args.max_results,
        priorities=args.priorities or ["high"],
    )
    if args.append_existing:
        data = merge_harvests(load_json(args.out, {}), data)
    atomic_write_json(args.out, data)
    atomic_write_text(args.md_out, render_markdown(data))
    print(
        "youtube year backfill harvest: "
        f"selected={data['selected_queue_count']} "
        f"candidates={data['summary']['candidate_count']} "
        f"strong={data['summary']['strong_count']} "
        f"review={data['summary']['review_count']} "
        f"requests~={data['api_request_count_estimate']}"
    )


if __name__ == "__main__":
    main()
