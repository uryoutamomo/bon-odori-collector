#!/usr/bin/env python3
"""Build a daily X harvest review queue for glossary terms and song/venue co-occurrence."""

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bon_odori_songs import extract_song_candidates


DATA = Path("data")
VOICES = DATA / "voices.json"
PUBLIC_EVENTS = DATA / "public" / "events_public.json"
PUBLIC_VENUES = DATA / "public" / "venues_public.json"
OUT = DATA / "weekly_harvest_candidates.json"

TERM_PATTERNS = [
    ("輪踊り", "櫓や中心を囲んで輪になって踊る形式", "準公式用語"),
    ("参戦", "盆踊りイベントへ参加すること", "参加スタイル語"),
    ("踊り納め", "その年や時期の最後の盆踊り参加", "参加スタイル語"),
    ("踊り始め", "その年や時期の最初の盆踊り参加", "参加スタイル語"),
    ("ハシゴ", "複数会場を同日または連続して巡る行動", "行動語"),
    ("はしご", "複数会場を同日または連続して巡る行動", "行動語"),
    ("梯子", "複数会場を同日または連続して巡る行動", "行動語"),
    ("盆活", "盆踊り関連の参加・調査・練習などの活動", "行動語"),
    ("盆オフ", "盆踊りを軸にしたオフ会・集まり", "界隈語"),
    ("盆踊りオフ会", "盆踊りを軸にしたオフ会・集まり", "界隈語"),
    ("練習会", "盆踊りの曲や振りを練習する会", "準公式用語"),
    ("踊り会", "盆踊りや輪踊りの会", "準公式用語"),
]


def load_json(path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def row_date(row):
    return parse_date(row.get("date") or row.get("created_at") or row.get("published_at"))


def recent_voices(days, now=None):
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    rows = []
    for row in load_json(VOICES, []):
        dt = row_date(row)
        if dt and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt and dt >= since:
            rows.append(row)
    return rows, since, now


def known_names(path, *fields):
    names = []
    for row in load_json(path, []):
        for field in fields:
            value = row.get(field)
            if value and len(str(value)) >= 3:
                names.append(str(value))
    return sorted(set(names), key=len, reverse=True)


def evidence(row):
    return {
        "url": row.get("url") or "",
        "date": row.get("date") or "",
        "account": row.get("account") or row.get("name") or "",
        "text": clean_text(row.get("text"))[:500],
    }


def add_candidate(candidates, key, item):
    current = candidates.setdefault(key, item)
    if current is not item:
        current["evidence_count"] += item.get("evidence_count", 1)
        seen_urls = {ev.get("url") for ev in current["evidence"]}
        for ev in item.get("evidence", []):
            if ev.get("url") not in seen_urls:
                current["evidence"].append(ev)


def build(days):
    voices, since, now = recent_voices(days)
    venues = known_names(PUBLIC_VENUES, "name")
    events = known_names(PUBLIC_EVENTS, "name")
    candidates = {}
    for row in voices:
        text = clean_text(row.get("text"))
        if not text:
            continue
        ev = evidence(row)
        for term, interpretation, subtype in TERM_PATTERNS:
            if term in text:
                add_candidate(
                    candidates,
                    ("term", term, subtype),
                    {
                        "category": "用語候補",
                        "type": subtype,
                        "term": term,
                        "interpretation": interpretation,
                        "confidence": "要レビュー",
                        "reason": "日次X収穫パターンに一致。準公式用語も対象に含める。",
                        "evidence_count": 1,
                        "evidence": [ev],
                    },
                )

        matched_venues = [name for name in venues if name in text][:5]
        matched_events = [name for name in events if name in text][:5]
        songs = extract_song_candidates(text)
        for song in songs:
            song_name = song["name"]
            add_candidate(
                candidates,
                ("song", song_name),
                {
                    "category": "曲候補",
                    "type": "曲名",
                    "term": song_name,
                    "interpretation": song_name,
                    "confidence": "要レビュー",
                    "reason": "曲名抽出器で検出: " + ", ".join(song.get("reasons", [])),
                    "evidence_count": 1,
                    "evidence": [ev],
                },
            )
            for venue in matched_venues:
                add_candidate(
                    candidates,
                    ("song_venue", song_name, venue),
                    {
                        "category": "曲×会場共起",
                        "type": "共起",
                        "term": f"{song_name} × {venue}",
                        "song_name": song_name,
                        "venue": venue,
                        "event_candidates": matched_events,
                        "interpretation": f"{venue}で{song_name}が言及された可能性",
                        "confidence": "要レビュー",
                        "reason": "同一voice内に曲名候補と既知会場名が共起。",
                        "evidence_count": 1,
                        "evidence": [ev],
                    },
                )

    rows = []
    for item in candidates.values():
        evidence_rows = item.pop("evidence")
        item["evidence"] = evidence_rows[:5]
        item["evidence_text"] = "\n---\n".join(ev["text"] for ev in evidence_rows[:3])
        item["evidence_url"] = evidence_rows[0].get("url", "") if evidence_rows else ""
        rows.append(item)
    rows.sort(key=lambda row: (row["category"], -row["evidence_count"], row["term"]))
    return {
        "generated_by": "build_weekly_harvest_candidates.py",
        "generated_at": now.isoformat(),
        "since": since.isoformat(),
        "days": days,
        "voice_count": len(voices),
        "candidate_count": len(rows),
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    output = build(args.days)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"日次X収穫候補生成: voices {output['voice_count']} / "
        f"candidates {output['candidate_count']} -> {args.out}"
    )


if __name__ == "__main__":
    main()
