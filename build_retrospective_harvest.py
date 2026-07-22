#!/usr/bin/env python3
"""Build persistent retrospective candidates from data/voices.json."""

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from song_processing.bon_odori_songs import extract_song_candidates
from collection_support.event_evidence import (
    aggregate_event_candidates,
    build_event_candidate_match_key,
    classify_event_evidence,
    dancer_key,
)
from collection_support.queue_store import normalize_candidate_key


DATA = Path("data")
VOICES = DATA / "voices.json"
OUT = DATA / "retrospective_harvest_candidates.json"


def load_json(path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    return re.sub(r"\s+", "", str(value or "").strip()).casefold()


def month_from_event_evidence(evidence):
    return evidence.get("estimated_month") or ""


def candidate_digest(*parts):
    raw = "\0".join(str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def tier(score):
    if score >= 50:
        return "promote"
    if score >= 20:
        return "review"
    return "hold"


def evidence_row(voice, event_evidence=None, extra=None):
    row = {
        "identity": (event_evidence or {}).get("identity") or "",
        "tweet_id": str(voice.get("tweet_id") or ""),
        "url": voice.get("url") or "",
        "text": clean_text(voice.get("text"))[:500],
        "account": voice.get("account") or "",
        "dancer_key": dancer_key(voice.get("account") or ""),
        "observed_at": voice.get("date") or "",
        "score": (event_evidence or {}).get("score", 0),
    }
    if extra:
        row.update(extra)
    return row


def add_evidence(group, ev):
    seen = {item.get("url") or item.get("tweet_id") for item in group["evidence"]}
    key = ev.get("url") or ev.get("tweet_id")
    if key and key in seen:
        return
    group["evidence"].append(ev)


def event_schema(candidate):
    venue = candidate.get("estimated_venue") or ""
    display_name = candidate.get("display_name") or candidate.get("title") or ""
    return {
        "kind": "event",
        "candidate_key": candidate["candidate_key"],
        "display_name": display_name,
        "normalized_event": candidate.get("normalized_event") or "",
        "venue": venue,
        "venue_key": normalize_candidate_key(venue, "会場") if venue else "",
        "month": candidate.get("estimated_month") or "",
        "estimated_date": candidate.get("estimated_date") or "",
        "year": candidate.get("year") or "",
        "hashtags": candidate.get("hashtags") or [],
        "score": candidate.get("confidence_score", 0),
        "tier": candidate.get("tier") or tier(candidate.get("confidence_score", 0)),
        "evidence_count": candidate.get("evidence_count", 0),
        "speaker_count": candidate.get("speaker_count", 0),
        "suppressed_event_hints": candidate.get("suppressed_event_hints") or [],
        "evidence": candidate.get("evidence") or [],
    }


def add_song_candidate(groups, voice, event_evidence):
    text = clean_text(voice.get("text"))
    if not text:
        return
    for song in extract_song_candidates(text):
        name = song["name"]
        venue = (event_evidence or {}).get("estimated_venue") or ""
        month = month_from_event_evidence(event_evidence or {})
        normalized_event = (event_evidence or {}).get("normalized_event") or ""
        key = (norm(name), normalize_candidate_key(venue, "会場") if venue else "", month)
        candidate_key = "song:" + candidate_digest("song", *key)
        group = groups.setdefault(key, {
            "kind": "song",
            "candidate_key": candidate_key,
            "display_name": name,
            "normalized_event": normalized_event,
            "venue": venue,
            "venue_key": normalize_candidate_key(venue, "会場") if venue else "",
            "month": month,
            "estimated_date": "",
            "year": (event_evidence or {}).get("year") or "",
            "hashtags": [],
            "score": 0,
            "tier": "hold",
            "evidence": [],
            "reasons": set(),
            "suppressed_event_hints": (event_evidence or {}).get("suppressed_event_hints") or [],
        })
        group["reasons"].update(song.get("reasons", []))
        add_evidence(
            group,
            evidence_row(
                voice,
                event_evidence,
                {
                    "song_name": name,
                    "reasons": song.get("reasons", []),
                    "estimated_event": (event_evidence or {}).get("estimated_event") or "",
                    "estimated_venue": venue,
                    "time_hints": (event_evidence or {}).get("time_hints") or [],
                },
            ),
        )


def add_venue_candidate(groups, voice, event_evidence):
    venue = (event_evidence or {}).get("estimated_venue") or ""
    if not venue:
        return
    month = month_from_event_evidence(event_evidence or {})
    venue_key = normalize_candidate_key(venue, "会場")
    key = (venue_key, month)
    group = groups.setdefault(key, {
        "kind": "venue",
        "candidate_key": "venue:" + candidate_digest("venue", venue_key, month),
        "display_name": venue,
        "normalized_event": "",
        "venue": venue,
        "venue_key": venue_key,
        "month": month,
        "estimated_date": "",
        "year": (event_evidence or {}).get("year") or "",
        "hashtags": [],
        "score": 0,
        "tier": "hold",
        "evidence": [],
        "suppressed_event_hints": (event_evidence or {}).get("suppressed_event_hints") or [],
    })
    add_evidence(
        group,
        evidence_row(
            voice,
            event_evidence,
            {
                "estimated_event": (event_evidence or {}).get("estimated_event") or "",
                "estimated_venue": venue,
                "time_hints": (event_evidence or {}).get("time_hints") or [],
            },
        ),
    )


def finalize_candidate(candidate):
    speakers = {item.get("dancer_key") for item in candidate["evidence"] if item.get("dancer_key")}
    base = min(len(candidate["evidence"]) * 10, 30)
    speaker_score = min(len(speakers) * 10, 25)
    anchor_score = 15 if candidate.get("venue") and candidate.get("month") else 8 if candidate.get("venue") else 0
    reason_score = 10 if candidate.get("reasons") else 0
    score = min(100, base + speaker_score + anchor_score + reason_score)
    candidate["score"] = score
    candidate["tier"] = tier(score)
    candidate["evidence_count"] = len(candidate["evidence"])
    candidate["speaker_count"] = len(speakers)
    if "reasons" in candidate:
        candidate["reasons"] = sorted(candidate["reasons"])
    return candidate


def build_from_voices(voices, generated_at=None):
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    event_evidence = []
    song_groups = {}
    venue_groups = {}
    classified_count = 0

    for voice in voices:
        if not isinstance(voice, dict):
            continue
        evidence = classify_event_evidence(voice)
        if evidence:
            evidence["match_key"] = build_event_candidate_match_key(evidence)
            event_evidence.append(evidence)
            classified_count += 1
            add_venue_candidate(venue_groups, voice, evidence)
        add_song_candidate(song_groups, voice, evidence)

    event_candidates = [event_schema(candidate) for candidate in aggregate_event_candidates(event_evidence)]
    song_candidates = [finalize_candidate(candidate) for candidate in song_groups.values()]
    venue_candidates = [finalize_candidate(candidate) for candidate in venue_groups.values()]
    candidates = event_candidates + song_candidates + venue_candidates
    candidates.sort(key=lambda item: (item["kind"], -item.get("score", 0), item["display_name"], item["candidate_key"]))

    by_kind = Counter(item["kind"] for item in candidates)
    by_tier = Counter(item.get("tier", "hold") for item in candidates)
    suppressed_count = sum(len(item.get("suppressed_event_hints") or []) for item in candidates)
    venue_month_grouped_count = sum(
        1 for item in candidates
        if item["kind"] in ("event", "venue") and item.get("venue") and item.get("month")
    )
    return {
        "generated_by": "build_retrospective_harvest.py",
        "generated_at": generated_at,
        "source": str(VOICES),
        "voice_count": len([voice for voice in voices if isinstance(voice, dict)]),
        "classified_event_evidence_count": classified_count,
        "candidate_count": len(candidates),
        "counts": {
            "by_kind": dict(sorted(by_kind.items())),
            "by_tier": dict(sorted(by_tier.items())),
            "suppressed_event_hint_count": suppressed_count,
            "venue_month_grouped_count": venue_month_grouped_count,
        },
        "candidates": candidates,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--voices", type=Path, default=VOICES)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    output = build_from_voices(load_json(args.voices, []))
    if not args.dry_run:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"retrospective harvest: voices={output['voice_count']} "
        f"candidates={output['candidate_count']} "
        f"by_kind={output['counts']['by_kind']} "
        f"by_tier={output['counts']['by_tier']}"
        + (" (dry-run)" if args.dry_run else f" -> {args.out}")
    )


if __name__ == "__main__":
    main()
