"""Build a local SQLite RDB snapshot for YouTube evidence data."""

import argparse
import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from build_youtube_active_video_review import video_id_from_url
from youtube_channels.extract_youtube_setlists import compact_url


DATA = Path("data")
VOICES = DATA / "voices.json"
REGISTRY = DATA / "youtube_channel_registry.json"
ACTIVE_REVIEW = DATA / "youtube_active_video_review.json"
SETLIST_OCCURRENCES = DATA / "youtube_setlist_occurrences.json"
PUBLIC_EVENTS = DATA / "public" / "events_public.json"
OUT_DB = DATA / "youtube_evidence.sqlite"
OUT_SUMMARY = DATA / "youtube_rdb_summary.json"

YOUTUBE_HOST_MARKERS = ("youtube.com", "youtu.be")


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE channels (
  channel_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  channel_url TEXT,
  rss_url TEXT,
  status TEXT,
  collection_enabled INTEGER NOT NULL DEFAULT 0,
  priority TEXT,
  scope TEXT,
  date_validation_required INTEGER NOT NULL DEFAULT 0,
  trusted_for_json TEXT NOT NULL DEFAULT '[]',
  metrics_json TEXT NOT NULL DEFAULT '{}',
  added_at TEXT,
  last_reviewed_at TEXT,
  last_collected_at TEXT
);

CREATE TABLE videos (
  video_id TEXT PRIMARY KEY,
  video_url TEXT NOT NULL UNIQUE,
  channel_id TEXT,
  title TEXT NOT NULL,
  description_excerpt TEXT,
  published_at TEXT,
  detected_event_date TEXT,
  thumbnail_url TEXT,
  has_bon_context INTEGER NOT NULL DEFAULT 0,
  action TEXT,
  priority TEXT,
  out_of_scope INTEGER NOT NULL DEFAULT 0,
  source_url TEXT,
  FOREIGN KEY (channel_id) REFERENCES channels(channel_id)
);

CREATE TABLE video_official_urls (
  video_id TEXT NOT NULL,
  url TEXT NOT NULL,
  PRIMARY KEY (video_id, url),
  FOREIGN KEY (video_id) REFERENCES videos(video_id)
);

CREATE TABLE video_event_matches (
  video_id TEXT PRIMARY KEY,
  event_name TEXT,
  venue TEXT,
  event_date TEXT,
  date_end TEXT,
  area TEXT,
  score INTEGER,
  reasons_json TEXT NOT NULL DEFAULT '[]',
  FOREIGN KEY (video_id) REFERENCES videos(video_id)
);

