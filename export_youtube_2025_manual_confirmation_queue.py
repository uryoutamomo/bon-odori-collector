"""Export a manual confirmation queue for remaining YouTube 2025 candidates."""

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


SECOND_PASS = Path("data/youtube_2025_second_pass_event_groups.json")
ACTIVE_REVIEW = Path("data/youtube_active_video_review.json")
OUT = Path("data/youtube_2025_manual_confirmation_queue.json")
MD_OUT = Path("data/youtube_2025_manual_confirmation_queue.md")

LOW_VALUE_DOMAINS = {
    "ebay.com",
    "google.com",
    "goo.gl",
    "instagram.com",
    "linktr.ee",
    "maps.app.goo.gl",
    "twitter.com",
    "x.com",
    "youtu.be",
    "youtube.com",
}


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def md_escape(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def domain(url):
    host = (urlparse(url or "").netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def is_low_value_url(url):
    host = domain(url)
    return any(host == low or host.endswith("." + low) for low in LOW_VALUE_DOMAINS)


def primary_candidate_url(urls):
    for url in urls:
        if url and not is_low_value_url(url):
            return url
    for url in urls:
        if url:
            return url
    return ""


def remaining_backfill_rows(second_pass):
    rows = []
    for group in second_pass.get("groups") or []:
        category = group.get("category") or ""
        if category == "date_backfill_candidate_single_date":
            priority = "high"
        elif category == "date_backfill_candidate_multi_date":
            priority = "normal"
        else:
            priority = "low"
        rows.append(
            {
                "queue": "remaining_backfill",
                "priority": priority,
                "category": category,
                "event_name": group.get("event_name") or "",
                "event_id": group.get("event_id") or "",
                "video_count": group.get("video_count") or 0,
                "detected_dates": group.get("detected_dates") or [],
                "source_url": group.get("event_source_url") or "",
                "recommended_action": group.get("recommended_action") or "",
                "sample_videos": group.get("sample_videos") or [],
            }
        )
    return rows


def official_confirmation_rows(active_review):
    grouped = {}
    for row in active_review.get("rows") or []:
        if row.get("action") != "needs_official_confirmation":
            continue
        urls = row.get("official_urls") or []
        primary_url = primary_candidate_url(urls)
        host = domain(primary_url)
        if not primary_url:
            bucket = "missing_url"
            priority = "low"
        elif is_low_value_url(primary_url):
            bucket = "social_or_map_only"
            priority = "low"
        else:
            bucket = "official_url_candidate"
            priority = "high"
        key = (bucket, primary_url or row.get("title") or row.get("video_url") or "")
        item = grouped.setdefault(
            key,
            {
                "queue": "needs_official_confirmation",
                "priority": priority,
                "category": bucket,
                "primary_url": primary_url,
                "primary_domain": host,
                "video_count": 0,
                "detected_dates": [],
                "titles": [],
                "videos": [],
            },
        )
        item["video_count"] += 1
        if row.get("detected_event_date") and row["detected_event_date"] not in item["detected_dates"]:
            item["detected_dates"].append(row["detected_event_date"])
        title = row.get("title") or ""
        if title and title not in item["titles"] and len(item["titles"]) < 5:
            item["titles"].append(title)
        item["videos"].append(
            {
                "title": title,
                "video_url": row.get("video_url") or row.get("source_url") or "",
                "official_urls": urls,
                "detected_event_date": row.get("detected_event_date") or "",
                "channel_id": row.get("channel_id") or "",
            }
        )
    rows = list(grouped.values())
    for row in rows:
        row["detected_dates"].sort()
    return rows


def build_queue(second_pass_path=SECOND_PASS, active_review_path=ACTIVE_REVIEW):
    second_pass = load_json(second_pass_path, {"groups": []})
    active_review = load_json(active_review_path, {"rows": []})
    rows = remaining_backfill_rows(second_pass) + official_confirmation_rows(active_review)
    rows.sort(key=lambda row: ({"high": 0, "normal": 1, "low": 2}.get(row["priority"], 9), row["queue"], -row["video_count"]))
    counts = defaultdict(lambda: {"items": 0, "videos": 0})
    for row in rows:
        key = f"{row['queue']}:{row['category']}"
        counts[key]["items"] += 1
        counts[key]["videos"] += row.get("video_count") or 0
    return {
        "generated_by": "export_youtube_2025_manual_confirmation_queue.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": [str(second_pass_path), str(active_review_path)],
        "item_count": len(rows),
        "video_count": sum(row.get("video_count") or 0 for row in rows),
        "counts": [{"bucket": key, **value} for key, value in sorted(counts.items())],
        "rows": rows,
    }


def render_markdown(queue):
    lines = [
        "# YouTube 2025 手動確認キュー",
        "",
        f"- 生成: {queue['generated_at']}",
        f"- items: {queue['item_count']}",
        f"- videos: {queue['video_count']}",
        "",
        "## counts",
        "",
        "| bucket | items | videos |",
        "| --- | ---: | ---: |",
    ]
    for row in queue["counts"]:
        lines.append(f"| {md_escape(row['bucket'])} | {row['items']} | {row['videos']} |")
    lines.extend([
        "",
        "## queue",
        "",
        "| priority | queue | category | name/url | dates | videos | action |",
        "| --- | --- | --- | --- | --- | ---: | --- |",
    ])
    for row in queue["rows"]:
        name = row.get("event_name") or row.get("primary_url") or "URL未確認"
        dates = ", ".join(row.get("detected_dates") or [])
        action = row.get("recommended_action") or "公式URL本文確認。本DB登録/追記は確認後に限定"
        lines.append(
            f"| {md_escape(row['priority'])} | {md_escape(row['queue'])} | {md_escape(row['category'])} | "
            f"{md_escape(name)} | {md_escape(dates)} | {row.get('video_count') or 0} | {md_escape(action)} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    queue = build_queue()
    OUT.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MD_OUT.write_text(render_markdown(queue), encoding="utf-8")
    print(
        "[youtube-2025-manual-confirmation-queue] "
        f"items={queue['item_count']} videos={queue['video_count']} -> {OUT}"
    )


if __name__ == "__main__":
    main()
