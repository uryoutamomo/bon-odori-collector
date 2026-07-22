"""Build the review table for videos from active YouTube channels."""

import argparse
import json
import re
import tempfile
import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from youtube_channels.extract_youtube_setlists import compact_url, parse_youtube_event_date, primary_description_text
from youtube_backfill.plan_youtube_event_updates import is_out_of_scope, match_public_event
from youtube_backfill.youtube_title_parts import split_youtube_title


DATA = Path("data")
VOICES = DATA / "voices.json"
REGISTRY = DATA / "youtube_channel_registry.json"
PUBLIC_EVENTS = DATA / "public" / "events_public.json"
YOUTUBE_SETLISTS = DATA / "youtube_setlist_occurrences.json"
OUT = DATA / "youtube_active_video_review.json"
MARKDOWN_OUT = DATA / "youtube_active_video_review.md"
DEFAULT_EXPORT_MAX_PER_CHANNEL = 10000

BON_CONTEXT_RE = re.compile(r"(盆踊り|盆おどり|bon\s*odori|bondance|bon\s*dance|音頭|民踊)", re.I)
NOISY_WEAK_EVIDENCE_CHANNELS = {"Tokyo Hz", "Tokyo Lonely Walker"}
SONG_CLIP_TITLE_RE = re.compile(
    r"[「『\"“][^」』\"”]{1,60}[」』\"”]|"
    r"\s[-ー–]\s*[^/【】]{1,50}|"
    r" by [^/【】]{1,50}|"
    r"(?:盆踊り|Bon Dance|Bon Odori)[ 　]*[0-9０-９]+|"
    r"[0-9０-９]+終?\b",
    re.I,
)
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}
GOOGLE_MAPS_HOSTS = {"goo.gl", "maps.app.goo.gl", "www.google.com", "google.com"}
SOCIAL_HOSTS = {
    "x.com",
    "twitter.com",
    "www.instagram.com",
    "instagram.com",
    "www.facebook.com",
    "facebook.com",
    "www.ebay.com",
    "ebay.com",
    "linktr.ee",
}

