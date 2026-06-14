#!/usr/bin/env python3
"""Build a queue of posts likely to need image OCR for song setlists."""

import hashlib
import json
import re
from pathlib import Path


DATA = Path("data")
VOICES = DATA / "voices.json"
OUT = DATA / "song_ocr_queue.json"

SETLIST_HINT_RE = re.compile(r"(?:曲目リスト|曲目表|曲目|曲順|セットリスト|セトリ)")
STRONG_SETLIST_HINT_RE = re.compile(r"(?:曲目リスト|曲目表|セットリスト|セトリ)")
BON_RE = re.compile(r"(?:盆踊り|盆おどり|盆踊|民踊|音頭)")
LINK_RE = re.compile(r"https?://\S+|t\.co/\S+|pic\.twitter\.com/\S+")


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def queue_id(row):
    raw = "\0".join([
        row.get("url") or "",
        row.get("tweet_id") or "",
        row.get("text") or "",
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def should_queue(row):
    text = row.get("text") or ""
    has_media = bool(row.get("media_urls"))
    has_setlist_hint = bool(SETLIST_HINT_RE.search(text))
    has_strong_setlist_hint = bool(STRONG_SETLIST_HINT_RE.search(text))
    has_bon_context = bool(BON_RE.search(text))
    has_link = bool(LINK_RE.search(text))
    if has_media:
        return has_setlist_hint and has_bon_context
    return has_strong_setlist_hint and has_bon_context and has_link


def build(rows):
    queued = []
    for row in rows:
        if row.get("source") not in ("x", "x_whitelist", "x_event_history", "x_proactive"):
            continue
        if not should_queue(row):
            continue
        media_urls = row.get("media_urls") or []
        queued.append({
            "id": queue_id(row),
            "status": "needs_ocr" if media_urls else "needs_media_resolution",
            "account": row.get("account") or "",
            "url": row.get("url") or "",
            "tweet_id": row.get("tweet_id") or "",
            "date": row.get("date") or "",
            "media_urls": media_urls,
            "text": (row.get("text") or "")[:800],
            "review_hint": "画像をOCRし、曲目が読めたら data/song_ocr_review.json に転記する",
        })
    queued.sort(key=lambda row: (row["status"], row["date"], row["url"]))
    return {
        "generated_by": "build_song_ocr_queue.py",
        "count": len(queued),
        "items": queued,
    }


def main():
    output = build(load_json(VOICES, []))
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"曲目画像OCRキュー生成: {output['count']}件 -> {OUT}")


if __name__ == "__main__":
    main()
