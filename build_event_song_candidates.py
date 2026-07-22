#!/usr/bin/env python3
"""Build a review queue of song candidates for each bon-odori event."""

import hashlib
import json
import os
import re
from pathlib import Path

from song_processing.bon_odori_songs import extract_song_candidates


DATA = Path("data")
PUBLIC = DATA / "public"
OUT = DATA / "event_song_candidates.json"

SOURCE_FILES = [
    ("x_voice", DATA / "voices.json"),
    ("latest_news", DATA / "latest.json"),
    ("blog_registration", DATA / "blog_registration_candidates.json"),
    ("fallback_event", DATA / "fallback_event_candidates.json"),
]


def load_json(path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def norm(value):
    return re.sub(r"\s+", "", str(value or "")).casefold()


def text_blob(*values):
    return "\n".join(str(v or "") for v in values if v)


def source_rows():
    for source, path in SOURCE_FILES:
        data = load_json(path, [] if source in ("public_event", "x_voice", "latest_news") else {"items": []})
        rows = data.get("items", data) if isinstance(data, dict) else data
        for row in rows:
            if not isinstance(row, dict):
                continue
            event = row.get("event") if isinstance(row.get("event"), dict) else {}
            yield {
                "source": source,
                "event_name": row.get("name") or event.get("name") or row.get("title") or "",
                "venue": row.get("venue") or row.get("venue_name") or "",
                "area": row.get("area") or row.get("region") or "",
                "date": row.get("date") or event.get("date_text") or "",
                "url": row.get("url") or row.get("source_url") or event.get("source_url") or "",
                "text": text_blob(
                    row.get("name"),
                    row.get("title"),
                    row.get("description"),
                    row.get("detail"),
                    row.get("memo"),
                    row.get("text"),
                    event.get("name"),
                    event.get("date_text"),
                ),
            }


def public_events():
    events = []
    for row in load_json(PUBLIC / "events_public.json", []):
        events.append({
            "name": row.get("name") or "",
            "venue": row.get("venue") or "",
            "area": row.get("area") or "",
            "date": row.get("date"),
            "songs": [
                s.get("name") if isinstance(s, dict) else str(s)
                for s in row.get("songs", [])
            ],
        })
    return events


def match_event(row, events):
    row_event = norm(row["event_name"])
    row_venue = norm(row["venue"])
    row_text = norm(row["text"])
    best = None
    best_score = 0
    for event in events:
        score = 0
        event_name = norm(event["name"])
        venue = norm(event["venue"])
        if event_name and (event_name in row_text or (row_event and (row_event in event_name or event_name in row_event))):
            score += 6
        if venue and (venue in row_text or (row_venue and (row_venue == venue or venue in row_venue or row_venue in venue))):
            score += 5
        if event["area"] and event["area"] == row["area"]:
            score += 1
        if score > best_score:
            best = event
            best_score = score
    return best if best_score >= 5 else None


def confidence(candidate, event, evidence_count, source):
    reasons = set(candidate.get("reasons", []))
    if event and ("song_suffix_in_context" in reasons or "split_context" in reasons) and evidence_count >= 2:
        return "高"
    if event and ("song_suffix_in_context" in reasons or "known_song_context" in reasons or source == "public_event"):
        return "中"
    if event:
        return "低"
    return "未紐づけ"


def candidate_id(song, event_name, venue, url):
    raw = "\0".join([song, event_name, venue, url])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def build():
    events = public_events()
    grouped = {}
    for event in events:
        for song in event.get("songs", []):
            key = (song, event["name"], event["venue"])
            grouped[key] = {
                "id": candidate_id(song, event["name"], event["venue"], "public"),
                "song_name": song,
                "event_name": event["name"],
                "venue": event["venue"],
                "area": event["area"],
                "status": "公開済み",
                "confidence": "公開済み",
                "reasons": {"already_public"},
                "evidence": [],
                "already_public": True,
            }
    for row in source_rows():
        candidates = extract_song_candidates(row["text"])
        if not candidates:
            continue
        event = match_event(row, events)
        if not event and not row["venue"]:
            continue
        for cand in candidates:
            event_name = event["name"] if event else row["event_name"]
            venue = event["venue"] if event else row["venue"]
            area = event["area"] if event else row["area"]
            key = (cand["name"], event_name, venue)
            item = grouped.setdefault(key, {
                "id": candidate_id(cand["name"], event_name, venue, row["url"]),
                "song_name": cand["name"],
                "event_name": event_name,
                "venue": venue,
                "area": area,
                "status": "未確認",
                "confidence": "低",
                "reasons": set(),
                "evidence": [],
                "already_public": False,
            })
            item["reasons"].update(cand["reasons"])
            if row["url"] and all(ev["url"] != row["url"] for ev in item["evidence"]):
                item["evidence"].append({
                    "source": row["source"],
                    "url": row["url"],
                    "date": row["date"],
                    "text": row["text"][:420],
                })
            if not item["already_public"]:
                item["confidence"] = confidence(cand, event, len(item["evidence"]), row["source"])

    rows = []
    confidence_rank = {"高": 0, "中": 1, "低": 2, "未紐づけ": 3, "公開済み": 4}
    for item in grouped.values():
        item["reasons"] = sorted(item["reasons"])
        item["evidence_count"] = len(item["evidence"])
        rows.append(item)
    rows.sort(key=lambda r: (
        r["already_public"],
        confidence_rank.get(r["confidence"], 9),
        r["area"],
        r["venue"],
        r["song_name"],
    ))
    return {
        "generated_by": "build_event_song_candidates.py",
        "count": len(rows),
        "public_event_count": sum(1 for r in rows if r["already_public"]),
        "review_count": sum(1 for r in rows if not r["already_public"]),
        "candidates": rows,
    }


def main():
    output = build()
    os.makedirs(OUT.parent, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(
        f"曲目候補生成完了: {output['count']}件 "
        f"(公開済み {output['public_event_count']} / 要レビュー {output['review_count']}) → {OUT}"
    )


if __name__ == "__main__":
    main()
