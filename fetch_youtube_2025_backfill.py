"""Fetch 2025 videos from active YouTube channels into voices.json."""

import argparse
import json
import os
import re
import tempfile
import urllib.parse
import urllib.request
import urllib.error
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

from backfill_youtube_descriptions import best_thumbnail_url, load_env_value
from extract_youtube_setlists import compact_url


DATA = Path("data")
REGISTRY = DATA / "youtube_channel_registry.json"
VOICES = DATA / "voices.json"
REPORT = DATA / "youtube_2025_backfill_fetch_report.json"
YOUTUBE_CHANNELS_API = "https://www.googleapis.com/youtube/v3/channels"
YOUTUBE_PLAYLIST_ITEMS_API = "https://www.googleapis.com/youtube/v3/playlistItems"
URL_RE = re.compile(r"https?://[^\s\"'<>]+")


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


def active_channels(registry, include_channel_ids=None):
    include_channel_ids = set(include_channel_ids or [])
    channels = []
    for row in registry.get("channels") or []:
        if row.get("status") == "active" and row.get("collection_enabled") and row.get("channel_id"):
            if include_channel_ids and row.get("channel_id") not in include_channel_ids:
                continue
            channels.append(row)
    return channels


def request_json(url, retries=3):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=45) as response:
                return json.loads(response.read().decode("utf-8"))
        except (socket.timeout, TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(attempt * 2)
    raise last_error


def fetch_upload_playlist_ids(channel_ids, api_key):
    params = urllib.parse.urlencode({
        "part": "contentDetails,snippet",
        "id": ",".join(channel_ids),
        "maxResults": 50,
        "key": api_key,
    })
    payload = request_json(f"{YOUTUBE_CHANNELS_API}?{params}")
    rows = {}
    for item in payload.get("items") or []:
        channel_id = item.get("id") or ""
        uploads = (
            ((item.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
            or ""
        )
        snippet = item.get("snippet") or {}
        if channel_id and uploads:
            rows[channel_id] = {
                "uploads_playlist_id": uploads,
                "title": snippet.get("title") or channel_id,
            }
    return rows


def fetch_playlist_items(playlist_id, api_key, max_pages):
    rows = []
    page_token = ""
    pages = 0
    while True:
        params = {
            "part": "snippet",
            "playlistId": playlist_id,
            "maxResults": 50,
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token
        payload = request_json(f"{YOUTUBE_PLAYLIST_ITEMS_API}?{urllib.parse.urlencode(params)}")
        pages += 1
        rows.extend(payload.get("items") or [])
        page_token = payload.get("nextPageToken") or ""
        if not page_token or pages >= max_pages:
            break
        published = [
            ((item.get("snippet") or {}).get("publishedAt") or "")
            for item in payload.get("items") or []
        ]
        if published and max(published) < "2025-01-01T00:00:00Z":
            break
    return rows, pages


def extract_urls(text):
    urls = []
    for match in URL_RE.finditer(text or ""):
        url = match.group(0).rstrip(")、。，.,)")
        if url and url not in urls:
            urls.append(url)
    return urls


def item_to_voice(item, channel):
    snippet = item.get("snippet") or {}
    resource = snippet.get("resourceId") or {}
    video_id = resource.get("videoId") or ""
    if not video_id:
        return None
    description = snippet.get("description") or ""
    channel_id = channel.get("channel_id") or snippet.get("videoOwnerChannelId") or snippet.get("channelId") or ""
    channel_title = channel.get("channel_title") or snippet.get("videoOwnerChannelTitle") or snippet.get("channelTitle") or channel_id
    voice = {
        "source": "youtube",
        "account": channel_id,
        "name": channel_title,
        "title": snippet.get("title") or "",
        "text": description[:3000],
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "date": snippet.get("publishedAt") or "",
        "tags": [],
        "youtube_channel_id": channel_id,
        "youtube_channel_title": channel_title,
        "youtube_published_at": snippet.get("publishedAt") or "",
        "thumbnail_url": best_thumbnail_url(snippet.get("thumbnails") or {}),
        "youtube_backfill_source": "fetch_youtube_2025_backfill.py",
    }
    urls = extract_urls(description)
    if urls:
        voice["media_urls"] = urls
    return voice


def merge_voices(existing, additions):
    by_url = {compact_url(row.get("url") or ""): row for row in existing if row.get("url")}
    added = 0
    updated = 0
    for voice in additions:
        key = compact_url(voice.get("url") or "")
        if not key:
            continue
        current = by_url.get(key)
        if not current:
            by_url[key] = voice
            added += 1
            continue
        changed = False
        for field in [
            "text",
            "media_urls",
            "youtube_channel_id",
            "youtube_channel_title",
            "youtube_published_at",
            "thumbnail_url",
        ]:
            value = voice.get(field)
            if value and value != current.get(field):
                if field == "text" and len(str(value)) <= len(str(current.get(field) or "")):
                    continue
                current[field] = value
                changed = True
        if changed:
            updated += 1
    merged = sorted(by_url.values(), key=lambda row: row.get("date") or "", reverse=True)
    return merged, added, updated


def fetch_backfill(registry, api_key, year="2025", max_pages_per_channel=10, channel_ids=None):
    channels = active_channels(registry, include_channel_ids=channel_ids)
    playlist_by_channel = fetch_upload_playlist_ids([row["channel_id"] for row in channels], api_key)
    additions = []
    channel_reports = []
    request_count = 1
    for channel in channels:
        channel_id = channel["channel_id"]
        playlist = (playlist_by_channel.get(channel_id) or {}).get("uploads_playlist_id")
        if not playlist:
            channel_reports.append({
                "channel_id": channel_id,
                "channel_title": channel.get("channel_title") or channel_id,
                "status": "missing_uploads_playlist",
                "fetched_items": 0,
                "year_video_count": 0,
            })
            continue
        items, pages = fetch_playlist_items(playlist, api_key, max_pages=max_pages_per_channel)
        request_count += pages
        year_items = [
            item for item in items
            if ((item.get("snippet") or {}).get("publishedAt") or "").startswith(year)
        ]
        voices = [item_to_voice(item, channel) for item in year_items]
        voices = [voice for voice in voices if voice]
        additions.extend(voices)
        channel_reports.append({
            "channel_id": channel_id,
            "channel_title": channel.get("channel_title") or channel_id,
            "priority": channel.get("priority") or "",
            "candidate_score": (channel.get("review_decision") or {}).get("candidate_score"),
            "auto_score": ((channel.get("metrics") or {}).get("analytics") or {}).get("auto_score"),
            "status": "ok",
            "playlist_pages": pages,
            "fetched_items": len(items),
            "year_video_count": len(voices),
        })
    return additions, channel_reports, request_count


def build_report(channel_reports, additions, request_count, dry_run, added=0, updated=0):
    counts = {}
    for voice in additions:
        title = voice.get("youtube_channel_title") or voice.get("name") or voice.get("account")
        counts[title] = counts.get(title, 0) + 1
    return {
        "generated_by": "fetch_youtube_2025_backfill.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "api_request_count": request_count,
        "fetched_2025_video_count": len(additions),
        "voices_added": added,
        "voices_updated": updated,
        "by_channel": channel_reports,
        "addition_counts_by_channel": counts,
        "samples": additions[:20],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", default="2025")
    parser.add_argument("--max-pages-per-channel", type=int, default=10)
    parser.add_argument("--channel-id", action="append", dest="channel_ids", help="Limit to a channel ID. Repeatable.")
    parser.add_argument("--registry", default=str(REGISTRY))
    parser.add_argument("--voices", default=str(VOICES))
    parser.add_argument("--report", default=str(REPORT))
    parser.add_argument("--env", default=".env")
    parser.add_argument("--apply", action="store_true", help="Update voices.json.")
    args = parser.parse_args()

    api_key = load_env_value("YOUTUBE_DATA_API_KEY", args.env)
    if not api_key:
        raise SystemExit("YOUTUBE_DATA_API_KEY is not set")
    registry = load_json(args.registry, {"channels": []})
    additions, channel_reports, request_count = fetch_backfill(
        registry,
        api_key,
        year=args.year,
        max_pages_per_channel=args.max_pages_per_channel,
        channel_ids=args.channel_ids,
    )
    added = updated = 0
    if args.apply:
        voices_path = Path(args.voices)
        merged, added, updated = merge_voices(load_json(voices_path, []), additions)
        atomic_write_json(voices_path, merged)
    report = build_report(channel_reports, additions, request_count, not args.apply, added=added, updated=updated)
    atomic_write_json(args.report, report)
    print(
        "[youtube-2025-backfill] "
        f"fetched_2025={len(additions)} requests={request_count} "
        f"added={added} updated={updated} dry_run={not args.apply} -> {args.report}"
    )


if __name__ == "__main__":
    main()
