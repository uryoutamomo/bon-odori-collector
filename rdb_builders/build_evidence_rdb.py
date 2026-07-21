"""Build a local SQLite RDB snapshot for X and YouTube evidence data."""

import argparse
import json
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from build_youtube_active_video_review import video_id_from_url
from extract_youtube_setlists import compact_url


DATA = Path("data")
VOICES = DATA / "voices.json"
X_ACCOUNT_SCORES = DATA / "x_account_scores.json"
X_CANDIDATES = DATA / "x_candidate_accounts.json"
X_CANDIDATE_REVIEWS = DATA / "x_candidate_post_review.json"
OUT_DB = DATA / "evidence.sqlite"
OUT_SUMMARY = DATA / "evidence_rdb_summary.json"

SOURCE_PLATFORMS = {
    "x": "x",
    "x_whitelist": "x",
    "x_proactive": "x",
    "x_event_history": "x",
    "youtube": "youtube",
}
URL_RE = re.compile(r"https?://[^\s、。，)）]+")


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE source_accounts (
  platform TEXT NOT NULL,
  account_key TEXT NOT NULL,
  display_name TEXT,
  post_count INTEGER NOT NULL DEFAULT 0,
  first_seen_at TEXT,
  last_seen_at TEXT,
  PRIMARY KEY (platform, account_key)
);

CREATE TABLE source_posts (
  post_key TEXT PRIMARY KEY,
  platform TEXT NOT NULL,
  source TEXT NOT NULL,
  account_key TEXT NOT NULL,
  display_name TEXT,
  title TEXT,
  text TEXT,
  url TEXT,
  published_at TEXT,
  tags_json TEXT NOT NULL DEFAULT '[]',
  raw_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (platform, account_key) REFERENCES source_accounts(platform, account_key)
);

CREATE TABLE post_urls (
  post_key TEXT NOT NULL,
  url TEXT NOT NULL,
  url_kind TEXT NOT NULL,
  PRIMARY KEY (post_key, url),
  FOREIGN KEY (post_key) REFERENCES source_posts(post_key)
);

