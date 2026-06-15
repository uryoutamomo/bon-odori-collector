"""Build reviewable event-song links from YouTube discovery candidates."""

import argparse
import hashlib
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from song_occurrences import parse_event_date


DATA = Path("data")
EVENT_CANDIDATES = DATA / "youtube_event_candidates.json"
OUT = DATA / "youtube_event_song_candidates.json"
MARKDOWN_OUT = DATA / "youtube_event_song_candidates.md"
YOUTUBE_CHANNEL_CANDIDATES = DATA / "youtube_channel_candidates.json"
CHAPTER_RE = re.compile(r"^\s*(?:(\d{1,2}:)?\d{1,2}:\d{2})\s*[-:：　 ]+\s*(.+?)\s*$")
CHAPTER_NOISE_RE = re.compile(
    r"(op|end|encore|アンコール|提灯|lantern|map|subscribe|チャンネル|"
    r"関連動画|opening music|ending music|background music|precap|"
    r"bon odori part|festival|tokyo sky tree|traditional dance)",
    re.I,
)


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


def digest(*parts):
    raw = "\0".join(str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def candidate_rows(payload):
    rows = payload.get("event_candidates") if isinstance(payload, dict) else payload
    return rows if isinstance(rows, list) else []


def compact_url(url):
    url = str(url or "").strip()
    if "youtu.be/" in url:
        video_id = url.split("youtu.be/", 1)[1].split("?", 1)[0].split("&", 1)[0]
        return f"https://www.youtube.com/watch?v={video_id}"
    return url


def channel_video_descriptions(payload):
    descriptions = {}
    if not isinstance(payload, dict):
        return descriptions
    for channel in payload.get("channels") or []:
        for video in channel.get("sample_videos") or []:
            url = compact_url(video.get("url") or "")
            description = video.get("description") or ""
            if url and description:
                descriptions[url] = description
    for video in payload.get("event_candidates") or []:
        url = compact_url(video.get("url") or "")
        description = video.get("description") or ""
        if url and description:
            descriptions[url] = description
    return descriptions


def normalize_chapter_title(value):
    value = re.sub(r"\s+", " ", str(value or "")).strip(" -:：、。")
    value = re.sub(r"【[^】]{1,30}】", "", value).strip()
    return value


def extract_chapter_songs(description):
    rows = []
    seen = set()
    for line in str(description or "").splitlines():
        match = CHAPTER_RE.match(line)
        if not match:
            continue
        title = normalize_chapter_title(match.group(2))
        if not title or CHAPTER_NOISE_RE.search(title):
            continue
        if len(title) > 90:
            continue
        key = re.sub(r"\W+", "", title).casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append({
            "number": len(rows) + 1,
            "title": title,
            "url": "",
            "source": "chapter",
        })
    return rows


def enriched_setlist(candidate, description_by_url):
    setlist = list(candidate.get("setlist_sample") or [])
    url = compact_url(candidate.get("url") or "")
    description = description_by_url.get(url) or ""
    chapter_songs = extract_chapter_songs(description)
    if len(chapter_songs) <= len(setlist):
        return setlist
    return chapter_songs


def candidate_event_date(candidate, description_by_url):
    existing = candidate.get("event_date") or ""
    if existing:
        return existing
    url = compact_url(candidate.get("url") or "")
    description = description_by_url.get(url) or ""
    return parse_event_date(description, candidate.get("description_excerpt"), candidate.get("title")) or ""


def event_song_rows(event_candidates, description_by_url=None):
    description_by_url = description_by_url or {}
    rows = []
    for candidate in event_candidates:
        setlist = enriched_setlist(candidate, description_by_url)
        if not setlist:
            continue
        event_date = candidate_event_date(candidate, description_by_url)
        event_key = "yt-event:" + digest(
            event_date,
            candidate.get("event_name_hint") or candidate.get("title"),
            candidate.get("url"),
        )
        for song in setlist:
            title = song.get("title") or ""
            if not title:
                continue
            rows.append({
                "candidate_key": "yt-song:" + digest(event_key, title, song.get("url") or candidate.get("url")),
                "event_key": event_key,
                "event_name": candidate.get("event_name_hint") or candidate.get("title") or "",
                "venue": candidate.get("venue_hint") or "",
                "event_date": event_date,
                "song_title": title,
                "song_number": song.get("number") or "",
                "song_url": song.get("url") or "",
                "source_video_url": candidate.get("url") or "",
                "source_video_title": candidate.get("title") or "",
                "source_channel_id": candidate.get("channel_id") or "",
                "source_channel_title": candidate.get("channel_title") or "",
                "source_published_at": candidate.get("published_at") or "",
                "thumbnail_url": candidate.get("thumbnail_url") or "",
                "description_excerpt": candidate.get("description_excerpt") or "",
                "evidence_type": song.get("source") or "youtube_description",
                "review_status": "未確認",
            })
    rows.sort(key=lambda row: (row["event_date"], row["event_name"], row["song_number"], row["song_title"]), reverse=True)
    return rows


def group_events(rows):
    events = {}
    for row in rows:
        event = events.setdefault(row["event_key"], {
            "event_key": row["event_key"],
            "event_name": row["event_name"],
            "venue": row["venue"],
            "event_date": row["event_date"],
            "source_video_url": row["source_video_url"],
            "source_video_title": row["source_video_title"],
            "source_channel_id": row["source_channel_id"],
            "source_channel_title": row["source_channel_title"],
            "source_published_at": row["source_published_at"],
            "thumbnail_url": row["thumbnail_url"],
            "description_excerpt": row.get("description_excerpt") or "",
            "song_count": 0,
            "songs": [],
        })
        event["songs"].append({
            "candidate_key": row["candidate_key"],
            "title": row["song_title"],
            "number": row["song_number"],
            "url": row["song_url"],
            "evidence_type": row["evidence_type"],
            "review_status": row["review_status"],
        })
        event["song_count"] = len(event["songs"])
    return sorted(events.values(), key=lambda row: (row["event_date"], row["song_count"]), reverse=True)


def build_output(payload):
    description_by_url = channel_video_descriptions(load_json(YOUTUBE_CHANNEL_CANDIDATES, {}))
    rows = event_song_rows(candidate_rows(payload), description_by_url)
    events = group_events(rows)
    return {
        "generated_by": "build_youtube_event_song_candidates.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(EVENT_CANDIDATES),
        "event_count": len(events),
        "event_song_candidate_count": len(rows),
        "events": events,
        "rows": rows,
    }


def md_escape(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def md_truncate(value, limit=100):
    value = md_escape(value)
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def render_markdown(output):
    lines = [
        "# YouTubeイベント曲候補",
        "",
        f"- イベント候補: {output['event_count']}件",
        f"- 曲候補: {output['event_song_candidate_count']}件",
        "",
        "| 日付 | 曲数 | チャンネル | イベント/動画 | URL |",
        "| --- | --- | --- | --- | --- |",
    ]
    for event in output["events"][:30]:
        lines.append(
            "| "
            f"{md_escape(event['event_date'])} | "
            f"{event['song_count']} | "
            f"{md_escape(event['source_channel_title'])} | "
            f"{md_truncate(event['event_name'] or event['source_video_title'])} | "
            f"{md_escape(event['source_video_url'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(EVENT_CANDIDATES))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--md-out", default=str(MARKDOWN_OUT))
    args = parser.parse_args()

    output = build_output(load_json(args.input, {}))
    output["source"] = args.input
    atomic_write_json(args.out, output)
    atomic_write_text(args.md_out, render_markdown(output))
    print(
        "[youtube-event-songs] "
        f"events={output['event_count']} "
        f"rows={output['event_song_candidate_count']} -> {args.out}, {args.md_out}"
    )


if __name__ == "__main__":
    main()
