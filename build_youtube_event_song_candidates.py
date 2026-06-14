"""Build reviewable event-song links from YouTube discovery candidates."""

import argparse
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path


DATA = Path("data")
EVENT_CANDIDATES = DATA / "youtube_event_candidates.json"
OUT = DATA / "youtube_event_song_candidates.json"
MARKDOWN_OUT = DATA / "youtube_event_song_candidates.md"


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


def event_song_rows(event_candidates):
    rows = []
    for candidate in event_candidates:
        setlist = candidate.get("setlist_sample") or []
        if not setlist:
            continue
        event_key = "yt-event:" + digest(
            candidate.get("event_date"),
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
                "event_date": candidate.get("event_date") or "",
                "song_title": title,
                "song_number": song.get("number") or "",
                "song_url": song.get("url") or "",
                "source_video_url": candidate.get("url") or "",
                "source_video_title": candidate.get("title") or "",
                "source_channel_id": candidate.get("channel_id") or "",
                "source_channel_title": candidate.get("channel_title") or "",
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
    rows = event_song_rows(candidate_rows(payload))
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