CREATE TABLE x_account_scores (
  account_key TEXT PRIMARY KEY,
  handle TEXT,
  status TEXT,
  confidence TEXT,
  usefulness_rank TEXT,
  usefulness_rank_number INTEGER,
  usefulness_score REAL,
  score REAL,
  quality_score REAL,
  value_ratio REAL,
  posts_seen INTEGER,
  valuable_posts INTEGER,
  future_schedule_posts INTEGER,
  noise_posts INTEGER,
  value_points REAL,
  last_seen TEXT,
  role_tags_json TEXT NOT NULL DEFAULT '[]',
  top_reasons_json TEXT NOT NULL DEFAULT '{}',
  raw_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE x_candidate_accounts (
  handle TEXT PRIMARY KEY,
  name TEXT,
  description TEXT,
  location TEXT,
  followers INTEGER,
  following INTEGER,
  profile_url TEXT,
  candidate_score REAL,
  reasons_json TEXT NOT NULL DEFAULT '[]',
  discovered_by_json TEXT NOT NULL DEFAULT '[]',
  raw_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE x_candidate_post_reviews (
  handle TEXT PRIMARY KEY,
  name TEXT,
  description TEXT,
  graph_candidate_score REAL,
  tweets_checked INTEGER,
  valuable_posts INTEGER,
  future_schedule_posts INTEGER,
  post_avg_value REAL,
  promote_score REAL,
  recommendation TEXT,
  reason_counts_json TEXT NOT NULL DEFAULT '{}',
  raw_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE x_candidate_review_sample_posts (
  handle TEXT NOT NULL,
  sample_index INTEGER NOT NULL,
  value_score REAL,
  reasons_json TEXT NOT NULL DEFAULT '[]',
  text TEXT,
  url TEXT,
  published_at TEXT,
  PRIMARY KEY (handle, sample_index),
  FOREIGN KEY (handle) REFERENCES x_candidate_post_reviews(handle)
);

CREATE INDEX idx_source_posts_platform_source ON source_posts(platform, source);
CREATE INDEX idx_source_posts_account ON source_posts(platform, account_key);
CREATE INDEX idx_source_posts_published_at ON source_posts(published_at);
CREATE INDEX idx_post_urls_url_kind ON post_urls(url_kind);
CREATE INDEX idx_x_account_scores_rank ON x_account_scores(usefulness_rank, usefulness_score);
CREATE INDEX idx_x_candidate_reviews_recommendation ON x_candidate_post_reviews(recommendation);
"""


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def json_text(value):
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def platform_for_voice(voice):
    source = voice.get("source") or ""
    return SOURCE_PLATFORMS.get(source)


def normalize_x_handle(value):
    value = str(value or "").strip()
    if not value:
        return ""
    return value if value.startswith("@") else f"@{value}"


def x_status_id(url):
    match = re.search(r"/status/(\d+)", str(url or ""))
    return match.group(1) if match else ""


def post_key_for_voice(voice):
    platform = platform_for_voice(voice)
    url = voice.get("url") or ""
    if platform == "x":
        status_id = x_status_id(url)
        if status_id:
            return f"x:{status_id}"
    if platform == "youtube":
        video_id = video_id_from_url(compact_url(url))
        if video_id:
            return f"youtube:{video_id}"
    account = voice.get("account") or voice.get("youtube_channel_id") or ""
    date = voice.get("date") or ""
    return f"{platform}:{account}:{date}:{url}"


def account_key_for_voice(voice):
    platform = platform_for_voice(voice)
    if platform == "youtube":
        return voice.get("youtube_channel_id") or voice.get("account") or ""
    if platform == "x":
        return normalize_x_handle(voice.get("account"))
    return voice.get("account") or ""


def canonical_post_url(voice):
    if platform_for_voice(voice) == "youtube":
        return compact_url(voice.get("url") or "")
    return voice.get("url") or ""


def extract_urls(text):
    urls = []
    for match in URL_RE.finditer(str(text or "")):
        url = match.group(0)
        if url not in urls:
            urls.append(url)
    return urls


def url_kind(url):
    host = urlparse(str(url or "")).hostname or ""
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    if host in {"x.com", "twitter.com", "www.x.com", "www.twitter.com"}:
        return "x"
    if "t.co" in host:
        return "shortlink"
    return "external"


def build_source_rows(voices):
    accounts = {}
    posts = {}
    post_urls = []
    for voice in voices:
        platform = platform_for_voice(voice)
        if not platform:
            continue
        account_key = account_key_for_voice(voice)
        if not account_key:
            continue
        post_key = post_key_for_voice(voice)
        display_name = voice.get("youtube_channel_title") or voice.get("name") or ""
        published_at = voice.get("date") or ""
        account = accounts.setdefault(
            (platform, account_key),
            {
                "platform": platform,
                "account_key": account_key,
                "display_name": display_name,
                "post_count": 0,
                "first_seen_at": published_at,
                "last_seen_at": published_at,
            },
        )
        account["post_count"] += 1
        if display_name and not account.get("display_name"):
            account["display_name"] = display_name
        if published_at:
            if not account.get("first_seen_at") or published_at < account["first_seen_at"]:
                account["first_seen_at"] = published_at
            if not account.get("last_seen_at") or published_at > account["last_seen_at"]:
                account["last_seen_at"] = published_at

        posts[post_key] = {
            "post_key": post_key,
            "platform": platform,
            "source": voice.get("source") or "",
            "account_key": account_key,
            "display_name": display_name,
            "title": voice.get("title") or "",
            "text": voice.get("text") or "",
            "url": canonical_post_url(voice),
            "published_at": published_at,
            "tags_json": json_text(voice.get("tags") or []),
            "raw_json": json_text(voice),
        }
        urls = [canonical_post_url(voice)]
        urls.extend(voice.get("media_urls") or [])
        urls.extend(extract_urls(voice.get("text") or ""))
        for url in dict.fromkeys(url for url in urls if url):
            post_urls.append({
                "post_key": post_key,
                "url": compact_url(url),
                "url_kind": url_kind(url),
            })
    return list(accounts.values()), list(posts.values()), post_urls


def build_x_score_rows(scores):
    rows = []
    for account_key, row in (scores.get("accounts") or {}).items():
        rows.append({
            "account_key": normalize_x_handle(row.get("handle") or account_key),
            "handle": normalize_x_handle(row.get("handle") or account_key),
            "status": row.get("status") or "",
            "confidence": row.get("confidence") or "",
            "usefulness_rank": row.get("usefulness_rank") or "",
            "usefulness_rank_number": row.get("usefulness_rank_number"),
            "usefulness_score": row.get("usefulness_score"),
            "score": row.get("score"),
            "quality_score": row.get("quality_score"),
            "value_ratio": row.get("value_ratio"),
            "posts_seen": row.get("posts_seen"),
            "valuable_posts": row.get("valuable_posts"),
            "future_schedule_posts": row.get("future_schedule_posts"),
            "noise_posts": row.get("noise_posts"),
            "value_points": row.get("value_points"),
            "last_seen": row.get("last_seen") or "",
            "role_tags_json": json_text(row.get("role_tags") or []),
            "top_reasons_json": json_text(row.get("top_reasons") or {}),
            "raw_json": json_text(row),
        })
    return rows


def build_x_candidate_rows(candidates):
    rows = []
    for row in candidates.get("candidates") or []:
        handle = normalize_x_handle(row.get("handle"))
        if not handle:
            continue
        rows.append({
            "handle": handle,
            "name": row.get("name") or "",
            "description": row.get("description") or "",
            "location": row.get("location") or "",
            "followers": row.get("followers"),
            "following": row.get("following"),
            "profile_url": row.get("url") or "",
            "candidate_score": row.get("candidate_score"),
            "reasons_json": json_text(row.get("reasons") or []),
            "discovered_by_json": json_text(row.get("discovered_by") or []),
            "raw_json": json_text(row),
        })
    return rows


def build_x_review_rows(reviews):
    review_rows = []
    sample_rows = []
    for row in reviews.get("results") or []:
        handle = normalize_x_handle(row.get("handle"))
        if not handle:
            continue
        review_rows.append({
            "handle": handle,
            "name": row.get("name") or "",
            "description": row.get("description") or "",
            "graph_candidate_score": row.get("graph_candidate_score"),
            "tweets_checked": row.get("tweets_checked"),
            "valuable_posts": row.get("valuable_posts"),
            "future_schedule_posts": row.get("future_schedule_posts"),
            "post_avg_value": row.get("post_avg_value"),
            "promote_score": row.get("promote_score"),
            "recommendation": row.get("recommendation") or "",
            "reason_counts_json": json_text(row.get("reason_counts") or {}),
            "raw_json": json_text(row),
        })
        for index, sample in enumerate(row.get("sample_valuable_posts") or [], start=1):
            sample_rows.append({
                "handle": handle,
                "sample_index": index,
                "value_score": sample.get("value_score"),
                "reasons_json": json_text(sample.get("reasons") or []),
                "text": sample.get("text") or "",
                "url": sample.get("url") or "",
                "published_at": sample.get("date") or "",
            })
    return review_rows, sample_rows


def create_db(path, accounts, posts, post_urls, x_scores, x_candidates, x_reviews, x_review_samples):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".tmp-evidence-rdb-", suffix=".sqlite", delete=False) as handle:
        tmp_path = Path(handle.name)
    try:
        with sqlite3.connect(tmp_path) as conn:
            conn.executescript(SCHEMA)
            conn.executemany(
                """
                INSERT INTO source_accounts VALUES (
                  :platform, :account_key, :display_name, :post_count, :first_seen_at, :last_seen_at
                )
                """,
                sorted(accounts, key=lambda row: (row["platform"], row["account_key"])),
            )
            conn.executemany(
                """
                INSERT INTO source_posts VALUES (
                  :post_key, :platform, :source, :account_key, :display_name, :title, :text,
                  :url, :published_at, :tags_json, :raw_json
                )
                """,
                sorted(posts, key=lambda row: row["post_key"]),
            )
            conn.executemany(
                "INSERT OR IGNORE INTO post_urls VALUES (:post_key, :url, :url_kind)",
                post_urls,
            )
            conn.executemany(
                """
                INSERT INTO x_account_scores VALUES (
                  :account_key, :handle, :status, :confidence, :usefulness_rank,
                  :usefulness_rank_number, :usefulness_score, :score, :quality_score,
                  :value_ratio, :posts_seen, :valuable_posts, :future_schedule_posts,
                  :noise_posts, :value_points, :last_seen, :role_tags_json,
                  :top_reasons_json, :raw_json
                )
                """,
                sorted(x_scores, key=lambda row: row["account_key"]),
            )
            conn.executemany(
                """
                INSERT INTO x_candidate_accounts VALUES (
                  :handle, :name, :description, :location, :followers, :following,
                  :profile_url, :candidate_score, :reasons_json, :discovered_by_json, :raw_json
                )
                """,
                sorted(x_candidates, key=lambda row: row["handle"]),
            )
            conn.executemany(
                """
                INSERT INTO x_candidate_post_reviews VALUES (
                  :handle, :name, :description, :graph_candidate_score, :tweets_checked,
                  :valuable_posts, :future_schedule_posts, :post_avg_value, :promote_score,
                  :recommendation, :reason_counts_json, :raw_json
                )
                """,
                sorted(x_reviews, key=lambda row: row["handle"]),
            )
            conn.executemany(
                """
                INSERT INTO x_candidate_review_sample_posts VALUES (
                  :handle, :sample_index, :value_score, :reasons_json, :text, :url, :published_at
                )
                """,
                x_review_samples,
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
                "source_accounts",
                "source_posts",
                "post_urls",
                "x_account_scores",
                "x_candidate_accounts",
                "x_candidate_post_reviews",
                "x_candidate_review_sample_posts",
            ]
        }


def build_evidence_rdb(
    voices,
    x_account_scores,
    x_candidates,
    x_candidate_reviews,
    out_db=OUT_DB,
    out_summary=OUT_SUMMARY,
):
    accounts, posts, post_urls = build_source_rows(voices)
    scores = build_x_score_rows(x_account_scores)
    candidates = build_x_candidate_rows(x_candidates)
    reviews, review_samples = build_x_review_rows(x_candidate_reviews)
    create_db(out_db, accounts, posts, post_urls, scores, candidates, reviews, review_samples)
    summary = {
        "generated_by": "build_evidence_rdb.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": str(out_db),
        "sources": {
            "voices": str(VOICES),
            "x_account_scores": str(X_ACCOUNT_SCORES),
            "x_candidate_accounts": str(X_CANDIDATES),
            "x_candidate_post_review": str(X_CANDIDATE_REVIEWS),
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

    summary = build_evidence_rdb(
        load_json(VOICES, []),
        load_json(X_ACCOUNT_SCORES, {"accounts": {}}),
        load_json(X_CANDIDATES, {"candidates": []}),
        load_json(X_CANDIDATE_REVIEWS, {"results": []}),
        out_db=Path(args.out_db),
        out_summary=Path(args.out_summary),
    )
    print(
        "evidence RDB snapshot: "
        + ", ".join(f"{name}={count}" for name, count in summary["table_counts"].items())
    )


if __name__ == "__main__":
    main()
