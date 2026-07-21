"""Discover YouTube channel and event candidates with YouTube Data API."""

import argparse
import json
import os
import re
import tempfile
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from youtube_channels.backfill_youtube_descriptions import best_thumbnail_url, load_env_value
from youtube_channels.extract_youtube_setlists import (
    BON_CONTEXT_RE,
    compact_url,
    extract_setlist,
    infer_event_and_venue,
    parse_youtube_event_date,
)


DATA = Path("data")
KNOWN_CHANNELS = DATA / "youtube_channels.json"
OUT = DATA / "youtube_channel_candidates.json"
EVENTS_OUT = DATA / "youtube_event_candidates.json"
MARKDOWN_OUT = DATA / "youtube_channel_candidates.md"
SEARCH_API_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_API_URL = "https://www.googleapis.com/youtube/v3/videos"
DEFAULT_QUERIES = [
    "盆踊り 2025 曲目",
    "納涼盆踊り 2025",
    "民踊大会 2025",
    "盆踊り 東京 2025",
    "bon odori 2025 japan",
    "郡上おどり 2025 セットリスト",
]
CHAPTER_RE = re.compile(r"^\s*(?:(\d{1,2}:)?\d{1,2}:\d{2})\s*[-:：　 ]+\s*(.+?)\s*$")
CHAPTER_NOISE_RE = re.compile(
    r"(precap|highlight|ハイライト|関連動画|subscribe|チャンネル|map|playlist|"
    r"festival videos|city walk|scramble|shibuya sky|散歩|交差点|rooftop)",
    re.I,
)
SONGISH_RE = re.compile(r"(音頭|踊り|おどり|節|甚句|唄|ソーラン|炭坑|八木|東京|ダンシング|hero|ondo|bushi|song)", re.I)


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


def chunks(items, size):
    for idx in range(0, len(items), size):
        yield items[idx:idx + size]


def youtube_get(url, params):
    query = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{url}?{query}", timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def search_videos(query, api_key, max_results=10, published_after="2025-01-01T00:00:00Z"):
    params = {
        "part": "snippet",
        "type": "video",
        "q": query,
        "maxResults": max_results,
        "order": "relevance",
        "key": api_key,
    }
    if published_after:
        params["publishedAfter"] = published_after
    payload = youtube_get(SEARCH_API_URL, params)
    rows = []
    for item in payload.get("items", []):
        video_id = ((item.get("id") or {}).get("videoId") or "").strip()
        snippet = item.get("snippet") or {}
        if video_id:
            rows.append({
                "video_id": video_id,
                "query": query,
                "title": snippet.get("title") or "",
                "description": snippet.get("description") or "",
                "channel_id": snippet.get("channelId") or "",
                "channel_title": snippet.get("channelTitle") or "",
                "published_at": snippet.get("publishedAt") or "",
                "thumbnail_url": best_thumbnail_url(snippet.get("thumbnails") or {}),
            })
    return rows


def fetch_video_snippets(video_ids, api_key):
    rows = {}
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
                rows[video_id] = snippet
    return rows


def known_channel_ids(payload):
    channels = payload.get("channels") if isinstance(payload, dict) else payload
    if not isinstance(channels, list):
        return set()
    return {row.get("channel_id") for row in channels if row.get("channel_id")}


def bon_context(video):
    text = "\n".join([video.get("title") or "", video.get("description") or ""])
    return bool(BON_CONTEXT_RE.search(text) or re.search(r"bon\s*odori", text, re.I))


def normalize_chapter_title(value):
    value = re.sub(r"\s+", " ", str(value or "")).strip(" -:：、。")
    value = re.sub(r"^第?\d+\s*(?:部|回|曲目?)\s*", "", value)
    value = value.strip("\"'“”「」『』")
    return value


