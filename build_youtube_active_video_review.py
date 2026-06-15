"""Build a review table for videos from active YouTube channels."""

import argparse
import json
import re
import tempfile
import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from extract_youtube_setlists import compact_url, parse_youtube_event_date
from plan_youtube_event_updates import is_out_of_scope, match_public_event


DATA = Path("data")
VOICES = DATA / "voices.json"
REGISTRY = DATA / "youtube_channel_registry.json"
PUBLIC_EVENTS = DATA / "public" / "events_public.json"
YOUTUBE_SETLISTS = DATA / "youtube_setlist_occurrences.json"
OUT = DATA / "youtube_active_video_review.json"
MARKDOWN_OUT = DATA / "youtube_active_video_review.md"

BON_CONTEXT_RE = re.compile(r"(盆踊り|盆おどり|bon\s*odori|bondance|bon\s*dance|音頭|民踊)", re.I)
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}


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


def video_id_from_url(url):
    parsed = urllib.parse.urlparse(str(url or ""))
    host = parsed.hostname or ""
    if host == "youtu.be":
        return parsed.path.strip("/")
    if host in {"www.youtube.com", "youtube.com", "m.youtube.com"}:
        if parsed.path.startswith("/shorts/"):
            return parsed.path.split("/shorts/", 1)[1].split("/", 1)[0]
        query = urllib.parse.parse_qs(parsed.query)
        return (query.get("v") or [""])[0]
    return ""


def active_channel_ids(registry):
    ids = set()
    for channel in registry.get("channels") or []:
        if channel.get("status") == "active" and channel.get("collection_enabled"):
            ids.add(channel.get("channel_id"))
    return {channel_id for channel_id in ids if channel_id}


def is_youtube_url(url):
    host = urllib.parse.urlparse(str(url or "")).hostname or ""
    return host in YOUTUBE_HOSTS


def official_urls(voice):
    urls = []
    for url in voice.get("media_urls") or []:
        if not is_youtube_url(url) and url not in urls:
            urls.append(url)
    return urls


def has_bon_context(voice):
    return bool(BON_CONTEXT_RE.search("\n".join([voice.get("title") or "", voice.get("text") or ""])))


def setlist_video_index(payload):
    by_url = defaultdict(list)
    for occurrence in payload.get("occurrences") or []:
        summary = {
            "occurrence_key": occurrence.get("occurrence_key") or "",
            "event_name": occurrence.get("canonical_event_name")
            or occurrence.get("event_name_hint")
            or "",
            "venue": occurrence.get("canonical_venue") or occurrence.get("venue") or "",
            "event_date": occurrence.get("event_date") or "",
            "song_count": occurrence.get("song_count") or 0,
            "confidence": occurrence.get("confidence") or "",
        }
        for video in occurrence.get("source_videos") or []:
            url = compact_url(video.get("url"))
            if url:
                by_url[url].append(summary)
        for song in occurrence.get("setlist") or []:
            url = compact_url(song.get("url"))
            if url:
                by_url[url].append(summary)
    return by_url


def dedupe_occurrences(rows):
    seen = set()
    output = []
    for row in rows:
        key = row.get("occurrence_key")
        if key in seen:
            continue
        seen.add(key)
        output.append(row)
    return output


def latest_active_voices(voices, registry, max_per_channel=15):
    active_ids = active_channel_ids(registry)
    grouped = defaultdict(list)
    for voice in voices:
        channel_id = voice.get("youtube_channel_id") or voice.get("account") or ""
        if voice.get("source") != "youtube" or channel_id not in active_ids:
            continue
        grouped[channel_id].append(voice)
    selected = []
    for rows in grouped.values():
        selected.extend(sorted(rows, key=lambda row: row.get("date") or "", reverse=True)[:max_per_channel])
    return selected


def review_action(row):
    if row["out_of_scope"] and not row["matched_public_event"]:
        return "out_of_scope"
    if row["matched_public_event"] or row["setlist_occurrences"]:
        return "append_existing_event"
    if row["official_urls"] and row["has_bon_context"]:
        return "needs_official_confirmation"
    if row["has_bon_context"]:
        return "review_video_evidence"
    return "ignore"


def priority_for(row):
    if row["action"] == "append_existing_event":
        return "high"
    if row["official_urls"] and row["has_bon_context"]:
        return "high"
    if row["has_bon_context"]:
        return "normal"
    return "low"


