#!/usr/bin/env python3
"""Apply accepted official source review decisions to evergreen_events.json."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from proactive_search import parse_months


ROOT = Path(__file__).resolve().parent
DEFAULT_REVIEW = ROOT / "data/official_source_review_candidates.json"
DEFAULT_EVERGREEN = ROOT / "data/evergreen_events.json"

APPLY_DECISIONS = {"official", "hp"}


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


def key_for(venue: str, event_name: str) -> str:
    return re.sub(r"\s+", "", f"{venue}|{event_name}").casefold()


def text_key(value: str) -> str:
    return re.sub(r"\s+", "", value or "").casefold()


def clean_event_name(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"\s*\d{1,2}月\d{1,2}日(?:\([^)]*\))?(?:[-〜ｰ=]\d{1,2}日(?:\([^)]*\))?)?.*$", "", text)
    text = re.sub(r"\s*\d{1,2}/\d{1,2}(?:\([^)]*\))?(?:[-〜ｰ=]\d{1,2}(?:\([^)]*\))?)?.*$", "", text)
    text = re.sub(r"\s*\d{1,2}:\d{2}.*$", "", text)
    return text.strip(" 。、")


def unique(values):
    result = []
    seen = set()
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def event_months(row):
    months = parse_months(row.get("event_month"))
    if months:
        return months
    return parse_months(row.get("event_date_text"))


def ensure_event(events, row):
    venue = row.get("venue") or ""
    event_name = clean_event_name(row.get("event_name") or venue)
    by_key = {key_for(event.get("venue") or "", event.get("event_name") or ""): event for event in events}
    key = key_for(venue, event_name)
    event = by_key.get(key)
    if not event:
        venue_matches = [
            item for item in events
            if text_key(item.get("venue") or "") == text_key(venue)
        ]
        if len(venue_matches) == 1:
            event = venue_matches[0]
    created = False
    if not event:
        event = {
            "venue": venue,
            "event_name": event_name,
            "months": event_months(row),
            "scale": row.get("scale") or "",
            "aliases": unique([venue, event_name]),
            "confirmation_terms": unique([event_name, venue]),
            "official_sources": [],
            "tier": "reviewed_source",
            "source": "official_source_review",
        }
        events.append(event)
        created = True
    return event, created


def apply_row(events, row):
    decision = row.get("decision")
    if decision not in APPLY_DECISIONS:
        return None
    url = row.get("source_url") or ""
    if not url:
        return None
    if not row.get("venue"):
        return None
    event, created = ensure_event(events, row)
    before = set(event.get("official_sources") or [])
    event["official_sources"] = unique(list(before) + [url])
    existing_type = event.get("official_source_type")
    if decision == "official" or not existing_type:
        event["official_source_type"] = decision
    event["aliases"] = unique(
        list(event.get("aliases") or [])
        + [row.get("venue"), row.get("event_name")]
    )
    event["confirmation_terms"] = unique(
        list(event.get("confirmation_terms") or [])
        + [row.get("event_name"), row.get("venue")]
    )
    if not event.get("months"):
        event["months"] = event_months(row)
    return {
        "id": row.get("id"),
        "decision": decision,
        "created_event": created,
        "added_source": url not in before,
        "venue": event.get("venue"),
        "event_name": event.get("event_name"),
        "source_url": url,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", default=str(DEFAULT_REVIEW))
    parser.add_argument("--evergreen", default=str(DEFAULT_EVERGREEN))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    review = read_json(Path(args.review), {"rows": []})
    evergreen = read_json(Path(args.evergreen), {"events": []})
    events = evergreen.setdefault("events", [])

    applied = []
    skipped = 0
    for row in review.get("rows", []):
        result = apply_row(events, row)
        if result:
            applied.append(result)
        else:
            skipped += 1

    evergreen["updated_at"] = datetime.now(timezone.utc).isoformat()
    evergreen["updated_by"] = "apply_official_source_review_decisions.py"
    if not args.dry_run:
        write_json(Path(args.evergreen), evergreen)

    print(
        f"official source decisions: applied={len(applied)} skipped={skipped} "
        f"created={sum(1 for row in applied if row['created_event'])} "
        f"added_sources={sum(1 for row in applied if row['added_source'])} "
        f"dry_run={args.dry_run}"
    )
    for row in applied[:20]:
        print(f"- {row['decision']} {row['event_name']} / {row['source_url']}")
    if len(applied) > 20:
        print(f"- ... {len(applied) - 20} more")


if __name__ == "__main__":
    main()