CREATE TABLE setlist_occurrences (
  occurrence_key TEXT PRIMARY KEY,
  event_key_hint TEXT,
  event_name_hint TEXT,
  canonical_event_name TEXT,
  venue TEXT,
  canonical_venue TEXT,
  event_date TEXT,
  source_video_count INTEGER NOT NULL DEFAULT 0,
  song_count INTEGER NOT NULL DEFAULT 0,
  confidence TEXT,
  role TEXT,
  act TEXT,
  reliability_key TEXT,
  matched_public_event_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE occurrence_videos (
  occurrence_key TEXT NOT NULL,
  video_id TEXT NOT NULL,
  video_url TEXT NOT NULL,
  account TEXT,
  title TEXT,
  published_at TEXT,
  thumbnail_url TEXT,
  PRIMARY KEY (occurrence_key, video_id),
  FOREIGN KEY (occurrence_key) REFERENCES setlist_occurrences(occurrence_key)
);

CREATE TABLE setlist_songs (
  occurrence_key TEXT NOT NULL,
  position INTEGER NOT NULL,
  title TEXT NOT NULL,
  video_url TEXT,
  video_id TEXT,
  PRIMARY KEY (occurrence_key, position, title, video_url),
  FOREIGN KEY (occurrence_key) REFERENCES setlist_occurrences(occurrence_key)
);

CREATE INDEX idx_videos_channel ON videos(channel_id);
CREATE INDEX idx_videos_action ON videos(action);
CREATE INDEX idx_videos_detected_event_date ON videos(detected_event_date);
CREATE INDEX idx_occurrence_videos_video ON occurrence_videos(video_id);
CREATE INDEX idx_setlist_occurrences_event_date ON setlist_occurrences(event_date);
"""


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def json_text(value):
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def bool_int(value):
    return 1 if value else 0


def is_youtube_url(url):
    value = str(url or "")
    return any(marker in value for marker in YOUTUBE_HOST_MARKERS)


def official_urls_from_voice(voice):
    urls = []
    for url in voice.get("media_urls") or []:
        if url and not is_youtube_url(url) and url not in urls:
            urls.append(url)
    return urls


def build_thumbnail_index(setlists):
    thumbnails = {}
    for occurrence in setlists.get("occurrences") or []:
        for video in occurrence.get("source_videos") or []:
            url = compact_url(video.get("url"))
            video_id = video_id_from_url(url)
            if video_id and video.get("thumbnail_url"):
                thumbnails[video_id] = video.get("thumbnail_url")
    return thumbnails


def registry_channels(registry):
    rows = {}
    for channel in registry.get("channels") or []:
        channel_id = channel.get("channel_id") or ""
        if not channel_id:
            continue
        rows[channel_id] = {
            "channel_id": channel_id,
            "title": channel.get("channel_title") or channel_id,
            "channel_url": channel.get("channel_url") or "",
            "rss_url": channel.get("rss_url") or "",
            "status": channel.get("status") or "",
            "collection_enabled": bool_int(channel.get("collection_enabled")),
            "priority": channel.get("priority") or "",
            "scope": channel.get("scope") or "",
            "date_validation_required": bool_int(channel.get("date_validation_required")),
            "trusted_for_json": json_text(channel.get("trusted_for") or []),
            "metrics_json": json_text(channel.get("metrics") or {}),
            "added_at": channel.get("added_at") or "",
            "last_reviewed_at": channel.get("last_reviewed_at") or "",
            "last_collected_at": channel.get("last_collected_at") or "",
        }
    return rows


def review_index(active_review):
    return {
        row.get("video_id"): row
        for row in active_review.get("rows") or []
        if row.get("video_id")
    }


def youtube_voice_videos(voices, review_rows, thumbnails):
    rows = {}
    official_urls = {}
    for voice in voices:
        if voice.get("source") != "youtube":
            continue
        url = compact_url(voice.get("url") or "")
        video_id = video_id_from_url(url)
        if not video_id:
            continue
        review = review_rows.get(video_id) or {}
        rows[video_id] = {
            "video_id": video_id,
            "video_url": url,
            "channel_id": voice.get("youtube_channel_id") or voice.get("account") or review.get("channel_id") or "",
            "title": voice.get("title") or review.get("title") or video_id,
            "description_excerpt": review.get("description_excerpt") or (voice.get("text") or "")[:240],
            "published_at": voice.get("date") or review.get("published_at") or "",
            "detected_event_date": review.get("detected_event_date") or "",
            "thumbnail_url": thumbnails.get(video_id, ""),
            "has_bon_context": bool_int(review.get("has_bon_context")),
            "action": review.get("action") or "",
            "priority": review.get("priority") or "",
            "out_of_scope": bool_int(review.get("out_of_scope")),
            "source_url": voice.get("url") or review.get("source_url") or url,
        }
        official_urls[video_id] = list(dict.fromkeys(
            list(review.get("official_urls") or []) + official_urls_from_voice(voice)
        ))
    return rows, official_urls


def review_event_matches(review_rows):
    rows = []
    for video_id, row in review_rows.items():
        match = row.get("matched_public_event") or {}
        if not match:
            continue
        rows.append({
            "video_id": video_id,
            "event_name": match.get("name") or "",
            "venue": match.get("venue") or "",
            "event_date": match.get("date") or "",
            "date_end": match.get("date_end") or "",
            "area": match.get("area") or "",
            "score": int(match.get("score") or 0),
            "reasons_json": json_text(match.get("reasons") or []),
        })
    return rows


def setlist_rows(setlists):
    occurrences = []
    occurrence_videos = []
    songs = []
    for occurrence in setlists.get("occurrences") or []:
        occurrence_key = occurrence.get("occurrence_key") or ""
        if not occurrence_key:
            continue
        occurrences.append({
            "occurrence_key": occurrence_key,
            "event_key_hint": occurrence.get("event_key_hint") or "",
            "event_name_hint": occurrence.get("event_name_hint") or "",
            "canonical_event_name": occurrence.get("canonical_event_name") or "",
            "venue": occurrence.get("venue") or "",
            "canonical_venue": occurrence.get("canonical_venue") or "",
            "event_date": occurrence.get("event_date") or "",
            "source_video_count": int(occurrence.get("source_video_count") or 0),
            "song_count": int(occurrence.get("song_count") or 0),
            "confidence": occurrence.get("confidence") or "",
            "role": occurrence.get("role") or "",
            "act": occurrence.get("act") or "",
            "reliability_key": occurrence.get("reliability_key") or "",
            "matched_public_event_json": json_text(occurrence.get("matched_public_event") or {}),
        })
        for video in occurrence.get("source_videos") or []:
            video_url = compact_url(video.get("url") or "")
            video_id = video_id_from_url(video_url)
            if not video_id:
                continue
            occurrence_videos.append({
                "occurrence_key": occurrence_key,
                "video_id": video_id,
                "video_url": video_url,
                "account": video.get("account") or "",
                "title": video.get("title") or "",
                "published_at": video.get("published_at") or "",
                "thumbnail_url": video.get("thumbnail_url") or "",
            })
        for song in occurrence.get("setlist") or []:
            video_url = compact_url(song.get("url") or "")
            songs.append({
                "occurrence_key": occurrence_key,
                "position": int(song.get("number") or 0),
                "title": song.get("title") or "",
                "video_url": video_url,
                "video_id": video_id_from_url(video_url),
            })
    return occurrences, occurrence_videos, songs


def ensure_channels_for_videos(channels, videos):
    for video in videos.values():
        channel_id = video.get("channel_id") or ""
        if channel_id and channel_id not in channels:
            channels[channel_id] = {
                "channel_id": channel_id,
                "title": channel_id,
                "channel_url": "",
                "rss_url": "",
                "status": "unregistered",
                "collection_enabled": 0,
                "priority": "",
                "scope": "",
                "date_validation_required": 0,
                "trusted_for_json": "[]",
                "metrics_json": "{}",
                "added_at": "",
                "last_reviewed_at": "",
                "last_collected_at": "",
            }


def create_db(path, channels, videos, official_urls, event_matches, occurrences, occurrence_videos, songs):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".tmp-youtube-rdb-", suffix=".sqlite", delete=False) as handle:
        tmp_path = Path(handle.name)
    try:
        with sqlite3.connect(tmp_path) as conn:
            conn.executescript(SCHEMA)
            conn.executemany(
                """
                INSERT INTO channels VALUES (
                  :channel_id, :title, :channel_url, :rss_url, :status, :collection_enabled,
                  :priority, :scope, :date_validation_required, :trusted_for_json,
                  :metrics_json, :added_at, :last_reviewed_at, :last_collected_at
                )
                """,
                sorted(channels.values(), key=lambda row: row["channel_id"]),
            )
            conn.executemany(
                """
                INSERT INTO videos VALUES (
                  :video_id, :video_url, :channel_id, :title, :description_excerpt,
                  :published_at, :detected_event_date, :thumbnail_url, :has_bon_context,
                  :action, :priority, :out_of_scope, :source_url
                )
                """,
                sorted(videos.values(), key=lambda row: row["video_id"]),
            )
            conn.executemany(
                "INSERT INTO video_official_urls VALUES (:video_id, :url)",
                [
                    {"video_id": video_id, "url": url}
                    for video_id, urls in official_urls.items()
                    if video_id in videos
                    for url in urls
                ],
            )
            conn.executemany(
                """
                INSERT INTO video_event_matches VALUES (
                  :video_id, :event_name, :venue, :event_date, :date_end, :area, :score, :reasons_json
                )
                """,
                [row for row in event_matches if row["video_id"] in videos],
            )
            conn.executemany(
                """
                INSERT INTO setlist_occurrences VALUES (
                  :occurrence_key, :event_key_hint, :event_name_hint, :canonical_event_name,
                  :venue, :canonical_venue, :event_date, :source_video_count, :song_count,
                  :confidence, :role, :act, :reliability_key, :matched_public_event_json
                )
                """,
                occurrences,
            )
            conn.executemany(
                """
                INSERT INTO occurrence_videos VALUES (
                  :occurrence_key, :video_id, :video_url, :account, :title, :published_at, :thumbnail_url
                )
                """,
                occurrence_videos,
            )
            conn.executemany(
                """
                INSERT INTO setlist_songs VALUES (
                  :occurrence_key, :position, :title, :video_url, :video_id
                )
                """,
                songs,
            )
            conn.commit()
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def table_counts(path):
    with sqlite3.connect(path) as conn:
        return {
            name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            for name in [
                "channels",
                "videos",
                "video_official_urls",
                "video_event_matches",
                "setlist_occurrences",
                "occurrence_videos",
                "setlist_songs",
            ]
        }


def build_youtube_rdb(
    voices,
    registry,
    active_review,
    setlists,
    out_db=OUT_DB,
    out_summary=OUT_SUMMARY,
):
    thumbnails = build_thumbnail_index(setlists)
    channels = registry_channels(registry)
    reviews = review_index(active_review)
    videos, official_urls = youtube_voice_videos(voices, reviews, thumbnails)
    ensure_channels_for_videos(channels, videos)
    event_matches = review_event_matches(reviews)
    occurrences, occurrence_videos, songs = setlist_rows(setlists)
    create_db(out_db, channels, videos, official_urls, event_matches, occurrences, occurrence_videos, songs)
    summary = {
        "generated_by": "build_youtube_rdb.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": str(out_db),
        "sources": {
            "voices": str(VOICES),
            "registry": str(REGISTRY),
            "active_review": str(ACTIVE_REVIEW),
            "setlist_occurrences": str(SETLIST_OCCURRENCES),
        },
        "table_counts": table_counts(out_db),
    }
    Path(out_summary).parent.mkdir(parents=True, exist_ok=True)
    Path(out_summary).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-db", default=str(OUT_DB))
    parser.add_argument("--out-summary", default=str(OUT_SUMMARY))
    args = parser.parse_args()

    summary = build_youtube_rdb(
        load_json(VOICES, []),
        load_json(REGISTRY, {"channels": []}),
        load_json(ACTIVE_REVIEW, {"rows": []}),
        load_json(SETLIST_OCCURRENCES, {"occurrences": []}),
        out_db=Path(args.out_db),
        out_summary=Path(args.out_summary),
    )
    print(
        "youtube RDB snapshot: "
        + ", ".join(f"{name}={count}" for name, count in summary["table_counts"].items())
    )


if __name__ == "__main__":
    main()