def extract_chapter_setlist(description):
    rows = []
    seen = set()
    for line in str(description or "").splitlines():
        match = CHAPTER_RE.match(line)
        if not match:
            continue
        title = normalize_chapter_title(match.group(2))
        if not title or CHAPTER_NOISE_RE.search(title):
            continue
        if len(title) > 80:
            continue
        if not SONGISH_RE.search(title):
            continue
        key = title.casefold()
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "number": len(rows) + 1,
            "title": title,
            "url": "",
            "source": "chapter",
        })
    return rows


def merge_setlist_candidates(*groups):
    rows = []
    seen = set()
    for group in groups:
        for item in group or []:
            title = normalize_chapter_title(item.get("title") or "")
            key = re.sub(r"\W+", "", title).casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append({**item, "title": title})
    return rows


def filter_numbered_setlist(rows):
    filtered = []
    for item in rows:
        title = normalize_chapter_title(item.get("title") or "")
        if not title:
            continue
        if not SONGISH_RE.search(title):
            continue
        if re.fullmatch(r"20?\d{2}|[0-9０-９]{1,2}", title):
            continue
        if not re.search(r"[一-龥ぁ-んァ-ヶA-Za-z]", title):
            continue
        if len(title) > 50 and re.search(r"(youtube|動画|festival|walk|4k)", title, re.I):
            continue
        filtered.append({**item, "title": title, "source": item.get("source") or "numbered_url"})
    return filtered


def excerpt(value, limit=500):
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def event_name_is_noise(value):
    value = str(value or "").strip()
    if not value:
        return True
    if value.startswith(("#", "※")):
        return True
    return any(marker in value for marker in ("カメラ", "熱暴走", "会場が完全", "このビデオは"))


def enrich_video_candidate(video):
    text = "\n".join([video.get("title") or "", video.get("description") or ""])
    numbered_setlist = filter_numbered_setlist(extract_setlist(video.get("description") or ""))
    chapter_setlist = extract_chapter_setlist(video.get("description") or "")
    setlist = merge_setlist_candidates(numbered_setlist, chapter_setlist)
    voice = {
        "title": video.get("title") or "",
        "text": video.get("description") or "",
        "url": video.get("url") or "",
    }
    event_name, venue, event_key = infer_event_and_venue(voice, {})
    if event_name_is_noise(event_name):
        event_name = video.get("title") or event_name
        venue = event_name
    return {
        **video,
        "url": compact_url(video.get("url") or f"https://www.youtube.com/watch?v={video['video_id']}"),
        "event_date": parse_youtube_event_date(text),
        "event_name_hint": event_name,
        "venue_hint": venue,
        "event_key_hint": event_key,
        "setlist_count": len(setlist),
        "setlist_sample": setlist[:10],
        "description_excerpt": excerpt(video.get("description") or ""),
        "bon_context": bon_context(video),
    }


def score_candidate_channel(row):
    score = 0
    reasons = []
    if row["already_known"]:
        score += 10
        reasons.append("既存チャンネル")
    score += min(row["found_video_count"] * 4, 20)
    if row["bon_context_video_count"]:
        score += min(row["bon_context_video_count"] * 8, 32)
        reasons.append(f"盆踊り文脈{row['bon_context_video_count']}本")
    if row["setlist_candidate_count"]:
        score += min(row["setlist_candidate_count"] * 18, 36)
        reasons.append(f"曲目候補{row['setlist_candidate_count']}本")
    if row["event_date_candidate_count"]:
        score += min(row["event_date_candidate_count"] * 8, 24)
        reasons.append(f"日付抽出{row['event_date_candidate_count']}本")
    score = min(score, 100)
    if score >= 60:
        status = "優先確認"
    elif score >= 30:
        status = "確認"
    else:
        status = "保留"
    return score, status, reasons