def build_review(voices, registry, public_events, youtube_setlists, max_per_channel=15):
    setlist_by_url = setlist_video_index(youtube_setlists)
    rows = []
    for voice in latest_active_voices(voices, registry, max_per_channel=max_per_channel):
        url = compact_url(voice.get("url") or "")
        text = voice.get("text") or ""
        title = voice.get("title") or ""
        candidate = {
            "event_name": title,
            "venue": "",
            "source_video_title": title,
            "description_excerpt": text[:1000],
            "source_channel_title": voice.get("youtube_channel_title") or voice.get("name") or "",
        }
        row = {
            "video_id": video_id_from_url(url),
            "video_url": url,
            "source_url": voice.get("url") or "",
            "title": title,
            "channel_id": voice.get("youtube_channel_id") or voice.get("account") or "",
            "channel_title": voice.get("youtube_channel_title") or voice.get("name") or "",
            "published_at": voice.get("date") or "",
            "detected_event_date": parse_youtube_event_date(text, title) or "",
            "has_bon_context": has_bon_context(voice),
            "official_urls": official_urls(voice),
            "matched_public_event": match_public_event(candidate, public_events),
            "setlist_occurrences": dedupe_occurrences(setlist_by_url.get(url, [])),
            "out_of_scope": is_out_of_scope(candidate),
            "description_excerpt": text[:240],
        }
        row["action"] = review_action(row)
        row["priority"] = priority_for(row)
        rows.append(row)
    rows.sort(key=lambda row: (
        {"append_existing_event": 0, "needs_official_confirmation": 1, "review_video_evidence": 2,
         "out_of_scope": 3, "ignore": 4}.get(row["action"], 9),
        {"high": 0, "normal": 1, "low": 2}.get(row["priority"], 9),
        row["channel_title"],
        row["published_at"],
    ))
    counts = {}
    for row in rows:
        counts[row["action"]] = counts.get(row["action"], 0) + 1
    return {
        "generated_by": "build_youtube_active_video_review.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "voices": str(VOICES),
            "registry": str(REGISTRY),
            "public_events": str(PUBLIC_EVENTS),
            "youtube_setlists": str(YOUTUBE_SETLISTS),
        },
        "max_per_channel": max_per_channel,
        "video_count": len(rows),
        "counts": counts,
        "rows": rows,
    }


def md_escape(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def md_link(title, url):
    if not url:
        return md_escape(title)
    return f"[{md_escape(title)}]({md_escape(url)})"


def render_markdown(review):
    lines = [
        "# YouTube active動画レビュー",
        "",
        f"- 生成: {review['generated_at']}",
        f"- 対象: activeチャンネル各{review['max_per_channel']}件まで",
        f"- 動画数: {review['video_count']}件",
    ]
    for action, count in sorted(review["counts"].items()):
        lines.append(f"- {action}: {count}件")
    lines.extend([
        "",
        "| action | priority | channel | published | video | match | official_url | setlist |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for row in review["rows"]:
        match = row.get("matched_public_event") or {}
        match_text = " / ".join(x for x in [match.get("name"), match.get("venue")] if x)
        official = row["official_urls"][0] if row["official_urls"] else ""
        setlist = ", ".join(
            f"{item.get('event_name')}({item.get('song_count')})"
            for item in row["setlist_occurrences"][:2]
        )
        lines.append(
            "| "
            f"{md_escape(row['action'])} | "
            f"{md_escape(row['priority'])} | "
            f"{md_escape(row['channel_title'])} | "
            f"{md_escape(row['published_at'][:10])} | "
            f"{md_link(row['title'], row['video_url'])} | "
            f"{md_escape(match_text)} | "
            f"{md_escape(official)} | "
            f"{md_escape(setlist)} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-per-channel", type=int, default=15)
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--markdown-out", default=str(MARKDOWN_OUT))
    args = parser.parse_args()
    review = build_review(
        load_json(VOICES, []),
        load_json(REGISTRY, {}),
        load_json(PUBLIC_EVENTS, []),
        load_json(YOUTUBE_SETLISTS, {}),
        max_per_channel=args.max_per_channel,
    )
    atomic_write_json(args.out, review)
    atomic_write_text(args.markdown_out, render_markdown(review))
    print(f"wrote {args.out} ({review['video_count']} videos, counts={review['counts']})")


if __name__ == "__main__":
    main()
