"""Backfill YouTube voice descriptions with YouTube Data API v3."""

import argparse
import json
import os
import re
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from extract_youtube_setlists import compact_url


VOICES = Path("data/voices.json")
OUT_REPORT = Path("data/youtube_description_backfill_report.json")
YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3/videos"
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


def load_env_value(name, env_path=".env"):
    if os.environ.get(name):
        return os.environ[name]
    path = Path(env_path)
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return ""


def video_id_from_url(url):
    url = compact_url(url)
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname == "youtu.be":
        return parsed.path.strip("/")
    if parsed.hostname in {"www.youtube.com", "youtube.com"}:
        query = urllib.parse.parse_qs(parsed.query)
        return (query.get("v") or [""])[0]
    return ""


def chunks(items, size):
    for idx in range(0, len(items), size):
        yield items[idx:idx + size]


def youtube_voices(voices):
    return [v for v in voices if v.get("source") == "youtube" and v.get("url")]


def extract_urls(text):
    urls = []
    for match in URL_RE.finditer(text or ""):
        url = match.group(0).rstrip(")、。，.,)")
        if url and url not in urls:
            urls.append(url)
    return urls


def best_thumbnail_url(thumbnails):
    thumbnails = thumbnails or {}
    for key in ("maxres", "standard", "high", "medium", "default"):
        url = (thumbnails.get(key) or {}).get("url")
        if url:
            return url
    return ""


def plan_backfill(voices):
    rows = []
    seen = set()
    for idx, voice in enumerate(youtube_voices(voices)):
        video_id = video_id_from_url(voice.get("url"))
        if not video_id or video_id in seen:
            continue
        seen.add(video_id)
        rows.append({
            "index": idx,
            "video_id": video_id,
            "url": compact_url(voice.get("url")),
            "title": voice.get("title") or "",
            "current_text_length": len(voice.get("text") or ""),
            "has_media_urls": bool(voice.get("media_urls")),
        })
    return rows


def fetch_video_snippets(video_ids, api_key):
    if not video_ids:
        return {}
    params = urllib.parse.urlencode({
        "part": "snippet",
        "id": ",".join(video_ids),
        "key": api_key,
        "maxResults": 50,
    })
    url = f"{YOUTUBE_API_URL}?{params}"
    with urllib.request.urlopen(url, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    snippets = {}
    for item in payload.get("items", []):
        video_id = item.get("id")
        snippet = item.get("snippet") or {}
        if video_id:
            snippets[video_id] = snippet
    return snippets


def apply_snippets(voices, snippets):
    updated = 0
    expanded = 0
    media_updated = 0
    metadata_updated = 0
    missing = 0
    for voice in youtube_voices(voices):
        video_id = video_id_from_url(voice.get("url"))
        snippet = snippets.get(video_id)
        if not snippet:
            missing += 1
            continue
        description = snippet.get("description") or ""
        if not description:
            continue
        old_text = voice.get("text") or ""
        if description != old_text:
            voice["text"] = description
            updated += 1
            if len(description) > len(old_text):
                expanded += 1
        media_urls = extract_urls(description)
        if media_urls and media_urls != voice.get("media_urls"):
            voice["media_urls"] = media_urls
            media_updated += 1
        metadata = {
            "title": snippet.get("title") or "",
            "youtube_channel_id": snippet.get("channelId") or "",
            "youtube_channel_title": snippet.get("channelTitle") or "",
            "youtube_published_at": snippet.get("publishedAt") or "",
            "thumbnail_url": best_thumbnail_url(snippet.get("thumbnails") or {}),
        }
        changed = False
        for key, value in metadata.items():
            if value and voice.get(key) != value:
                voice[key] = value
                changed = True
        if changed:
            metadata_updated += 1
    return {
        "updated": updated,
        "expanded": expanded,
        "media_updated": media_updated,
        "metadata_updated": metadata_updated,
        "missing": missing,
    }


def build_report(plan, result=None, fetched_count=0, dry_run=True):
    return {
        "generated_by": "backfill_youtube_descriptions.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "planned_video_count": len(plan),
        "api_request_count_estimate": (len(plan) + 49) // 50,
        "fetched_video_count": fetched_count,
        "result": result or {},
        "planned_samples": plan[:20],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--voices", default=str(VOICES))
    parser.add_argument("--report", default=str(OUT_REPORT))
    parser.add_argument("--fetch", action="store_true", help="Call YouTube Data API and update voices.json.")
    parser.add_argument("--env", default=".env")
    args = parser.parse_args()

    voices_path = Path(args.voices)
    voices = load_json(voices_path, [])
    plan = plan_backfill(voices)
    if not args.fetch:
        report = build_report(plan, dry_run=True)
        atomic_write_json(args.report, report)
        print(
            "[youtube-backfill] dry-run: "
            f"videos={report['planned_video_count']} "
            f"requests~={report['api_request_count_estimate']} -> {args.report}"
        )
        return

    api_key = load_env_value("YOUTUBE_DATA_API_KEY", args.env)
    if not api_key:
        raise SystemExit("YOUTUBE_DATA_API_KEY is not set")

    snippets = {}
    for batch in chunks([row["video_id"] for row in plan], 50):
        snippets.update(fetch_video_snippets(batch, api_key))
    result = apply_snippets(voices, snippets)
    atomic_write_json(voices_path, voices)
    report = build_report(plan, result=result, fetched_count=len(snippets), dry_run=False)
    atomic_write_json(args.report, report)
    print(
        "[youtube-backfill] fetched: "
        f"videos={len(snippets)}/{len(plan)} "
        f"updated={result['updated']} expanded={result['expanded']} "
        f"media_updated={result['media_updated']} "
        f"metadata_updated={result['metadata_updated']} -> {voices_path}"
    )


if __name__ == "__main__":
    main()
