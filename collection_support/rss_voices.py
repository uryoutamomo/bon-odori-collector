"""RSS voice collection and its two-file snapshot transaction.

Network/parser access and feed discovery are injected by the caller so the
collector facade can retain its existing test patch points.
"""

import html
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


VOICE_TEXT_MAX_CHARS = 3000


@dataclass
class VoiceCollectionResult:
    """One RSS lane result. Failed lanes never contribute partial rows."""

    state: str
    items: list = field(default_factory=list)
    seen_urls: list = field(default_factory=list)
    failures: list = field(default_factory=list)


class VoiceCollectionError(RuntimeError):
    pass


def read_json_list(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, list):
        raise ValueError(f"{path} must contain a JSON array")
    return value


def _atomic_write_json(path, value):
    path = Path(path)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_name = handle.name
    return Path(temp_name)


def commit_voice_snapshot(voices_file, voices, seen_file, seen):
    """Commit both state files, restoring the first if the second replace fails."""
    voices_file, seen_file = Path(voices_file), Path(seen_file)
    old_voices = voices_file.read_bytes() if voices_file.exists() else None
    old_seen = seen_file.read_bytes() if seen_file.exists() else None
    voices_temp = _atomic_write_json(voices_file, voices)
    seen_temp = _atomic_write_json(seen_file, seen)
    try:
        voices_temp.replace(voices_file)
        seen_temp.replace(seen_file)
    except Exception:
        if old_voices is not None:
            restore = voices_file.with_name(voices_file.name + ".restore")
            restore.write_bytes(old_voices)
            restore.replace(voices_file)
        elif voices_file.exists():
            voices_file.unlink()
        if old_seen is not None:
            restore = seen_file.with_name(seen_file.name + ".restore")
            restore.write_bytes(old_seen)
            restore.replace(seen_file)
        elif seen_file.exists():
            seen_file.unlink()
        raise
    finally:
        for path in (voices_temp, seen_temp):
            if path.exists():
                path.unlink()


def load_active_youtube_registry_feeds(path):
    """Load active YouTube channel RSS feeds from the registry if it exists."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as handle:
            registry = json.load(handle)
    except Exception as exc:
        raise VoiceCollectionError(f"youtube_registry:{type(exc).__name__}") from exc

    feeds = []
    for channel in registry.get("channels") or []:
        if channel.get("status") != "active" or not channel.get("collection_enabled"):
            continue
        channel_id = channel.get("channel_id") or ""
        rss_url = channel.get("rss_url") or (
            f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}" if channel_id else ""
        )
        if rss_url:
            feeds.append({
                "source": "youtube", "account": channel.get("account") or channel_id,
                "name": channel.get("channel_title") or channel_id, "rss_url": rss_url,
                "channel_id": channel_id,
            })
    return feeds


def voice_feeds(static_feeds, registry_path):
    """Merge static feeds and active registry feeds, de-duplicated by RSS URL."""
    feeds, seen_rss = [], set()
    for feed in static_feeds + load_active_youtube_registry_feeds(registry_path):
        rss_url = feed.get("rss_url")
        if rss_url and rss_url not in seen_rss:
            feeds.append(feed)
            seen_rss.add(rss_url)
    return feeds


def extract_urls(text):
    urls = []
    for match in re.finditer(r"https?://[^\s\"'<>]+", text or ""):
        url = html.unescape(match.group(0)).rstrip(")、。，.,)")
        if url and url not in urls:
            urls.append(url)
    return urls


def parse_voice_entry(entry, feed_meta):
    title = entry.get("title", "")
    url = entry.get("link", "")
    text = ""
    if "summary" in entry:
        text = entry["summary"]
    elif entry.get("content"):
        text = entry["content"][0].get("value", "")
    media_urls = extract_urls(text)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text)).strip()[:VOICE_TEXT_MAX_CHARS]
    date_str = ""
    parsed_date = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed_date:
        from time import mktime
        date_str = datetime.fromtimestamp(mktime(parsed_date), tz=timezone.utc).isoformat()
    voice = {
        "source": feed_meta["source"], "account": feed_meta["account"], "name": feed_meta["name"],
        "title": title, "text": text, "url": url, "date": date_str,
        "tags": [tag.get("term", "") for tag in entry.get("tags", []) if tag.get("term")],
    }
    if media_urls:
        voice["media_urls"] = media_urls
    if feed_meta.get("channel_id"):
        voice["youtube_channel_id"] = feed_meta["channel_id"]
        voice["youtube_channel_title"] = feed_meta["name"]
    return voice


def collect_voices_outcome(seen_urls, *, has_feedparser, feeds_loader, parser, entry_parser=parse_voice_entry):
    """Collect RSS voices under the explicit success/empty/skipped/failed contract."""
    original_seen = list(seen_urls)
    if not has_feedparser:
        print("[voices] feedparser がインストールされていないためスキップします")
        return VoiceCollectionResult("skipped", seen_urls=original_seen)
    try:
        feeds = feeds_loader()
    except VoiceCollectionError as exc:
        print(f"[voices] YouTubeチャンネル台帳を読めません: {exc}")
        return VoiceCollectionResult("failed", seen_urls=original_seen, failures=[str(exc)])
    if not feeds:
        print("[voices] RSS feed がないためスキップします")
        return VoiceCollectionResult("skipped", seen_urls=original_seen)
    new_items, new_seen, failures = [], list(seen_urls), []
    for feed_meta in feeds:
        rss_url = feed_meta["rss_url"]
        print(f"[voices] 取得中: {feed_meta['name']} ({rss_url})")
        try:
            parsed = parser.parse(rss_url)
            status = getattr(parsed, "status", None)
            if status is None and hasattr(parsed, "get"):
                status = parsed.get("status")
            if (status is not None and int(status) >= 400) or parsed.bozo:
                failure = f"rss:{feed_meta['name']}:" + (f"http_{status}" if status else "bozo")
                failures.append(failure)
                print(f"[voices] 取得失敗: {feed_meta['name']} ({failure.rsplit(':', 1)[-1]})")
                continue
            count = 0
            for entry in parsed.entries:
                url = entry.get("link", "")
                if not url or url in seen_urls or url in new_seen:
                    continue
                new_items.append(entry_parser(entry, feed_meta))
                new_seen.append(url)
                count += 1
            print(f"[voices] {feed_meta['name']}: {count} 件追加")
        except Exception as exc:
            print(f"[voices] エラー ({feed_meta['name']}): {exc}")
            failures.append(f"rss:{feed_meta['name']}:{type(exc).__name__}")
    if failures:
        return VoiceCollectionResult("failed", seen_urls=original_seen, failures=failures)
    return VoiceCollectionResult("success" if new_items else "empty", items=new_items, seen_urls=new_seen)