PARENT_EVENT_COMPONENT_PATTERNS = (
    (r"GMOシブヤエンタメ祭", "GMOシブヤエンタメ祭", "JAME盆踊り / SHIBUYA MIYASHITA PARK BON DANCE"),
    (r"肉フェス", "肉フェス", "アニメメメ盆踊り"),
    (r"アースデイ東京|Earth Day Tokyo", "アースデイ東京", "イマジン盆踊り部"),
    (r"千住・人情芸術祭", "千住・人情芸術祭", "盆踊りパフォーマンス"),
    (r"戦国武将EXPO|SAMURAIフェス", "戦国武将EXPO / SAMURAIフェス", "盆踊りステージ"),
    (r"AKIBAフェス", "AKIBAフェス", "盆踊りステージ"),
    (r"国立旭通りジューンフェスタ", "国立旭通りジューンフェスタ", "盆踊り企画"),
    (r"大井町縁日|大井蔵王権現神社例大祭", "大井町縁日", "晴盆 / 盆踊り企画"),
    (r"ふるさと応援祭\s*ビールと浴衣de盆踊り", "ふるさと応援祭", "ビールと浴衣de盆踊り"),
    (r"浅草夜祭", "浅草夜祭", "アキバ盆踊り / 盆踊り企画"),
    (r"大阪の祭.*EXPO2025|EXPO2025真夏の陣", "大阪・関西万博 大阪の祭", "盆踊りギネス世界記録企画"),
    (r"渋谷・鹿児島おはら祭|おはら祭", "渋谷・鹿児島おはら祭", "音頭/踊り企画"),
    (r"ニコニコ超会議|超ニコニコ盆踊り", "ニコニコ超会議", "超ニコニコ盆踊り"),
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


def is_noise_url(url):
    parsed = urllib.parse.urlparse(str(url or ""))
    host = parsed.hostname or ""
    path = parsed.path or ""
    if host in GOOGLE_MAPS_HOSTS:
        return True
    if host in SOCIAL_HOSTS:
        return True
    if host in YOUTUBE_HOSTS and (path.startswith("/channel/") or path.startswith("/c/") or path.startswith("/@")):
        return True
    return False


def official_urls(voice):
    urls = []
    for url in voice.get("media_urls") or []:
        if not is_youtube_url(url) and not is_noise_url(url) and url not in urls:
            urls.append(url)
    return urls


def has_bon_context(voice):
    return bool(BON_CONTEXT_RE.search("\n".join([
        voice.get("title") or "",
        primary_description_text(voice.get("text") or ""),
    ])))


def parent_event_component(row):
    haystack = row.get("title") or ""
    if not BON_CONTEXT_RE.search(haystack):
        return None
    for pattern, parent_event_name, component_label in PARENT_EVENT_COMPONENT_PATTERNS:
        if re.search(pattern, haystack, re.I):
            return {
                "parent_event_name": parent_event_name,
                "component_label": component_label,
                "component_reason": "親イベント本体ではなく、年別の盆踊り要素として保持",
            }
    return None


def normalize_series_text(value):
    value = re.sub(r"https?://\S+", " ", str(value or ""))
    value = re.sub(r"20\d{2}[./年]?\s*\d{1,2}[./月]?\s*\d{1,2}日?", " ", value)
    value = re.sub(r"20\d{6}", " ", value)
    value = re.sub(r"#\w+", " ", value)
    value = re.sub(r"\[[0-9０-９]+/[0-9０-９]+\]|\([0-9０-９]+/[0-9０-９]+\)", " ", value)
    value = re.sub(r"\b(?:part|pt)\s*[0-9０-９]+\b", " ", value, flags=re.I)
    value = re.sub(r"[「『][^」』]{1,60}[」』]", " ", value)
    value = re.sub(r"【4K】|【[0-9０-９]K】|\[[0-9０-９]K\]", " ", value, flags=re.I)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def series_label_from_title(title):
    title = str(title or "")
    bracket = re.search(r"【([^】]{4,80})】", title)
    if bracket:
        label = normalize_series_text(bracket.group(1))
        if label:
            return label

    known_patterns = (
        r"山王音頭と民踊大会",
        r"新橋こいち祭",
        r"郡上おどりin青山",
        r"肉フェス\s*2025\s*アニメメメ盆踊り",
        r"国立旭通りジューンフェスタ",
        r"花園神社\s*盆踊り",
        r"自由が丘\s*盆踊り",
        r"丸の内\s*盆踊り",
        r"妖怪盆踊り|妖怪夏祭り",
        r"NO BORDER BON ODORI",
        r"Shibuya Bon Odori",
        r"Hanazono Shrine Bon Odori",
        r"Jiyugaoka Bon Odori",
        r"Marunouchi Bon Odori",
        r"Ebisu Ekimae Bon Dance Festival",
        r"Sumida Kinshicho Kawachi Ondo Bon Odori",
        r"Oku-Asakusa.*?Bon Odori",
        r"Ohdai Bon Odori",
        r"赤坂.*?日枝神社.*?盆踊り",
        r"築地本願寺納涼盆踊り大会",
        r"ふるさと応援祭\s*ビールと浴衣de盆踊り",
        r"靖国神社\s*みたままつり",
        r"居酒屋盆踊り",
        r"奥浅草盆踊り",
        r"戸越宮前盆踊り",
        r"飛鳥山公園.*?盆踊り",
    )
    for pattern in known_patterns:
        match = re.search(pattern, title, re.I)
        if match:
            return normalize_series_text(match.group(0))

    label = normalize_series_text(title)
    label = re.sub(r"^(?:盆踊り|bon\s*dance|bon\s*odori)\s+", "", label, flags=re.I)
    return label[:80]


def suppress_duplicate_review_evidence(rows):
    seen = set()
    for row in rows:
        if row.get("action") not in {
            "review_video_evidence",
            "needs_official_confirmation",
            "bon_component_of_parent_event",
        }:
            continue
        if row.get("matched_public_event") or row.get("setlist_occurrences"):
            continue
        label = series_label_from_title(row.get("title") or "")
        if not label:
            continue
        official_key = row.get("official_urls", [""])[0] if row.get("official_urls") else ""
        key = (
            row.get("channel_id") or row.get("channel_title") or "",
            row.get("detected_event_date") or "",
            label.casefold(),
            official_key,
        )
        if key in seen:
            previous_action = row.get("action")
            row["action"] = "ignore"
            row["priority"] = "low"
            row["auto_review_note"] = (
                "duplicate_parent_event_component"
                if previous_action == "bon_component_of_parent_event"
                else
                "duplicate_official_confirmation"
                if previous_action == "needs_official_confirmation"
                else "duplicate_review_video_evidence"
            )
            continue
        seen.add(key)


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


def date_matches_public_event(detected_date, match):
    if not match:
        return True
    if not detected_date:
        reasons = set(match.get("reasons") or [])
        return bool(reasons & {"event_name_in_youtube", "event_alias_in_youtube"})
    start = match.get("date") or ""
    end = match.get("date_end") or start
    if not start:
        return True
    return start <= detected_date <= end


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


def is_song_clip_fragment(row):
    title = row.get("title") or ""
    if row.get("official_urls") or row.get("matched_public_event") or row.get("setlist_occurrences"):
        return False
    if not row.get("has_bon_context"):
        return False
    if re.search(r"#\s*shorts\b|\bshorts\b", title, re.I):
        row["auto_review_note"] = "shorts_song_fragment"
        return True
    if row.get("parent_event_component") and SONG_CLIP_TITLE_RE.search(title):
        row["auto_review_note"] = "parent_event_song_clip_fragment"
        return True
    return False


def is_noisy_channel_weak_video_evidence(row):
    if row.get("channel_title") not in NOISY_WEAK_EVIDENCE_CHANNELS:
        return False
    if row.get("official_urls") or row.get("matched_public_event") or row.get("setlist_occurrences"):
        return False
    if not row.get("has_bon_context"):
        return False
    row["auto_review_note"] = "noisy_channel_weak_video_evidence"
    return True


def review_action(row):
    if row["out_of_scope"] and not row["matched_public_event"]:
        return "out_of_scope"
    if is_song_clip_fragment(row):
        if row.get("auto_review_note") == "parent_event_song_clip_fragment":
            return "bon_component_of_parent_event"
        return "ignore"
    if is_noisy_channel_weak_video_evidence(row):
        return "ignore"
    if row.get("parent_event_component"):
        return "bon_component_of_parent_event"
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
    if row["action"] == "bon_component_of_parent_event":
        return "normal"
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
        text = primary_description_text(voice.get("text") or "")
        title = voice.get("title") or ""
        candidate = {
            "event_name": title,
            "venue": "",
            "source_video_title": title,
            "description_excerpt": text[:1000],
            "source_channel_title": voice.get("youtube_channel_title") or voice.get("name") or "",
        }
        detected_event_date = parse_youtube_event_date(text, title) or ""
        title_parts = split_youtube_title(title)
        matched_public_event = match_public_event(candidate, public_events)
        if not date_matches_public_event(detected_event_date, matched_public_event):
            matched_public_event = None
        row = {
            "video_id": video_id_from_url(url),
            "video_url": url,
            "source_url": voice.get("url") or "",
            "title": title,
            "channel_id": voice.get("youtube_channel_id") or voice.get("account") or "",
            "channel_title": voice.get("youtube_channel_title") or voice.get("name") or "",
            "published_at": voice.get("date") or "",
            "detected_event_date": detected_event_date,
            **title_parts,
            "has_bon_context": has_bon_context(voice),
            "official_urls": official_urls(voice),
            "matched_public_event": matched_public_event,
            "setlist_occurrences": dedupe_occurrences(setlist_by_url.get(url, [])),
            "out_of_scope": is_out_of_scope(candidate),
            "description_excerpt": text[:240],
        }
        row["parent_event_component"] = parent_event_component(row)
        if row["parent_event_component"]:
            row.update(row["parent_event_component"])
        row["action"] = review_action(row)
        row["priority"] = priority_for(row)
        rows.append(row)
    suppress_duplicate_review_evidence(rows)
    rows.sort(key=lambda row: (
        {"append_existing_event": 0, "needs_official_confirmation": 1, "bon_component_of_parent_event": 2,
         "review_video_evidence": 3, "out_of_scope": 4, "ignore": 5}.get(row["action"], 9),
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
        "| action | priority | channel | published | video | parent_event | match | official_url | setlist |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
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
            f"{md_escape(row.get('parent_event_name', ''))} | "
            f"{md_escape(match_text)} | "
            f"{md_escape(official)} | "
            f"{md_escape(setlist)} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-per-channel", type=int, default=DEFAULT_EXPORT_MAX_PER_CHANNEL)
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
