"""Build a channel-level YouTube source database from collected voices."""

import argparse
import json
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from youtube_channels.backfill_youtube_descriptions import video_id_from_url
from youtube_channels.extract_youtube_setlists import compact_url


DATA = Path("data")
VOICES = DATA / "voices.json"
SETLIST_OCCURRENCES = DATA / "youtube_setlist_occurrences.json"
OUT = DATA / "youtube_channels.json"


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


def youtube_voices(voices):
    return [voice for voice in voices if voice.get("source") == "youtube" and voice.get("url")]


def channel_key(voice):
    return voice.get("youtube_channel_id") or voice.get("account") or voice.get("name") or "youtube"


def add_unique(target, value):
    if value and value not in target:
        target.append(value)


def preferred_thumbnail(videos):
    for video in sorted(videos, key=lambda row: row.get("published_at") or "", reverse=True):
        if video.get("thumbnail_url"):
            return video["thumbnail_url"]
    return ""


def iso_min(values):
    values = [value for value in values if value]
    return min(values) if values else ""


def iso_max(values):
    values = [value for value in values if value]
    return max(values) if values else ""


def build_occurrence_index(setlist_payload):
    occurrences = setlist_payload.get("occurrences") if isinstance(setlist_payload, dict) else setlist_payload
    by_account = defaultdict(list)
    if not isinstance(occurrences, list):
        return by_account
    for occurrence in occurrences:
        for account in occurrence.get("accounts") or []:
            by_account[account].append(occurrence)
    return by_account


def bon_context_score_text(voice):
    text = "\n".join([voice.get("title") or "", voice.get("text") or ""])
    return any(word in text for word in ("盆踊り", "BON ODORI", "Bon Odori", "輪踊り", "民踊", "音頭"))


