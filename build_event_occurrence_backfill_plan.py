"""Build an event occurrence backfill plan from harvested YouTube candidates."""

import argparse
import json
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from build_event_occurrence_observations import (
    confidence_for,
    date_clusters,
    series_key,
    stable_id,
    weekday_label,
)


DATA = Path("data")
CANDIDATES = DATA / "youtube_year_backfill_candidates.json"
DECISIONS = DATA / "low_confidence_backfill_decisions.json"
OUT = DATA / "event_occurrence_backfill_plan.json"
MD_OUT = DATA / "event_occurrence_backfill_plan.md"
QUOTE_RE = re.compile(r"[「『【\"]([^」』】\"]{2,60})[」』】\"]")


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


def clean_song_title(value):
    value = re.sub(r"\s+", " ", str(value or "")).strip(" -:：、。")
    value = re.sub(r"^(?:終|ラスト|最後)\s*", "", value)
    if len(value) > 60:
        return ""
    if re.search(r"(盆踊り|祭|大会|日枝神社|山王祭|納涼|東京都|Japan|Tokyo|20\d{2})", value, re.I):
        return ""
    return value


def song_hints_from_candidate(row):
    hints = []
    for song in row.get("setlist_sample") or []:
        title = clean_song_title(song.get("title"))
        if title:
            hints.append({"song_name": title, "source_url": song.get("url") or row.get("video_url")})
    title = row.get("title") or ""
    for match in QUOTE_RE.finditer(title):
        song = clean_song_title(match.group(1))
        if song:
            hints.append({"song_name": song, "source_url": row.get("video_url")})
    if not hints:
        head = re.split(r"\s{2,}|　| - | / |　", title, maxsplit=1)[0]
        song = clean_song_title(head)
        if song and len(song) <= 24:
            hints.append({"song_name": song, "source_url": row.get("video_url")})
    seen = set()
    deduped = []
    for hint in hints:
        key = hint["song_name"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(hint)
    return deduped


def candidate_video(row):
    return {
        "url": row.get("video_url"),
        "video_id": row.get("video_id"),
        "title": row.get("title"),
        "channel": row.get("channel_title"),
        "published_at": row.get("published_at"),
        "score": row.get("score"),
    }


def strong_candidates(payload):
    rows = []
    for row in payload.get("candidates") or []:
        if row.get("status") != "strong":
            continue
        date = row.get("detected_event_date") or ""
        if not date.startswith(f"{row.get('target_year')}-"):
            continue
        rows.append(row)
    return rows


def accepted_low_ids(decisions):
    return {
        row.get("observation_id")
        for row in decisions.get("accept") or []
        if row.get("observation_id")
    }


def build_plan(payload, decisions=None):
    decisions = decisions or {}
    manual_accepts = accepted_low_ids(decisions)
    grouped = defaultdict(lambda: defaultdict(list))
    for row in strong_candidates(payload):
        key = (row.get("event_name") or "", row.get("venue") or "", row.get("target_year"))
        grouped[key][row["detected_event_date"]].append(row)

    observations = []
    for (event_name, venue, year), by_date in sorted(grouped.items()):
        skey = series_key(event_name, venue)
        for dates in date_clusters(by_date.keys()):
            rows = []
            for date in dates:
                rows.extend(by_date[date])
            channels = sorted({row.get("channel_title") for row in rows if row.get("channel_title")})
            videos = [candidate_video(row) for row in sorted(rows, key=lambda item: item.get("score", 0), reverse=True)]
            song_counts = Counter()
            song_urls = defaultdict(set)
            for row in rows:
                for hint in song_hints_from_candidate(row):
                    song_counts[hint["song_name"]] += 1
                    if hint.get("source_url"):
                        song_urls[hint["song_name"]].add(hint["source_url"])
            songs = [
                {
                    "song_name": title,
                    "source_count": count,
                    "source_urls": sorted(song_urls[title])[:10],
                    "source_type": "youtube_backfill_title_observed",
                    "confidence": "observed" if count >= 2 else "hint",
                }
                for title, count in song_counts.most_common(40)
            ]
            observation = {
                "observation_id": stable_id(skey, year, ",".join(dates), "youtube_backfill"),
                "series_key": skey,
                "event_name": event_name,
                "venue": venue,
                "area": rows[0].get("area") or "",
                "year": year,
                "date_start": dates[0],
                "date_end": dates[-1],
                "observed_dates": dates,
                "weekday_start": weekday_label(dates[0]),
                "weekday_end": weekday_label(dates[-1]),
                "source_type": "youtube_backfill_observed",
                "source_video_count": len(videos),
                "source_channels": channels,
                "confidence": confidence_for(len(videos), len(channels), len(dates)),
                "source_videos": videos[:20],
                "songs": songs,
            }
            if observation["observation_id"] in manual_accepts and observation["confidence"] == "low":
                observation["confidence"] = "manual_accept"
                observation["manual_review"] = "accepted_low_confidence"
            observations.append(observation)

    excluded_low = [row for row in observations if row["confidence"] == "low"]
    observations = [row for row in observations if row["confidence"] != "low"]
    observations.sort(key=lambda row: (row["year"], row["event_name"], row["date_start"]))
    years = Counter(str(row["year"]) for row in observations)
    return {
        "generated_by": "build_event_occurrence_backfill_plan.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(CANDIDATES),
        "summary": {
            "observation_count": len(observations),
            "source_video_count": sum(row["source_video_count"] for row in observations),
            "observations_by_year": dict(sorted(years.items())),
            "observations_with_songs": sum(1 for row in observations if row.get("songs")),
            "manual_accepted_low_observation_count": sum(1 for row in observations if row["confidence"] == "manual_accept"),
            "excluded_low_observation_count": len(excluded_low),
            "excluded_low_source_video_count": sum(row["source_video_count"] for row in excluded_low),
        },
        "observations": observations,
        "excluded_low_observations": excluded_low,
    }


def md_cell(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(data):
    lines = [
        "# 年次開催回バックフィル追加プラン",
        "",
        f"- 生成: {data['generated_at']}",
        f"- observation_count: {data['summary']['observation_count']}",
        f"- source_video_count: {data['summary']['source_video_count']}",
        f"- observations_with_songs: {data['summary']['observations_with_songs']}",
        f"- excluded_low_observation_count: {data['summary']['excluded_low_observation_count']}",
        "",
        "| confidence | year | date | event | venue | videos | channels | songs |",
        "| --- | ---: | --- | --- | --- | ---: | ---: | ---: |",
    ]
    for row in data["observations"]:
        date = row["date_start"] if row["date_start"] == row["date_end"] else f"{row['date_start']}〜{row['date_end']}"
        lines.append(
            f"| {row['confidence']} | {row['year']} | {date} | "
            f"{md_cell(row['event_name'])} | {md_cell(row['venue'])} | "
            f"{row['source_video_count']} | {len(row['source_channels'])} | {len(row.get('songs') or [])} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", default=str(CANDIDATES))
    parser.add_argument("--decisions", default=str(DECISIONS))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--md-out", default=str(MD_OUT))
    args = parser.parse_args()

    payload = load_json(args.candidates, {})
    decisions = load_json(args.decisions, {})
    data = build_plan(payload, decisions)
    atomic_write_json(args.out, data)
    atomic_write_text(args.md_out, render_markdown(data))
    print(
        "event occurrence backfill plan: "
        f"observations={data['summary']['observation_count']} "
        f"videos={data['summary']['source_video_count']} "
        f"with_songs={data['summary']['observations_with_songs']}"
    )


if __name__ == "__main__":
    main()
