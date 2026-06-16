"""Build cross-source RDB links across Notion, X, and YouTube snapshots."""

import argparse
import json
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs


DATA = Path("data")
NOTION_DB = DATA / "notion_snapshot.sqlite"
EVIDENCE_DB = DATA / "evidence.sqlite"
YOUTUBE_DB = DATA / "youtube_evidence.sqlite"
OUT_DB = DATA / "bon_odori.sqlite"
OUT_SUMMARY = DATA / "bon_odori_rdb_summary.json"

YOUTUBE_EVIDENCE_RE = re.compile(r"\[youtube_evidence\][^\n]*(?:\n(?!\[youtube_evidence\]).*)*")
YOUTUBE_URL_RE = re.compile(r"https?://(?:www\.)?(?:youtube\.com|youtu\.be)/(?:watch\?v=|shorts/)?[A-Za-z0-9_-]+[^\s、。，)）]*")


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE events (
  event_id TEXT PRIMARY KEY,
  event_name TEXT,
  start_date TEXT,
  end_date TEXT,
  status TEXT,
  detail TEXT,
  source_url TEXT
);

CREATE TABLE venues (
  venue_id TEXT PRIMARY KEY,
  venue_name TEXT,
  area TEXT,
  address TEXT,
  access TEXT,
  scale TEXT
);

CREATE TABLE event_venues (
  event_id TEXT NOT NULL,
  venue_id TEXT NOT NULL,
  PRIMARY KEY (event_id, venue_id)
);

CREATE TABLE songs (
  song_id TEXT PRIMARY KEY,
  song_name TEXT,
  category TEXT,
  status TEXT,
  evidence_count REAL,
  source_url TEXT
);

CREATE TABLE dance_variants (
  dance_variant_id TEXT PRIMARY KEY,
  song_id TEXT NOT NULL,
  display_name TEXT NOT NULL,
  nickname TEXT,
  variant_type TEXT,
  confidence TEXT,
  source_event_id TEXT,
  source_url TEXT,
  notes TEXT
);

CREATE TABLE event_song_links (
  event_id TEXT NOT NULL,
  song_id TEXT,
  song_title TEXT NOT NULL,
  occurrence_key TEXT,
  evidence_id TEXT,
  link_status TEXT NOT NULL,
  link_source TEXT NOT NULL,
  dance_variant_id TEXT,
  notes TEXT,
  PRIMARY KEY (event_id, song_title, occurrence_key, evidence_id, link_source)
);

