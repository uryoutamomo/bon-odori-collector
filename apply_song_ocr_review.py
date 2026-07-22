#!/usr/bin/env python3
"""Append reviewed OCR setlists to data/song_evidence_manual.json."""

import argparse
import json
import re
from pathlib import Path

from song_processing.bon_odori_songs import extract_song_candidates


DATA = Path("data")
REVIEW = DATA / "song_ocr_review.json"
MANUAL_EVIDENCE = DATA / "song_evidence_manual.json"
PUBLIC_EVENTS = DATA / "public" / "events_public.json"


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def norm(value):
    return re.sub(r"\s+", "", str(value or "")).casefold()


def event_index():
    events = []
    for event in load_json(PUBLIC_EVENTS, []):
        events.append({
            "name": event.get("name") or "",
            "venue": event.get("venue") or "",
            "date": event.get("date") or "",
            "date_end": event.get("date_end") or "",
        })
    return events


def match_event(row, events):
    if row.get("event_name") and row.get("venue"):
        return {
            "name": row["event_name"],
            "venue": row["venue"],
            "date": row.get("event_date") or "",
            "date_end": row.get("event_date_end") or "",
        }
    text = norm(" ".join([
        row.get("tweet_text") or "",
        row.get("ocr_text") or "",
        row.get("event_name") or "",
        row.get("venue") or "",
    ]))
    best = None
    best_score = 0
    for event in events:
        score = 0
        if event["name"] and norm(event["name"]) in text:
            score += 6
        if event["venue"] and norm(event["venue"]) in text:
            score += 5
        if score > best_score:
            best = event
            best_score = score
    return best if best_score >= 6 else None


def songs_from_review(row):
    explicit = [str(song).strip() for song in row.get("songs", []) if str(song).strip()]
    if explicit:
        return explicit
    text = row.get("ocr_text") or ""
    return [item["name"] for item in extract_song_candidates(text)]


def append_review(review, manual, dry_run=False):
    manual.setdefault("version", 1)
    manual.setdefault("description", "Manual song evidence that should feed song_occurrences before public exports.")
    manual.setdefault("evidence", [])
    existing_keys = {
        (
            item.get("url") or "",
            item.get("event_name") or "",
            item.get("venue") or "",
            tuple(item.get("songs") or []),
        )
        for item in manual["evidence"]
    }
    events = event_index()
    appended = []
    skipped = []
    for row in review.get("items", []):
        if row.get("status") not in ("approved", "確認済み", "apply"):
            skipped.append({"url": row.get("url"), "reason": "not_approved"})
            continue
        event = match_event(row, events)
        if not event:
            skipped.append({"url": row.get("url"), "reason": "event_not_matched"})
            continue
        songs = songs_from_review(row)
        if not songs:
            skipped.append({"url": row.get("url"), "reason": "no_songs"})
            continue
        item = {
            "event_name": event["name"],
            "venue": event["venue"],
            "event_date": row.get("event_date") or event.get("date") or "",
            "event_start": row.get("event_start") or "",
            "observed_at": row.get("observed_at") or row.get("date") or "",
            "kind": row.get("kind") or "announced",
            "role": row.get("role") or "prediction",
            "reliability": float(row.get("reliability", 0.8)),
            "reliability_key": row.get("reliability_key") or "semi_official_setlist",
            "setlist_complete": bool(row.get("setlist_complete", len(songs) >= 3)),
            "speaker": row.get("account") or row.get("speaker") or "ocr_review",
            "source": row.get("source") or "ocr_review",
            "url": row.get("url") or "",
            "text": (row.get("ocr_text") or row.get("tweet_text") or "")[:900],
            "songs": songs,
        }
        key = (item["url"], item["event_name"], item["venue"], tuple(item["songs"]))
        if key in existing_keys:
            skipped.append({"url": item["url"], "reason": "duplicate"})
            continue
        existing_keys.add(key)
        appended.append(item)
        if not dry_run:
            manual["evidence"].append(item)
    return {"appended": appended, "skipped": skipped}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", type=Path, default=REVIEW)
    parser.add_argument("--manual", type=Path, default=MANUAL_EVIDENCE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    manual = load_json(args.manual, {"version": 1, "evidence": []})
    result = append_review(load_json(args.review, {"items": []}), manual, dry_run=args.dry_run)
    if not args.dry_run:
        write_json(args.manual, manual)
    print(
        "曲目OCRレビュー反映: "
        f"appended={len(result['appended'])} skipped={len(result['skipped'])} "
        f"dry_run={args.dry_run}"
    )


if __name__ == "__main__":
    main()
