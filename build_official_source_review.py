#!/usr/bin/env python3
"""Build a human review queue for recurring-event official source URLs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
DEFAULT_BLOG_CANDIDATES = ROOT / "data/blog_registration_candidates.json"
DEFAULT_YOUTUBE_VALIDATION = ROOT / "data/youtube_2025_official_candidate_validation.json"
DEFAULT_EVERGREEN = ROOT / "data/evergreen_events.json"
DEFAULT_PUBLIC_EVENTS = ROOT / "data/public/events_public.json"
DEFAULT_OUT_JSON = ROOT / "data/official_source_review_candidates.json"
DEFAULT_OUT_MD = ROOT / "data/official_source_review_candidates.md"

EXCLUDED_DOMAINS = {
    "minato-bon-odori.blogspot.com",
    "www.youtube.com",
    "youtube.com",
    "youtu.be",
    "x.com",
    "twitter.com",
    "t.co",
}
SOCIAL_DOMAINS = {
    "facebook.com",
    "www.facebook.com",
    "instagram.com",
    "www.instagram.com",
}
OFFICIAL_HINTS = (
    ".lg.jp",
    ".go.jp",
    "city.",
    "city-",
    "town.",
    "kumin",
    "shotengai",
    "shoutengai",
    "sh商店街",
)


def read_json(path: Path, default):
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def write_markdown(path: Path, rows) -> None:
    lines = [
        "# 公式ソース判定待ち",
        "",
        "2025年実績イベントに紐づく公式HP候補です。`decision` は JSON 側で `official` / `hp` / `post` / `reject` / `hold` のいずれかを入れます。",
        "",
        "| No | 判定 | 推奨 | 区 | 会場 | イベント | URL | メモ |",
        "|---:|---|---|---|---|---|---|---|",
    ]
    for idx, row in enumerate(rows, start=1):
        url = row.get("source_url") or ""
        memo = row.get("memo") or row.get("reason") or ""
        memo = re.sub(r"\s+", " ", memo).strip()
        if len(memo) > 80:
            memo = memo[:77] + "..."
        lines.append(
            "| {idx} | {decision} | {suggested} | {region} | {venue} | {event} | {url} | {memo} |".format(
                idx=idx,
                decision=row.get("decision") or "pending",
                suggested=row.get("suggested_source_type") or "",
                region=_md(row.get("region") or ""),
                venue=_md(row.get("venue") or ""),
                event=_md(row.get("event_name") or ""),
                url=f"[link]({url})" if url else "",
                memo=_md(memo),
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _md(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def normalize_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def is_excluded(url: str) -> bool:
    domain = normalize_domain(url)
    return any(domain == item or domain.endswith("." + item) for item in EXCLUDED_DOMAINS)


def classify_url(url: str):
    domain = normalize_domain(url)
    path = urlparse(url).path.lower()
    if domain in SOCIAL_DOMAINS or any(domain.endswith("." + item) for item in SOCIAL_DOMAINS):
        return "post", 35, "SNS投稿候補"
    if domain.endswith(".lg.jp") or domain.endswith(".go.jp"):
        return "official", 85, "自治体・公的ドメイン"
    if path.endswith(".pdf"):
        return "hp", 65, "PDF告知資料の可能性"
    if any(hint in domain for hint in OFFICIAL_HINTS):
        return "official", 75, "主催・商店街・地域団体ドメインらしい"
    return "hp", 50, "紹介HPまたは公式HP候補"


def stable_id(venue: str, event_name: str, url: str) -> str:
    raw = f"{venue}|{event_name}|{url}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def load_existing_sources(path: Path):
    data = read_json(path, {"events": []})
    by_key = {}
    urls = set()
    for event in data.get("events", []):
        key = (event.get("venue") or "", event.get("event_name") or "")
        by_key[key] = event
        urls.update(event.get("official_sources") or [])
    return by_key, urls


def row_from_blog_item(item, existing_urls):
    url = item.get("source_url") or (item.get("event") or {}).get("source_url") or ""
    if not url or is_excluded(url):
        return None
    event = item.get("event") or {}
    venue = item.get("venue_name") or ""
    event_name = event.get("name") or item.get("event_name") or venue
    suggested, score, reason = classify_url(url)
    return {
        "id": stable_id(venue, event_name, url),
        "decision": "pending",
        "suggested_source_type": suggested,
        "suggested_score": score,
        "reason": reason,
        "source_origin": "blog_registration_candidates",
        "source_url": url,
        "source_domain": normalize_domain(url),
        "already_registered": url in existing_urls,
        "venue": venue,
        "event_name": event_name,
        "region": item.get("region") or "",
        "scale": item.get("scale") or "",
        "event_month": event.get("month") or "",
        "event_date_text": event.get("date_text") or "",
        "memo": item.get("memo") or "",
    }


def load_public_event_index(path: Path):
    rows = read_json(path, [])
    by_name = {}
    for row in rows if isinstance(rows, list) else []:
        name = row.get("name") or ""
        if name and name not in by_name:
            by_name[name] = row
    return by_name


def rows_from_youtube_validation(data, existing_urls, public_by_name):
    rows = []
    for item in data.get("rows", []):
        url = item.get("primary_url") or ""
        if not url or is_excluded(url):
            continue
        best = (item.get("best_existing_matches") or [{}])[0]
        venue = best.get("venue") or ""
        event_name = best.get("event_name") or ""
        if not event_name:
            title = (item.get("titles") or [""])[0]
            event_name = re.sub(r"【|】", "", title).strip()[:80] or normalize_domain(url)
        public_event = public_by_name.get(event_name) or {}
        venue = venue or public_event.get("venue") or ""
        region = public_event.get("area") or ""
        months = public_event.get("months") or []
        suggested, score, reason = classify_url(url)
        if item.get("status") == "existing_event_append_ready":
            suggested = "official"
            score = max(score, 80)
            reason = "2025公式URL本文の日付と既存イベント候補が一致"
        rows.append({
            "id": stable_id(venue, event_name, url),
            "decision": "pending",
            "suggested_source_type": suggested,
            "suggested_score": score,
            "reason": reason,
            "source_origin": "youtube_2025_official_candidate_validation",
            "source_url": url,
            "source_domain": normalize_domain(url),
            "already_registered": url in existing_urls,
            "venue": venue,
            "event_name": event_name,
            "region": region,
            "scale": "",
            "event_month": "、".join(f"{month}月" for month in months),
            "event_date_text": ", ".join(item.get("detected_dates") or []),
            "memo": item.get("reason") or "",
            "video_count": item.get("video_count") or 0,
        })
    return rows


def dedupe_rows(rows):
    deduped = {}
    for row in rows:
        key = (row.get("venue"), row.get("event_name"), row.get("source_url"))
        current = deduped.get(key)
        if not current or row.get("suggested_score", 0) > current.get("suggested_score", 0):
            deduped[key] = row
    return sorted(
        deduped.values(),
        key=lambda row: (
            row.get("already_registered", False),
            -int(row.get("suggested_score") or 0),
            row.get("region") or "",
            row.get("event_month") or "",
            row.get("event_name") or "",
        ),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blog-candidates", default=str(DEFAULT_BLOG_CANDIDATES))
    parser.add_argument("--youtube-validation", default=str(DEFAULT_YOUTUBE_VALIDATION))
    parser.add_argument("--evergreen", default=str(DEFAULT_EVERGREEN))
    parser.add_argument("--public-events", default=str(DEFAULT_PUBLIC_EVENTS))
    parser.add_argument("--out-json", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--out-md", default=str(DEFAULT_OUT_MD))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    _, existing_urls = load_existing_sources(Path(args.evergreen))
    blog_data = read_json(Path(args.blog_candidates), {"items": []})
    youtube_data = read_json(Path(args.youtube_validation), {"rows": []})
    public_by_name = load_public_event_index(Path(args.public_events))

    rows = []
    for item in blog_data.get("items", []):
        row = row_from_blog_item(item, existing_urls)
        if row:
            rows.append(row)
    rows.extend(rows_from_youtube_validation(youtube_data, existing_urls, public_by_name))
    rows = dedupe_rows(rows)
    if args.limit:
        rows = rows[:args.limit]

    counts = Counter(row.get("suggested_source_type") for row in rows)
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "build_official_source_review.py",
        "review_policy": {
            "decision_values": ["official", "hp", "post", "reject", "hold"],
            "official": "主催・会場・自治体など、公開サイトで公式告知としてリンクしてよい",
            "hp": "紹介HPまたは準公式。巡回候補には使うが公開リンクはしない",
            "post": "SNS投稿。巡回候補とは別扱いで、公開リンクはしない",
            "reject": "このイベントの根拠URLではない",
            "hold": "保留",
        },
        "source_counts": dict(counts),
        "candidate_count": len(rows),
        "rows": rows,
    }
    write_json(Path(args.out_json), output)
    write_markdown(Path(args.out_md), rows)
    print(
        f"official source review: candidates={len(rows)} "
        f"official_suggested={counts.get('official', 0)} "
        f"hp_suggested={counts.get('hp', 0)} "
        f"post_suggested={counts.get('post', 0)} -> {args.out_json}"
    )


if __name__ == "__main__":
    main()