CREATE TABLE evidence_items (
  evidence_id TEXT PRIMARY KEY,
  platform TEXT NOT NULL,
  evidence_type TEXT NOT NULL,
  source_key TEXT,
  source_id TEXT,
  account_key TEXT,
  title TEXT,
  text_excerpt TEXT,
  url TEXT,
  published_at TEXT,
  detected_event_date TEXT,
  raw_status TEXT,
  raw_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE event_evidence_links (
  event_id TEXT NOT NULL,
  evidence_id TEXT NOT NULL,
  link_status TEXT NOT NULL,
  link_source TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  notes TEXT,
  PRIMARY KEY (event_id, evidence_id, link_source)
);

CREATE TABLE song_evidence_links (
  song_id TEXT,
  song_title TEXT NOT NULL,
  evidence_id TEXT NOT NULL,
  occurrence_key TEXT,
  link_status TEXT NOT NULL,
  link_source TEXT NOT NULL,
  notes TEXT,
  PRIMARY KEY (song_title, evidence_id, occurrence_key, link_source)
);

CREATE TABLE review_queue (
  review_key TEXT PRIMARY KEY,
  review_type TEXT NOT NULL,
  platform TEXT,
  event_id TEXT,
  evidence_id TEXT,
  review_status TEXT NOT NULL,
  priority TEXT,
  reason TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE rdb_issues (
  issue_key TEXT PRIMARY KEY,
  severity TEXT NOT NULL,
  issue_type TEXT NOT NULL,
  description TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_events_name ON events(event_name);
CREATE INDEX idx_events_date ON events(start_date);
CREATE INDEX idx_event_song_event ON event_song_links(event_id);
CREATE INDEX idx_event_song_song ON event_song_links(song_id);
CREATE INDEX idx_event_song_variant ON event_song_links(dance_variant_id);
CREATE INDEX idx_evidence_platform ON evidence_items(platform);
CREATE INDEX idx_event_links_status ON event_evidence_links(link_status);
CREATE INDEX idx_song_links_status ON song_evidence_links(link_status);
CREATE INDEX idx_review_status ON review_queue(review_status);
"""


def json_text(value):
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def norm(value):
    return re.sub(r"[\W_]+", "", str(value or "")).casefold()


def compact_youtube_url(url):
    video_id = youtube_video_id(url)
    return f"https://www.youtube.com/watch?v={video_id}" if video_id else str(url or "")


def youtube_video_id(url):
    parsed = urlparse(str(url or ""))
    host = parsed.hostname or ""
    if host == "youtu.be":
        return parsed.path.strip("/").split("/", 1)[0]
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path.startswith("/shorts/"):
            return parsed.path.split("/shorts/", 1)[1].split("/", 1)[0]
        return (parse_qs(parsed.query).get("v") or [""])[0]
    return ""


def table_rows(db_path, table):
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]


def load_source_data(notion_db=NOTION_DB, evidence_db=EVIDENCE_DB, youtube_db=YOUTUBE_DB):
    return {
        "notion_events": table_rows(notion_db, "notion_events"),
        "notion_venues": table_rows(notion_db, "notion_venues"),
        "notion_songs": table_rows(notion_db, "notion_songs"),
        "notion_relations": table_rows(notion_db, "notion_relations"),
        "source_posts": table_rows(evidence_db, "source_posts"),
        "x_candidate_reviews": table_rows(evidence_db, "x_candidate_post_reviews"),
        "youtube_videos": table_rows(youtube_db, "videos"),
        "youtube_video_matches": table_rows(youtube_db, "video_event_matches"),
        "youtube_occurrences": table_rows(youtube_db, "setlist_occurrences"),
        "youtube_occurrence_videos": table_rows(youtube_db, "occurrence_videos"),
        "youtube_setlist_songs": table_rows(youtube_db, "setlist_songs"),
    }


def parse_notion_youtube_blocks(detail):
    rows = []
    for index, block in enumerate(YOUTUBE_EVIDENCE_RE.findall(detail or ""), start=1):
        label = block.splitlines()[0].replace("[youtube_evidence]", "").strip() or "YouTube証拠"
        urls = []
        songs = []
        detected_date = ""
        channel = ""
        for line in block.splitlines()[1:]:
            raw = line.strip()
            if not raw.startswith("- "):
                continue
            key, sep, value = raw[2:].partition(":")
            if not sep:
                key, sep, value = raw[2:].partition("：")
            if not sep:
                continue
            key = key.strip()
            value = value.strip()
            if key in {"動画", "代表動画"}:
                urls.extend(YOUTUBE_URL_RE.findall(value))
            elif key == "検出日付":
                detected_date = value
            elif key == "チャンネル":
                channel = value
            elif key == "曲目候補":
                songs = [song.strip() for song in value.split(",") if song.strip()]
        rows.append({
            "block_index": index,
            "label": label,
            "video_urls": [compact_youtube_url(url) for url in urls],
            "detected_date": detected_date,
            "channel": channel,
            "songs": songs,
            "raw_block": block,
        })
    return rows


def event_indexes(events, relations, venues):
    by_name_date = {}
    by_name_venue = {}
    by_name = {}
    venue_by_id = {row["venue_id"]: row for row in venues}
    event_venue_ids = {}
    for relation in relations:
        if relation.get("property_name") == "会場":
            event_venue_ids.setdefault(relation["page_id"], set()).add(relation["related_page_id"])
    for event in events:
        event_name_key = norm(event.get("event_name"))
        by_name.setdefault(event_name_key, []).append(event)
        if event.get("start_date"):
            by_name_date[(event_name_key, event.get("start_date"))] = event
        for venue_id in event_venue_ids.get(event["event_id"], set()):
            venue = venue_by_id.get(venue_id) or {}
            by_name_venue[(event_name_key, norm(venue.get("venue_name")))] = event
    return by_name_date, by_name_venue, by_name


def choose_event_for_youtube_match(match, indexes):
    by_name_date, by_name_venue, by_name = indexes
    name_key = norm(match.get("event_name"))
    venue_key = norm(match.get("venue"))
    event_date = match.get("event_date") or ""
    if event_date and (name_key, event_date) in by_name_date:
        return by_name_date[(name_key, event_date)], 0.95, "event_name_date"
    if venue_key and (name_key, venue_key) in by_name_venue:
        return by_name_venue[(name_key, venue_key)], 0.85, "event_name_venue"
    candidates = by_name.get(name_key) or []
    if len(candidates) == 1:
        return candidates[0], 0.65, "event_name_unique"
    return None, 0.0, "unmatched"


def choose_event_for_youtube_occurrence(occurrence, indexes):
    match = {
        "event_name": occurrence.get("canonical_event_name") or occurrence.get("event_name_hint"),
        "venue": occurrence.get("canonical_venue") or occurrence.get("venue"),
        "event_date": occurrence.get("event_date") or "",
    }
    return choose_event_for_youtube_match(match, indexes)


def build_unified_rows(source):
    events = [
        {
            "event_id": row["page_id"],
            "event_name": row.get("event_name") or "",
            "start_date": row.get("start_date") or "",
            "end_date": row.get("end_date") or "",
            "status": row.get("status") or "",
            "detail": row.get("detail") or "",
            "source_url": row.get("source_url") or "",
        }
        for row in source["notion_events"]
    ]
    venues = [
        {
            "venue_id": row["page_id"],
            "venue_name": row.get("venue_name") or "",
            "area": row.get("area") or "",
            "address": row.get("address") or "",
            "access": row.get("access") or "",
            "scale": row.get("scale") or "",
        }
        for row in source["notion_venues"]
    ]
    event_venues = [
        {"event_id": row["page_id"], "venue_id": row["related_page_id"]}
        for row in source["notion_relations"]
        if row.get("property_name") == "会場"
    ]
    songs = [
        {
            "song_id": row["page_id"],
            "song_name": row.get("song_name") or "",
            "category": row.get("category") or "",
            "status": row.get("status") or "",
            "evidence_count": row.get("evidence_count"),
            "source_url": row.get("source_url") or "",
        }
        for row in source["notion_songs"]
    ]
    song_by_norm = {norm(row["song_name"]): row for row in songs if row.get("song_name")}

    evidence = {}
    for row in source["source_posts"]:
        evidence[row["post_key"]] = {
            "evidence_id": row["post_key"],
            "platform": row["platform"],
            "evidence_type": "post" if row["platform"] == "x" else "video",
            "source_key": row["source"],
            "source_id": row["post_key"].split(":", 1)[-1],
            "account_key": row["account_key"],
            "title": row.get("title") or "",
            "text_excerpt": (row.get("text") or "")[:500],
            "url": row.get("url") or "",
            "published_at": row.get("published_at") or "",
            "detected_event_date": "",
            "raw_status": "",
            "raw_json": row.get("raw_json") or "{}",
        }
    for row in source["youtube_videos"]:
        evidence_id = f"youtube:{row['video_id']}"
        evidence[evidence_id] = {
            "evidence_id": evidence_id,
            "platform": "youtube",
            "evidence_type": "video",
            "source_key": "youtube_rdb",
            "source_id": row["video_id"],
            "account_key": row.get("channel_id") or "",
            "title": row.get("title") or "",
            "text_excerpt": row.get("description_excerpt") or "",
            "url": row.get("video_url") or "",
            "published_at": row.get("published_at") or "",
            "detected_event_date": row.get("detected_event_date") or "",
            "raw_status": row.get("action") or "",
            "raw_json": json_text(row),
        }
    for occurrence in source["youtube_occurrences"]:
        evidence_id = f"youtube_occurrence:{occurrence['occurrence_key']}"
        evidence[evidence_id] = {
            "evidence_id": evidence_id,
            "platform": "youtube",
            "evidence_type": "setlist_occurrence",
            "source_key": "youtube_setlist_occurrence",
            "source_id": occurrence["occurrence_key"],
            "account_key": "",
            "title": occurrence.get("event_name_hint") or occurrence.get("canonical_event_name") or "",
            "text_excerpt": f"{occurrence.get('venue') or ''} / songs={occurrence.get('song_count') or 0}",
            "url": "",
            "published_at": "",
            "detected_event_date": occurrence.get("event_date") or "",
            "raw_status": occurrence.get("confidence") or "",
            "raw_json": json_text(occurrence),
        }

    indexes = event_indexes(events, source["notion_relations"], venues)
    links = {}
    review = {}
    issues = {}

    def add_link(event_id, evidence_id, status, link_source, confidence, notes=""):
        key = (event_id, evidence_id, link_source)
        links[key] = {
            "event_id": event_id,
            "evidence_id": evidence_id,
            "link_status": status,
            "link_source": link_source,
            "confidence": confidence,
            "notes": notes,
        }

    for event in events:
        for block in parse_notion_youtube_blocks(event.get("detail") or ""):
            if not block["video_urls"]:
                issue_key = f"notion-youtube-block-no-video:{event['event_id']}:{block['block_index']}"
                issues[issue_key] = {
                    "issue_key": issue_key,
                    "severity": "low",
                    "issue_type": "youtube_evidence_block_without_video",
                    "description": f"YouTube evidence block has no parsed video URL: {event.get('event_name')}",
                    "payload_json": json_text(block),
                }
            for url in block["video_urls"]:
                video_id = youtube_video_id(url)
                evidence_id = f"youtube:{video_id}" if video_id else f"youtube_url:{url}"
                if evidence_id not in evidence:
                    evidence[evidence_id] = {
                        "evidence_id": evidence_id,
                        "platform": "youtube",
                        "evidence_type": "video",
                        "source_key": "notion_detail",
                        "source_id": video_id,
                        "account_key": block.get("channel") or "",
                        "title": block.get("label") or "",
                        "text_excerpt": "",
                        "url": url,
                        "published_at": "",
                        "detected_event_date": block.get("detected_date") or "",
                        "raw_status": "already_reflected",
                        "raw_json": json_text(block),
                    }
                add_link(event["event_id"], evidence_id, "already_reflected", "notion_detail_youtube_evidence", 1.0, block["label"])
                review_key = f"already-reflected:{event['event_id']}:{evidence_id}"
                review[review_key] = {
                    "review_key": review_key,
                    "review_type": "event_evidence",
                    "platform": "youtube",
                    "event_id": event["event_id"],
                    "evidence_id": evidence_id,
                    "review_status": "already_reflected",
                    "priority": "done",
                    "reason": "Notion detail contains [youtube_evidence]",
                    "payload_json": json_text(block),
                }

    already_reflected = {(row["event_id"], row["evidence_id"]) for row in links.values()}
    for match in source["youtube_video_matches"]:
        evidence_id = f"youtube:{match['video_id']}"
        event, confidence, reason = choose_event_for_youtube_match(match, indexes)
        if not event:
            review_key = f"youtube-unmatched:{evidence_id}"
            review[review_key] = {
                "review_key": review_key,
                "review_type": "event_evidence",
                "platform": "youtube",
                "event_id": "",
                "evidence_id": evidence_id,
                "review_status": "needs_event_match",
                "priority": "normal",
                "reason": "YouTube event match did not map to Notion event",
                "payload_json": json_text(match),
            }
            continue
        status = "already_reflected" if (event["event_id"], evidence_id) in already_reflected else "matched_existing_event"
        add_link(event["event_id"], evidence_id, status, f"youtube_video_event_match:{reason}", confidence, match.get("reasons_json") or "")
        review_key = f"{status}:{event['event_id']}:{evidence_id}:youtube-match"
        review[review_key] = {
            "review_key": review_key,
            "review_type": "event_evidence",
            "platform": "youtube",
            "event_id": event["event_id"],
            "evidence_id": evidence_id,
            "review_status": status,
            "priority": "high" if status == "matched_existing_event" else "done",
            "reason": f"Matched by {reason}",
            "payload_json": json_text(match),
        }

    youtube_status_priority = {
        "needs_official_confirmation": "high",
        "review_video_evidence": "normal",
        "out_of_scope": "low",
        "ignore": "low",
    }
    linked_evidence = {link["evidence_id"] for link in links.values()}
    for item in evidence.values():
        if item["platform"] != "youtube" or item["evidence_type"] != "video":
            continue
        status = item.get("raw_status") or ""
        if item["evidence_id"] in linked_evidence or status not in youtube_status_priority:
            continue
        review_key = f"youtube-video-status:{item['evidence_id']}"
        review[review_key] = {
            "review_key": review_key,
            "review_type": "event_evidence",
            "platform": "youtube",
            "event_id": "",
            "evidence_id": item["evidence_id"],
            "review_status": status,
            "priority": youtube_status_priority[status],
            "reason": "YouTube active review action",
            "payload_json": item["raw_json"],
        }

    song_links = []
    event_song_links = []
    occurrence_event_matches = {}
    for occurrence in source["youtube_occurrences"]:
        event, confidence, reason = choose_event_for_youtube_occurrence(occurrence, indexes)
        if event:
            occurrence_event_matches[occurrence["occurrence_key"]] = {
                "event": event,
                "confidence": confidence,
                "reason": reason,
            }

    for row in source["youtube_setlist_songs"]:
        title_key = norm(row.get("title"))
        song = song_by_norm.get(title_key)
        evidence_id = f"youtube:{row['video_id']}" if row.get("video_id") else f"youtube_occurrence:{row['occurrence_key']}"
        link_status = "matched_song" if song else "unmatched_song"
        song_links.append({
            "song_id": (song or {}).get("song_id") or "",
            "song_title": row.get("title") or "",
            "evidence_id": evidence_id,
            "occurrence_key": row.get("occurrence_key") or "",
            "link_status": link_status,
            "link_source": "youtube_setlist_song",
            "notes": "",
        })
        occurrence_event = occurrence_event_matches.get(row.get("occurrence_key") or "")
        if occurrence_event:
            event = occurrence_event["event"]
            event_song_links.append({
                "event_id": event["event_id"],
                "song_id": (song or {}).get("song_id") or "",
                "song_title": row.get("title") or "",
                "occurrence_key": row.get("occurrence_key") or "",
                "evidence_id": evidence_id,
                "link_status": link_status,
                "link_source": f"youtube_setlist_song:{occurrence_event['reason']}",
                "dance_variant_id": row.get("dance_variant_id") or "",
                "notes": "",
            })
        if not song:
            review_key = f"unmatched-song:{row.get('occurrence_key')}:{row.get('title')}:{evidence_id}"
            review[review_key] = {
                "review_key": review_key,
                "review_type": "song_evidence",
                "platform": "youtube",
                "event_id": "",
                "evidence_id": evidence_id,
                "review_status": "song_not_in_master",
                "priority": "normal",
                "reason": f"Setlist song not found in Notion song master: {row.get('title')}",
                "payload_json": json_text(row),
            }

    for row in source["x_candidate_reviews"]:
        evidence_id = f"x_candidate_review:{row['handle']}"
        evidence[evidence_id] = {
            "evidence_id": evidence_id,
            "platform": "x",
            "evidence_type": "account_review",
            "source_key": "x_candidate_post_review",
            "source_id": row["handle"],
            "account_key": row["handle"],
            "title": row.get("name") or row["handle"],
            "text_excerpt": row.get("description") or "",
            "url": "",
            "published_at": "",
            "detected_event_date": "",
            "raw_status": row.get("recommendation") or "",
            "raw_json": row.get("raw_json") or "{}",
        }
        review_key = f"x-candidate-review:{row['handle']}"
        review[review_key] = {
            "review_key": review_key,
            "review_type": "source_account",
            "platform": "x",
            "event_id": "",
            "evidence_id": evidence_id,
            "review_status": row.get("recommendation") or "review",
            "priority": "high" if row.get("recommendation") == "promote" else "normal",
            "reason": "X candidate post review recommendation",
            "payload_json": row.get("raw_json") or "{}",
        }

    x_unlinked_count = sum(1 for item in evidence.values() if item["platform"] == "x" and item["evidence_type"] == "post")
    issues["x-post-event-linking-not-implemented"] = {
        "issue_key": "x-post-event-linking-not-implemented",
        "severity": "low",
        "issue_type": "deferred_linking",
        "description": "X post to Notion event matching is not linked yet; kept in evidence_items for later review.",
        "payload_json": json_text({"x_post_count": x_unlinked_count}),
    }

    return {
        "events": events,
        "venues": venues,
        "event_venues": event_venues,
        "songs": songs,
        "dance_variants": source.get("dance_variants") or [],
        "event_song_links": event_song_links,
        "evidence": list(evidence.values()),
        "event_links": list(links.values()),
        "song_links": song_links,
        "review": list(review.values()),
        "issues": list(issues.values()),
    }


def create_db(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".tmp-bon-odori-rdb-", suffix=".sqlite", delete=False) as handle:
        tmp_path = Path(handle.name)
    try:
        with sqlite3.connect(tmp_path) as conn:
            conn.executescript(SCHEMA)
            conn.executemany("INSERT INTO events VALUES (:event_id, :event_name, :start_date, :end_date, :status, :detail, :source_url)", rows["events"])
            conn.executemany("INSERT INTO venues VALUES (:venue_id, :venue_name, :area, :address, :access, :scale)", rows["venues"])
            conn.executemany("INSERT OR IGNORE INTO event_venues VALUES (:event_id, :venue_id)", rows["event_venues"])
            conn.executemany("INSERT INTO songs VALUES (:song_id, :song_name, :category, :status, :evidence_count, :source_url)", rows["songs"])
            conn.executemany(
                """
                INSERT INTO dance_variants VALUES (
                  :dance_variant_id, :song_id, :display_name, :nickname,
                  :variant_type, :confidence, :source_event_id, :source_url, :notes
                )
                """,
                rows["dance_variants"],
            )
            conn.executemany(
                """
                INSERT OR IGNORE INTO event_song_links VALUES (
                  :event_id, :song_id, :song_title, :occurrence_key, :evidence_id,
                  :link_status, :link_source, :dance_variant_id, :notes
                )
                """,
                rows["event_song_links"],
            )
            conn.executemany(
                """
                INSERT INTO evidence_items VALUES (
                  :evidence_id, :platform, :evidence_type, :source_key, :source_id,
                  :account_key, :title, :text_excerpt, :url, :published_at,
                  :detected_event_date, :raw_status, :raw_json
                )
                """,
                rows["evidence"],
            )
            conn.executemany(
                """
                INSERT OR IGNORE INTO event_evidence_links VALUES (
                  :event_id, :evidence_id, :link_status, :link_source, :confidence, :notes
                )
                """,
                rows["event_links"],
            )
            conn.executemany(
                """
                INSERT OR IGNORE INTO song_evidence_links VALUES (
                  :song_id, :song_title, :evidence_id, :occurrence_key, :link_status, :link_source, :notes
                )
                """,
                rows["song_links"],
            )
            conn.executemany(
                """
                INSERT OR IGNORE INTO review_queue VALUES (
                  :review_key, :review_type, :platform, :event_id, :evidence_id,
                  :review_status, :priority, :reason, :payload_json
                )
                """,
                rows["review"],
            )
            conn.executemany("INSERT OR REPLACE INTO rdb_issues VALUES (:issue_key, :severity, :issue_type, :description, :payload_json)", rows["issues"])
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
                "events",
                "venues",
                "event_venues",
                "songs",
                "dance_variants",
                "event_song_links",
                "evidence_items",
                "event_evidence_links",
                "song_evidence_links",
                "review_queue",
                "rdb_issues",
            ]
        }


def build_bon_odori_rdb(
    notion_db=NOTION_DB,
    evidence_db=EVIDENCE_DB,
    youtube_db=YOUTUBE_DB,
    out_db=OUT_DB,
    out_summary=OUT_SUMMARY,
):
    source = load_source_data(notion_db, evidence_db, youtube_db)
    rows = build_unified_rows(source)
    create_db(out_db, rows)
    summary = {
        "generated_by": "build_bon_odori_rdb.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": str(out_db),
        "sources": {
            "notion": str(notion_db),
            "evidence": str(evidence_db),
            "youtube": str(youtube_db),
        },
        "table_counts": table_counts(out_db),
    }
    Path(out_summary).parent.mkdir(parents=True, exist_ok=True)
    Path(out_summary).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notion-db", default=str(NOTION_DB))
    parser.add_argument("--evidence-db", default=str(EVIDENCE_DB))
    parser.add_argument("--youtube-db", default=str(YOUTUBE_DB))
    parser.add_argument("--out-db", default=str(OUT_DB))
    parser.add_argument("--out-summary", default=str(OUT_SUMMARY))
    args = parser.parse_args()

    summary = build_bon_odori_rdb(
        notion_db=Path(args.notion_db),
        evidence_db=Path(args.evidence_db),
        youtube_db=Path(args.youtube_db),
        out_db=Path(args.out_db),
        out_summary=Path(args.out_summary),
    )
    print(
        "bon-odori RDB snapshot: "
        + ", ".join(f"{name}={count}" for name, count in summary["table_counts"].items())
    )


if __name__ == "__main__":
    main()