def build_candidates(videos, known_ids):
    grouped = defaultdict(list)
    for video in videos:
        grouped[video.get("channel_id") or video.get("channel_title") or "youtube"].append(video)

    channels = []
    event_candidates = []
    for key, rows in grouped.items():
        rows.sort(key=lambda row: row.get("published_at") or "", reverse=True)
        channel = {
            "channel_id": rows[0].get("channel_id") or "",
            "channel_title": rows[0].get("channel_title") or key,
            "channel_url": f"https://www.youtube.com/channel/{rows[0].get('channel_id')}"
            if rows[0].get("channel_id")
            else "",
            "already_known": rows[0].get("channel_id") in known_ids,
            "found_video_count": len(rows),
            "bon_context_video_count": sum(1 for row in rows if row.get("bon_context")),
            "setlist_candidate_count": sum(1 for row in rows if row.get("setlist_count", 0) >= 2),
            "event_date_candidate_count": sum(1 for row in rows if row.get("event_date")),
            "representative_thumbnail_url": next((row.get("thumbnail_url") for row in rows if row.get("thumbnail_url")), ""),
            "sample_videos": rows[:5],
        }
        channel["candidate_score"], channel["review_status"], channel["score_reasons"] = score_candidate_channel(channel)
        channels.append(channel)
        for row in rows:
            if row.get("bon_context") and (row.get("event_date") or row.get("setlist_count", 0) >= 2):
                event_candidates.append({
                    "video_id": row.get("video_id") or "",
                    "url": row.get("url") or "",
                    "title": row.get("title") or "",
                    "channel_id": row.get("channel_id") or "",
                    "channel_title": row.get("channel_title") or "",
                    "published_at": row.get("published_at") or "",
                    "thumbnail_url": row.get("thumbnail_url") or "",
                    "event_date": row.get("event_date") or "",
                    "event_name_hint": row.get("event_name_hint") or "",
                    "venue_hint": row.get("venue_hint") or "",
                    "setlist_count": row.get("setlist_count") or 0,
                    "setlist_sample": row.get("setlist_sample") or [],
                    "description_excerpt": row.get("description_excerpt") or "",
                    "query": row.get("query") or "",
                })

    channels.sort(key=lambda row: (-row["candidate_score"], row["already_known"], row["channel_title"]))
    event_candidates.sort(key=lambda row: (row.get("event_date") or "", row.get("published_at") or ""), reverse=True)
    return channels, event_candidates


