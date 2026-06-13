"""Build yearly event-song occurrence evidence and prediction snapshots."""

import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


DATA = Path("data")
YOUTUBE_REVIEW = DATA / "youtube_song_candidates_review.json"
PUBLIC_EVENTS = DATA / "public" / "events_public.json"
OUT_OCCURRENCES = DATA / "song_occurrences.json"
OUT_PUBLIC = DATA / "public" / "event_song_occurrences_public.json"
OUT_SNAPSHOT = DATA / "song_prediction_snapshots.json"

ISO_DATE_RE = re.compile(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})日?")
JP_DATE_RE = re.compile(r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日")
SETLIST_RE = re.compile(r"(?:曲目|曲順|セットリスト|セトリ|演目|プログラム)")
ANNOUNCED_RE = re.compile(r"(?:曲目表|プログラム|演目|曲目|曲順|予定|告知|発表|踊ります)")
OBSERVED_RE = re.compile(r"(?:行われました|開催された|様子|踊った|踊りました|お届けします|動画|YouTube)")


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def normalize_name(value):
    return re.sub(r"\s+", "", str(value or "")).casefold()


def occurrence_id(event_name, venue, year):
    raw = f"{normalize_name(event_name)}\0{normalize_name(venue)}\0{year}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def evidence_id(url, song_name, event_name, year):
    raw = f"{url or ''}\0{normalize_name(song_name)}\0{normalize_name(event_name)}\0{year}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def parse_event_date(*texts, fallback_year=None):
    for text in texts:
        if not text:
            continue
        for pattern in (JP_DATE_RE, ISO_DATE_RE):
            match = pattern.search(str(text))
            if match:
                y, m, d = [int(part) for part in match.groups()]
                return f"{y:04d}-{m:02d}-{d:02d}"
    if fallback_year:
        return f"{int(fallback_year):04d}-01-01"
    return None


def evidence_kind(text, source=""):
    text = str(text or "")
    source = str(source or "")
    if ANNOUNCED_RE.search(text) and not OBSERVED_RE.search(text):
        return "announced"
    if source == "youtube" or OBSERVED_RE.search(text):
        return "observed"
    return "hint"


def has_complete_setlist(text, song_count=0):
    text = str(text or "")
    numbered = re.findall(r"(?:^|\n)\s*[0-9０-９]{1,2}\s*[\.．、]?\s*[^\n]{2,40}", text)
    return bool(SETLIST_RE.search(text) and (song_count >= 3 or len(numbered) >= 3))


def speaker_key(value):
    value = str(value or "").strip()
    return value or "unknown"


def prediction_probability(evidence_items, target_year):
    """Return probability and label for one event-song relation.

    Formula follows the approved v1 shape:
    current-year announced 98%, current-year observed 95%, previous evidence
    decays by 0.75 per elapsed year and is adjusted by unique speaker count.
    """
    if not evidence_items:
        return {
            "probability": 0,
            "basis": "no_evidence",
            "basis_label": "根拠なし",
        }
    current = [ev for ev in evidence_items if ev.get("year") == target_year]
    if any(ev.get("kind") == "announced" for ev in current):
        return {"probability": 98, "basis": "current_announced", "basis_label": "今年告知"}
    if any(ev.get("kind") == "observed" for ev in current):
        return {"probability": 95, "basis": "current_observed", "basis_label": "今年実測"}
    if current:
        speakers = {speaker_key(ev.get("speaker")) for ev in current}
        probability = min(80, 40 + len(speakers) * 8)
        return {
            "probability": probability,
            "basis": "current_hint",
            "basis_label": "今年ヒント",
        }

    past = [ev for ev in evidence_items if ev.get("year") and ev.get("year") < target_year]
    if past:
        latest_year = max(ev["year"] for ev in past)
        latest = [ev for ev in past if ev["year"] == latest_year]
        base = max(98 if ev.get("kind") == "announced" else 95 if ev.get("kind") == "observed" else 50 for ev in latest)
        speakers = {speaker_key(ev.get("speaker")) for ev in latest}
        speaker_factor = min(1.0, 0.65 + 0.15 * max(1, len(speakers)))
        probability = round(base * (0.75 ** (target_year - latest_year)) * speaker_factor)
        kind = max((ev.get("kind") for ev in latest), key=lambda value: {"announced": 3, "observed": 2, "hint": 1}.get(value, 0))
        return {
            "probability": max(5, min(90, probability)),
            "basis": "past_evidence",
            "basis_label": f"{latest_year}年{'告知' if kind == 'announced' else '実測' if kind == 'observed' else 'ヒント'}",
            "latest_year": latest_year,
            "speaker_count": len(speakers),
        }
    return {
        "probability": 15,
        "basis": "prior",
        "basis_label": "階層prior未設定",
    }


def _add_evidence(grouped, event_name, venue, song_name, event_date, kind, speaker,
                  url="", text="", setlist_complete=False, source=""):
    if not event_date:
        return
    year = int(event_date[:4])
    key = (event_name, venue, year, song_name)
    grouped[key].append({
        "id": evidence_id(url, song_name, event_name, year),
        "kind": kind,
        "setlist_complete": bool(setlist_complete),
        "speaker": speaker_key(speaker),
        "url": url or "",
        "date": event_date,
        "year": year,
        "source": source or "",
        "text": re.sub(r"\s+", " ", str(text or "")).strip()[:240],
    })


def occurrences_from_youtube_review(review):
    grouped = defaultdict(list)
    for event in review.get("events", []):
        event_name = event.get("event_name") or ""
        venue = event.get("venue") or ""
        sample_text = "\n".join(event.get("sample_titles") or [])
        for song in event.get("songs", []):
            titles = song.get("sample_titles") or []
            text = "\n".join(titles) or sample_text
            event_date = parse_event_date(text)
            kind = evidence_kind(text, "youtube")
            setlist_complete = (event.get("song_count") or 0) >= 3 or has_complete_setlist(
                text, event.get("song_count") or 0
            )
            urls = song.get("urls") or []
            if not urls:
                urls = [""]
            for url in urls:
                _add_evidence(
                    grouped,
                    event_name,
                    venue,
                    song.get("name") or "",
                    event_date,
                    kind,
                    "youtube",
                    url=url,
                    text=text,
                    setlist_complete=setlist_complete,
                    source="youtube_review",
                )
    return grouped


def occurrences_from_public_events(events):
    grouped = defaultdict(list)
    for event in events:
        event_name = event.get("name") or ""
        venue = event.get("venue") or ""
        event_date = event.get("date")
        text = "\n".join(x for x in [event.get("description"), event.get("detail")] if x)
        if not event_date:
            continue
        for song in event.get("songs") or []:
            _add_evidence(
                grouped,
                event_name,
                venue,
                song.get("name") or "",
                event_date,
                "hint",
                "public_event_snapshot",
                text=text,
                setlist_complete=False,
                source="events_public",
            )
    return grouped


def merge_grouped(*grouped_maps):
    merged = defaultdict(list)
    seen = set()
    for grouped in grouped_maps:
        for key, rows in grouped.items():
            for row in rows:
                dedupe = row.get("id")
                if dedupe in seen:
                    continue
                seen.add(dedupe)
                merged[key].append(row)
    return merged


def build_occurrences(target_year=None, generated_at=None):
    target_year = target_year or datetime.now(timezone.utc).year
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    review = load_json(YOUTUBE_REVIEW, {})
    events = load_json(PUBLIC_EVENTS, [])
    grouped = merge_grouped(
        occurrences_from_youtube_review(review),
        occurrences_from_public_events(events),
    )
    occurrences = {}
    for (event_name, venue, year, song_name), evidence in grouped.items():
        occ_key = occurrence_id(event_name, venue, year)
        occurrence = occurrences.setdefault(occ_key, {
            "occurrence_id": occ_key,
            "event_name": event_name,
            "venue": venue,
            "year": year,
            "songs": {},
        })
        speakers = sorted({speaker_key(ev.get("speaker")) for ev in evidence})
        occurrence["songs"][song_name] = {
            "song_name": song_name,
            "evidence_count": len(evidence),
            "speaker_count": len(speakers),
            "speakers": speakers,
            "evidence": sorted(evidence, key=lambda ev: (ev.get("date") or "", ev.get("url") or "")),
            "prediction": prediction_probability(evidence, target_year),
        }

    rows = []
    for occurrence in occurrences.values():
        occurrence["songs"] = sorted(
            occurrence["songs"].values(),
            key=lambda row: (-row["prediction"]["probability"], row["song_name"]),
        )
        rows.append(occurrence)
    rows.sort(key=lambda row: (row["year"], row["venue"], row["event_name"]))
    return {
        "generated_by": "build_song_occurrences.py",
        "generated_at": generated_at,
        "target_year": target_year,
        "occurrence_count": len(rows),
        "song_relation_count": sum(len(row["songs"]) for row in rows),
        "occurrences": rows,
    }


def public_rows(occurrence_data):
    rows = []
    for occurrence in occurrence_data.get("occurrences", []):
        rows.append({
            "occurrence_id": occurrence["occurrence_id"],
            "event_name": occurrence["event_name"],
            "venue": occurrence["venue"],
            "year": occurrence["year"],
            "songs": [
                {
                    "name": song["song_name"],
                    "probability": song["prediction"]["probability"],
                    "basis": song["prediction"]["basis"],
                    "basis_label": song["prediction"]["basis_label"],
                    "evidence_count": song["evidence_count"],
                    "speaker_count": song["speaker_count"],
                    "setlist_complete": any(ev.get("setlist_complete") for ev in song["evidence"]),
                    "evidence_urls": [ev.get("url") for ev in song["evidence"] if ev.get("url")][:5],
                }
                for song in occurrence.get("songs", [])
            ],
        })
    return rows


def prediction_snapshot(occurrence_data):
    generated_at = occurrence_data.get("generated_at")
    target_year = occurrence_data.get("target_year")
    snapshots = []
    for occurrence in occurrence_data.get("occurrences", []):
        for song in occurrence.get("songs", []):
            snapshots.append({
                "snapshot_id": hashlib.sha256(
                    f"{occurrence['occurrence_id']}\0{song['song_name']}\0{generated_at}".encode("utf-8")
                ).hexdigest()[:20],
                "predicted_at": generated_at,
                "target_year": target_year,
                "occurrence_id": occurrence["occurrence_id"],
                "event_name": occurrence["event_name"],
                "venue": occurrence["venue"],
                "song_name": song["song_name"],
                "probability": song["prediction"]["probability"],
                "basis": song["prediction"]["basis"],
                "basis_label": song["prediction"]["basis_label"],
                "evidence_count": song["evidence_count"],
                "speaker_count": song["speaker_count"],
            })
    return {
        "generated_by": "build_song_occurrences.py",
        "generated_at": generated_at,
        "target_year": target_year,
        "snapshot_count": len(snapshots),
        "snapshots": snapshots,
    }
