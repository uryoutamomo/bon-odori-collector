"""Build event occurrence observations from reviewed YouTube evidence.

This is a staging dataset for the future event_series/event_occurrences model.
It does not write to Notion and does not mark future dates as confirmed.
"""

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DEFAULT_ACTIVE_REVIEW = DATA / "youtube_active_video_review.json"
DEFAULT_SETLIST_OCCURRENCES = DATA / "youtube_setlist_occurrences.json"
DEFAULT_OUT_JSON = DATA / "event_occurrence_observations.json"
DEFAULT_OUT_MD = DATA / "event_occurrence_observations.md"


def read_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data):
    with Path(path).open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def norm(text):
    return re.sub(r"[^0-9A-Za-zぁ-んァ-ン一-龥]", "", text or "").lower()


def stable_id(*parts, length=16):
    raw = "\n".join(str(part or "") for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def year_of(date):
    if not date:
        return None
    match = re.match(r"(\d{4})-\d{2}-\d{2}$", str(date))
    return int(match.group(1)) if match else None


def series_key(name, venue):
    base = f"{norm(name)}__{norm(venue)}"
    return stable_id(base, length=12)


def source_video(row):
    return {
        "url": row.get("video_url") or row.get("source_url"),
        "video_id": row.get("video_id"),
        "title": row.get("title"),
        "channel": row.get("channel_title"),
        "published_at": row.get("published_at"),
    }


def confidence_for(video_count, channel_count, date_count):
    if video_count >= 5 and channel_count >= 2:
        return "high"
    if video_count >= 3 or channel_count >= 2 or date_count >= 2:
        return "medium"
    return "low"


def build_active_observations(rows):
    groups = {}
    skipped = Counter()
    for row in rows:
        matched = row.get("matched_public_event") or {}
        date = row.get("detected_event_date")
        event_name = matched.get("name")
        venue = matched.get("venue")
        year = year_of(date)
        if not event_name or not venue or not year:
            skipped["missing_event_venue_or_date"] += 1
            continue
        key = (event_name, venue, year)
        group = groups.setdefault(key, {
            "event_name": event_name,
            "venue": venue,
            "area": matched.get("area"),
            "year": year,
            "channels": set(),
            "videos_by_date": defaultdict(list),
            "matched_public_event": matched,
        })
        if row.get("channel_title"):
            group["channels"].add(row.get("channel_title"))
        video = source_video(row)
        if video["url"]:
            group["videos_by_date"][date].append(video)

    observations = []
    for (event_name, venue, year), group in sorted(groups.items(), key=lambda item: item[0]):
        channels = sorted(group["channels"])
        skey = series_key(event_name, venue)
        for dates in date_clusters(group["videos_by_date"].keys()):
            videos = []
            for date in dates:
                videos.extend(group["videos_by_date"][date])
            observation_id = stable_id(skey, year, ",".join(dates))
            observations.append({
                "observation_id": observation_id,
                "series_key": skey,
                "event_name": event_name,
                "venue": venue,
                "area": group.get("area"),
                "year": year,
                "date_start": dates[0],
                "date_end": dates[-1],
                "observed_dates": dates,
                "weekday_start": weekday_label(dates[0]),
                "weekday_end": weekday_label(dates[-1]),
                "source_type": "youtube_observed",
                "source_video_count": len(videos),
                "source_channels": channels_for_videos(videos) or channels,
                "confidence": confidence_for(len(videos), len(channels_for_videos(videos) or channels), len(dates)),
                "matched_public_event": group.get("matched_public_event"),
                "source_videos": videos[:20],
                "songs": [],
            })
    return observations, skipped


def date_clusters(dates, max_gap_days=3):
    parsed = []
    for date in dates:
        try:
            parsed.append((datetime.strptime(date, "%Y-%m-%d"), date))
        except (TypeError, ValueError):
            continue
    parsed.sort()
    clusters = []
    current = []
    previous = None
    for dt, raw in parsed:
        if previous is None or (dt - previous).days <= max_gap_days:
            current.append(raw)
        else:
            clusters.append(current)
            current = [raw]
        previous = dt
    if current:
        clusters.append(current)
    return clusters


def channels_for_videos(videos):
    return sorted({video.get("channel") for video in videos if video.get("channel")})


def weekday_label(date):
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
    except (TypeError, ValueError):
        return ""
    return ["月", "火", "水", "木", "金", "土", "日"][dt.weekday()]


def setlist_song_title(item):
    title = (item.get("title") or "").strip()
    title = re.sub(r"\s+", " ", title)
    return title[:120]


def attach_songs(observations, setlist_occurrences):
    observations_by_event = defaultdict(list)
    observations_by_id = {row["observation_id"]: row for row in observations}
    for row in observations:
        observations_by_event[(row["event_name"], row["venue"], row["year"])].append(row)
    attached_occurrences = 0
    skipped = Counter()
    song_counters = defaultdict(Counter)
    song_urls = defaultdict(lambda: defaultdict(set))

    for occurrence in setlist_occurrences:
        matched = occurrence.get("matched_public_event") or {}
        event_name = matched.get("name")
        venue = matched.get("venue")
        year = year_of(occurrence.get("event_date"))
        if not event_name or not venue or not year:
            skipped["missing_match_or_date"] += 1
            continue
        key = (event_name, venue, year)
        observation = observation_for_date(observations_by_event.get(key) or [], occurrence.get("event_date"))
        if not observation:
            skipped["no_observation_group"] += 1
            continue
        attached_occurrences += 1
        observation_id = observation["observation_id"]
        for song in occurrence.get("setlist") or []:
            title = setlist_song_title(song)
            if not title:
                continue
            song_counters[observation_id][title] += 1
            if song.get("url"):
                song_urls[observation_id][title].add(song["url"])

    for observation_id, counter in song_counters.items():
        songs = []
        for title, count in counter.most_common(80):
            songs.append({
                "song_name": title,
                "source_count": count,
                "source_urls": sorted(song_urls[observation_id][title])[:10],
                "source_type": "youtube_setlist_observed",
                "confidence": "observed" if count >= 2 else "hint",
            })
        observations_by_id[observation_id]["songs"] = songs

    return {"attached_occurrences": attached_occurrences, "skipped": dict(skipped)}


def observation_for_date(observations, event_date):
    if not event_date:
        return None
    for row in observations:
        if event_date in row.get("observed_dates", []):
            return row
    for row in observations:
        if row["date_start"] <= event_date <= row["date_end"]:
            return row
    return None


def build_series(observations):
    grouped = defaultdict(list)
    for row in observations:
        grouped[row["series_key"]].append(row)
    series = []
    for skey, rows in sorted(grouped.items()):
        rows = sorted(rows, key=lambda row: row["year"])
        years = sorted({row["year"] for row in rows})
        event_names = Counter(row["event_name"] for row in rows)
        venues = Counter(row["venue"] for row in rows)
        series.append({
            "series_key": skey,
            "canonical_name": event_names.most_common(1)[0][0],
            "usual_venue": venues.most_common(1)[0][0],
            "observed_years": years,
            "observation_count": len(rows),
            "has_3year_window": has_consecutive_years(years, 3),
            "song_years": sorted({row["year"] for row in rows if row.get("songs")}),
        })
    return series


def has_consecutive_years(years, width):
    years = sorted(set(years))
    for idx in range(0, len(years)):
        window = list(range(years[idx], years[idx] + width))
        if all(year in years for year in window):
            return True
    return False


def render_markdown(data):
    lines = [
        "# 年次開催回観測 初期JSON",
        "",
        f"生成: {data['generated_at']}",
        "",
        "## 集計",
        "",
    ]
    summary = data["summary"]
    for key in [
        "observation_count",
        "series_count",
        "source_video_count",
        "observed_years",
        "series_with_3year_window",
        "observations_with_songs",
    ]:
        lines.append(f"- {key}: {summary[key]}")
    lines.extend(["", "## 年別", ""])
    for year, count in summary["observations_by_year"].items():
        lines.append(f"- {year}: {count}")
    lines.extend(["", "## 動画数上位", ""])
    for row in sorted(data["observations"], key=lambda item: item["source_video_count"], reverse=True)[:20]:
        date = row["date_start"] if row["date_start"] == row["date_end"] else f"{row['date_start']}〜{row['date_end']}"
        lines.append(
            f"- {row['event_name']} / {row['venue']} / {date}: "
            f"{row['source_video_count']} videos, songs={len(row.get('songs') or [])}, confidence={row['confidence']}"
        )
    lines.append("")
    return "\n".join(lines)


def build(active_review_path, setlist_path):
    active = read_json(active_review_path, {}).get("rows") or []
    setlists = read_json(setlist_path, {}).get("occurrences") or []
    observations, active_skipped = build_active_observations(active)
    song_summary = attach_songs(observations, setlists)
    series = build_series(observations)
    years = Counter(str(row["year"]) for row in observations)
    summary = {
        "observation_count": len(observations),
        "series_count": len(series),
        "source_video_count": sum(row["source_video_count"] for row in observations),
        "observed_years": sorted(years.keys()),
        "observations_by_year": dict(sorted(years.items())),
        "series_with_3year_window": sum(1 for row in series if row["has_3year_window"]),
        "observations_with_songs": sum(1 for row in observations if row.get("songs")),
        "active_review_skipped": dict(active_skipped),
        "setlist_attach": song_summary,
    }
    return {
        "generated_by": "build_event_occurrence_observations.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "active_review": str(active_review_path),
            "setlist_occurrences": str(setlist_path),
        },
        "summary": summary,
        "series": series,
        "observations": observations,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--active-review", default=str(DEFAULT_ACTIVE_REVIEW))
    parser.add_argument("--setlist-occurrences", default=str(DEFAULT_SETLIST_OCCURRENCES))
    parser.add_argument("--out-json", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--out-md", default=str(DEFAULT_OUT_MD))
    args = parser.parse_args()

    data = build(Path(args.active_review), Path(args.setlist_occurrences))
    write_json(args.out_json, data)
    Path(args.out_md).write_text(render_markdown(data), encoding="utf-8")
    print(
        "event occurrence observations: "
        f"observations={data['summary']['observation_count']} "
        f"series={data['summary']['series_count']} "
        f"videos={data['summary']['source_video_count']} "
        f"with_songs={data['summary']['observations_with_songs']}"
    )


if __name__ == "__main__":
    main()