def md_escape(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def md_truncate(value, limit=90):
    value = md_escape(value)
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def render_markdown(output):
    lines = [
        "# YouTubeチャンネル・イベント候補",
        "",
        f"- 動画候補: {output['video_count']}件",
        f"- チャンネル候補: {output['channel_candidate_count']}件",
        f"- イベント候補: {output['event_candidate_count']}件",
        f"- 検索語: {', '.join(output['queries'])}",
        "",
        "## 優先チャンネル候補",
        "",
        "| score | 状態 | 既存 | チャンネル | 動画 | 曲目候補 | 日付 | URL |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in output["channels"][:15]:
        lines.append(
            "| "
            f"{row['candidate_score']} | "
            f"{md_escape(row['review_status'])} | "
            f"{'yes' if row['already_known'] else 'no'} | "
            f"{md_escape(row['channel_title'])} | "
            f"{row['found_video_count']} | "
            f"{row['setlist_candidate_count']} | "
            f"{row['event_date_candidate_count']} | "
            f"{md_escape(row['channel_url'])} |"
        )
    lines.extend([
        "",
        "## 曲目つきイベント候補",
        "",
        "| 日付 | 曲目数 | チャンネル | タイトル | URL |",
        "| --- | --- | --- | --- | --- |",
    ])
    for row in [item for item in output["event_candidates"] if item.get("setlist_count", 0) >= 2][:20]:
        lines.append(
            "| "
            f"{md_escape(row.get('event_date'))} | "
            f"{row.get('setlist_count') or 0} | "
            f"{md_escape(row.get('channel_title'))} | "
            f"{md_truncate(row.get('title'))} | "
            f"{md_escape(row.get('url'))} |"
        )
    lines.extend([
        "",
        "## 日付つきイベント候補",
        "",
        "| 日付 | チャンネル | タイトル | URL |",
        "| --- | --- | --- | --- |",
    ])
    for row in [item for item in output["event_candidates"] if item.get("event_date")][:30]:
        lines.append(
            "| "
            f"{md_escape(row.get('event_date'))} | "
            f"{md_escape(row.get('channel_title'))} | "
            f"{md_truncate(row.get('title'), 110)} | "
            f"{md_escape(row.get('url'))} |"
        )
    lines.append("")
    return "\n".join(lines)


def atomic_write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".tmp-", suffix=".md", delete=False
    ) as handle:
        handle.write(text)
        tmp_name = handle.name
    Path(tmp_name).replace(path)


def discover(queries, max_results, api_key, known_channels_path=KNOWN_CHANNELS, published_after="2025-01-01T00:00:00Z"):
    search_rows = []
    seen = set()
    for query in queries:
        for row in search_videos(query, api_key, max_results=max_results, published_after=published_after):
            if row["video_id"] in seen:
                continue
            seen.add(row["video_id"])
            search_rows.append(row)
    snippets = fetch_video_snippets([row["video_id"] for row in search_rows], api_key)
    videos = []
    for row in search_rows:
        snippet = snippets.get(row["video_id"]) or {}
        if snippet:
            row = {
                **row,
                "title": snippet.get("title") or row.get("title") or "",
                "description": snippet.get("description") or row.get("description") or "",
                "channel_id": snippet.get("channelId") or row.get("channel_id") or "",
                "channel_title": snippet.get("channelTitle") or row.get("channel_title") or "",
                "published_at": snippet.get("publishedAt") or row.get("published_at") or "",
                "thumbnail_url": best_thumbnail_url(snippet.get("thumbnails") or {}) or row.get("thumbnail_url") or "",
            }
        row["url"] = f"https://www.youtube.com/watch?v={row['video_id']}"
        videos.append(enrich_video_candidate(row))

    known_ids = known_channel_ids(load_json(known_channels_path, {}))
    channels, event_candidates = build_candidates(videos, known_ids)
    return {
        "generated_by": "discover_youtube_channels.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "queries": queries,
        "max_results_per_query": max_results,
        "published_after": published_after,
        "api_request_count_estimate": len(queries) + ((len(search_rows) + 49) // 50),
        "video_count": len(videos),
        "channel_candidate_count": len(channels),
        "event_candidate_count": len(event_candidates),
        "channels": channels,
        "event_candidates": event_candidates,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", action="append", dest="queries", help="Search query. Repeatable.")
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--published-after", default="2025-01-01T00:00:00Z")
    parser.add_argument("--known-channels", default=str(KNOWN_CHANNELS))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--events-out", default=str(EVENTS_OUT))
    parser.add_argument("--md-out", default=str(MARKDOWN_OUT))
    parser.add_argument("--env", default=".env")
    args = parser.parse_args()

    api_key = load_env_value("YOUTUBE_DATA_API_KEY", args.env)
    if not api_key:
        raise SystemExit("YOUTUBE_DATA_API_KEY is not set")
    queries = args.queries or DEFAULT_QUERIES
    output = discover(
        queries,
        max_results=args.max_results,
        api_key=api_key,
        known_channels_path=Path(args.known_channels),
        published_after=args.published_after,
    )
    atomic_write_json(args.out, output)
    event_output = {
        "generated_by": "discover_youtube_channels.py",
        "generated_at": output["generated_at"],
        "source": args.out,
        "queries": output["queries"],
        "event_candidate_count": output["event_candidate_count"],
        "event_candidates": output["event_candidates"],
    }
    atomic_write_json(args.events_out, event_output)
    atomic_write_text(args.md_out, render_markdown(output))
    print(
        "[youtube-discovery] "
        f"videos={output['video_count']} "
        f"channels={output['channel_candidate_count']} "
        f"events={output['event_candidate_count']} "
        f"requests~={output['api_request_count_estimate']} -> {args.out}, {args.events_out}, {args.md_out}"
    )


if __name__ == "__main__":
    main()