def score_channel(row):
    score = 0
    reasons = []

    video_points = min(row["video_count"], 20)
    score += video_points
    if video_points:
        reasons.append(f"youtube動画{row['video_count']}本")

    bon_points = min(row["bon_odori_video_count"] * 3, 24)
    score += bon_points
    if bon_points:
        reasons.append(f"盆踊り文脈{row['bon_odori_video_count']}本")

    occurrence_points = min(row["setlist_occurrence_count"] * 10, 30)
    score += occurrence_points
    if occurrence_points:
        reasons.append(f"会場日付つきセットリスト{row['setlist_occurrence_count']}件")

    song_points = min(row["setlist_song_count"] // 3, 20)
    score += song_points
    if song_points:
        reasons.append(f"曲リンク{row['setlist_song_count']}件")

    complete_points = min(row["complete_setlist_count"] * 5, 15)
    score += complete_points
    if complete_points:
        reasons.append(f"まとまった曲目表{row['complete_setlist_count']}件")

    media_points = min(row["media_url_video_count"], 10)
    score += media_points
    if media_points:
        reasons.append(f"説明欄リンクあり{row['media_url_video_count']}本")

    score = min(score, 100)
    if score >= 70:
        status = "優先"
    elif score >= 35:
        status = "通常"
    else:
        status = "候補"
    return score, status, reasons


def sample_videos(videos, limit=5):
    rows = []
    seen = set()
    for video in sorted(videos, key=lambda row: row.get("published_at") or "", reverse=True):
        url = compact_url(video.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        rows.append({
            "url": url,
            "video_id": video_id_from_url(url),
            "title": video.get("title") or "",
            "published_at": video.get("published_at") or "",
            "thumbnail_url": video.get("thumbnail_url") or "",
        })
        if len(rows) >= limit:
            break
    return rows


def event_samples(occurrences, limit=10):
    rows = []
    for occurrence in sorted(
        occurrences,
        key=lambda row: (row.get("event_date") or "", row.get("venue") or ""),
        reverse=True,
    ):
        rows.append({
            "occurrence_key": occurrence.get("occurrence_key") or "",
            "event_name": occurrence.get("canonical_event_name")
            or occurrence.get("event_name_hint")
            or "",
            "venue": occurrence.get("canonical_venue") or occurrence.get("venue") or "",
            "event_date": occurrence.get("event_date") or "",
            "song_count": occurrence.get("song_count") or len(occurrence.get("setlist") or []),
            "confidence": occurrence.get("confidence") or "",
        })
        if len(rows) >= limit:
            break
    return rows


def build_channels(voices, setlist_payload):
    grouped = defaultdict(lambda: {"voices": [], "accounts": [], "names": [], "channel_titles": []})
    for voice in youtube_voices(voices):
        key = channel_key(voice)
        grouped[key]["voices"].append(voice)
        add_unique(grouped[key]["accounts"], voice.get("account") or "")
        add_unique(grouped[key]["names"], voice.get("name") or "")
        add_unique(grouped[key]["channel_titles"], voice.get("youtube_channel_title") or "")

    occurrences_by_account = build_occurrence_index(setlist_payload)
    rows = []
    for key, bucket in grouped.items():
        voices_for_channel = bucket["voices"]
        accounts = sorted(bucket["accounts"])
        occurrence_map = {}
        for account in accounts:
            for occurrence in occurrences_by_account.get(account, []):
                occurrence_map[occurrence.get("occurrence_key") or id(occurrence)] = occurrence
        occurrences = list(occurrence_map.values())
        videos = [
            {
                "url": compact_url(voice.get("url")),
                "title": voice.get("title") or "",
                "published_at": voice.get("youtube_published_at") or voice.get("date") or "",
                "thumbnail_url": voice.get("thumbnail_url") or "",
            }
            for voice in voices_for_channel
        ]
        row = {
            "channel_key": key,
            "channel_id": voices_for_channel[0].get("youtube_channel_id") or "",
            "channel_title": (bucket["channel_titles"] or bucket["names"] or accounts or [key])[0],
            "channel_url": (
                f"https://www.youtube.com/channel/{voices_for_channel[0].get('youtube_channel_id')}"
                if voices_for_channel[0].get("youtube_channel_id")
                else ""
            ),
            "accounts": accounts,
            "feed_names": sorted(bucket["names"]),
            "representative_thumbnail_url": preferred_thumbnail(videos),
            "video_count": len(voices_for_channel),
            "bon_odori_video_count": sum(1 for voice in voices_for_channel if bon_context_score_text(voice)),
            "text_gt_500_count": sum(1 for voice in voices_for_channel if len(voice.get("text") or "") > 500),
            "media_url_video_count": sum(1 for voice in voices_for_channel if voice.get("media_urls")),
            "setlist_occurrence_count": len(occurrences),
            "setlist_song_count": sum(
                occurrence.get("song_count") or len(occurrence.get("setlist") or [])
                for occurrence in occurrences
            ),
            "complete_setlist_count": sum(
                1
                for occurrence in occurrences
                if (occurrence.get("song_count") or len(occurrence.get("setlist") or [])) >= 3
            ),
            "venue_date_success_count": sum(
                1
                for occurrence in occurrences
                if occurrence.get("venue") and occurrence.get("event_date")
            ),
            "first_published_at": iso_min(video.get("published_at") for video in videos),
            "last_published_at": iso_max(video.get("published_at") for video in videos),
            "sample_videos": sample_videos(videos),
            "events": event_samples(occurrences),
            "source": "existing_voices",
        }
        row["auto_score"], row["collection_status"], row["score_reasons"] = score_channel(row)
        rows.append(row)

    rows.sort(key=lambda row: (-row["auto_score"], -row["setlist_song_count"], row["channel_title"]))
    return rows


def build_output(voices_path=VOICES, setlists_path=SETLIST_OCCURRENCES):
    voices = load_json(voices_path, [])
    setlist_payload = load_json(setlists_path, {})
    channels = build_channels(voices, setlist_payload)
    return {
        "generated_by": "build_youtube_channels.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(voices_path),
        "setlist_source": str(setlists_path),
        "channel_count": len(channels),
        "priority_channel_count": sum(1 for row in channels if row.get("collection_status") == "優先"),
        "youtube_voice_count": len(youtube_voices(voices)),
        "channels": channels,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--voices", default=str(VOICES))
    parser.add_argument("--setlists", default=str(SETLIST_OCCURRENCES))
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    output = build_output(Path(args.voices), Path(args.setlists))
    atomic_write_json(args.out, output)
    print(
        "[youtube-channels] "
        f"channels={output['channel_count']} "
        f"priority={output['priority_channel_count']} "
        f"voices={output['youtube_voice_count']} -> {args.out}"
    )


if __name__ == "__main__":
    main()
