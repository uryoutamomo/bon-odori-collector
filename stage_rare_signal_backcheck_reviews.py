#!/usr/bin/env python3
"""Stage confirmed rare-signal back-check reviews for downstream registration.

The script reads the generated back-check queue plus a separate human/Oto review
file. Only confirmed rows with at least one non-X confirmation URL are staged.
It does not mutate Master RDB, Notion, public JSON, or any event registry.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from x_official_source_accounts import is_official_social_url


DATA = Path("data")
DEFAULT_QUEUE = DATA / "rare_signal_backcheck_queue.json"
DEFAULT_REVIEWS = DATA / "rare_signal_backcheck_reviews.json"
DEFAULT_OUT_JSON = DATA / "rare_signal_registration_candidates.json"
DEFAULT_OUT_MD = DATA / "rare_signal_registration_candidates.md"

CONFIRM_DECISIONS = {"confirm", "confirmed", "採用", "確認済み", "登録候補"}
HOLD_DECISIONS = {"hold", "保留"}
REJECT_DECISIONS = {"reject", "rejected", "却下", "不採用"}
SOCIAL_DOMAINS = {"x.com", "twitter.com", "t.co"}


def load_json(path: Path, default):
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def review_rows(payload) -> list[dict]:
    rows = payload.get("reviews") if isinstance(payload, dict) else payload
    return [row for row in rows or [] if isinstance(row, dict)]


def review_index(payload) -> dict[str, dict]:
    indexed = {}
    for row in review_rows(payload):
        candidate_id = row.get("candidate_id") or row.get("id") or ""
        if candidate_id:
            indexed[candidate_id] = row
    return indexed


def hostname(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def is_social_url(url: str) -> bool:
    host = hostname(url)
    return any(host == domain or host.endswith("." + domain) for domain in SOCIAL_DOMAINS)


def clean_urls(urls) -> list[str]:
    if isinstance(urls, str):
        urls = [urls]
    cleaned = []
    for url in urls or []:
        text = str(url or "").strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def non_x_urls(urls) -> list[str]:
    return [url for url in clean_urls(urls) if not is_social_url(url)]


def confirmable_urls(urls) -> list[str]:
    return [url for url in clean_urls(urls) if not is_social_url(url) or is_official_social_url(url)]


def decision_of(review: dict) -> str:
    return str(review.get("decision") or "").strip()


def classify_skip(queue_row: dict, review: dict | None) -> str:
    if not review:
        return "missing_backcheck_review"
    decision = decision_of(review)
    if decision in HOLD_DECISIONS:
        return "hold"
    if decision in REJECT_DECISIONS:
        return "reject"
    if decision not in CONFIRM_DECISIONS:
        return "unknown_or_missing_decision"
    urls = confirmable_urls(review.get("confirmed_source_urls") or review.get("confirmed_source_url"))
    if not urls:
        return "missing_confirmable_source_url"
    if not (queue_row.get("primary_name") or queue_row.get("possible_event_name")):
        return "missing_name"
    return ""


def reviewed_or_queue(review: dict, queue_row: dict, key: str, fallback: str = ""):
    if key in review and review.get(key) is not None:
        return review.get(key)
    return queue_row.get(key) if queue_row.get(key) is not None else fallback


def staged_row(queue_row: dict, review: dict, generated_at: str) -> dict:
    confirmed_urls = confirmable_urls(review.get("confirmed_source_urls") or review.get("confirmed_source_url"))
    target = queue_row.get("promotion_target") or ""
    event_name = str(
        review.get("event_name")
        or review.get("possible_event_name")
        or queue_row.get("possible_event_name")
        or queue_row.get("primary_name")
        or ""
    ).strip()
    venue = str(review.get("venue") or reviewed_or_queue(review, queue_row, "possible_venue") or "").strip()
    area = str(review.get("area") or reviewed_or_queue(review, queue_row, "possible_area") or "").strip()
    date_text = str(review.get("date_text") or reviewed_or_queue(review, queue_row, "possible_date_text") or "").strip()
    song_names = review.get("possible_song_names") or queue_row.get("possible_song_names") or []
    ready = ready_for_registration(target, event_name, venue, area, date_text, confirmed_urls, song_names)
    return {
        "candidate_id": queue_row.get("candidate_id") or "",
        "generated_at": generated_at,
        "source_origin": "rare_signal_x_interpreted",
        "registration_status": "staged",
        "ready_for_registration": ready,
        "registration_blockers": [] if ready else registration_blockers(
            target, event_name, venue, area, date_text, confirmed_urls, song_names
        ),
        "promotion_target": target,
        "novelty_assessment": queue_row.get("novelty_assessment") or "",
        "event_name": event_name,
        "venue": venue,
        "area": area,
        "date_text": date_text,
        "song_names": song_names,
        "public_summary": review.get("public_summary") or queue_row.get("oto_interpreted_summary") or "",
        "registration_notes": review.get("registration_notes") or review.get("confirmation_notes") or "",
        "confirmed_source_urls": confirmed_urls,
        "confirmed_source_type": review.get("confirmed_source_type") or queue_row.get("confirmed_source_type") or "",
        "internal_discovery_urls": queue_row.get("internal_discovery_urls") or [],
        "source_policy": queue_row.get("source_policy") or "",
        "next_action": "register_after_review" if ready else "complete_required_fields",
    }


def ready_for_registration(
    target: str,
    event_name: str,
    venue: str,
    area: str,
    date_text: str,
    urls: list[str],
    song_names: list[str],
) -> bool:
    if not urls:
        return False
    if target == "song":
        return bool(song_names or event_name)
    if target == "venue":
        return bool(venue or event_name) and bool(area or venue)
    if target == "existing_evidence":
        return bool(event_name or venue or song_names)
    return bool(event_name and (venue or area) and date_text)


def registration_blockers(
    target: str,
    event_name: str,
    venue: str,
    area: str,
    date_text: str,
    urls: list[str],
    song_names: list[str],
) -> list[str]:
    blockers = []
    if not urls:
        blockers.append("missing_confirmed_source_url")
    if target == "song":
        if not (song_names or event_name):
            blockers.append("missing_song_name")
        return blockers
    if target == "venue":
        if not (venue or event_name):
            blockers.append("missing_venue_name")
        if not (area or venue):
            blockers.append("missing_area_or_address_hint")
        return blockers
    if target == "existing_evidence":
        if not (event_name or venue or song_names):
            blockers.append("missing_existing_record_hint")
        return blockers
    if not event_name:
        blockers.append("missing_event_name")
    if not (venue or area):
        blockers.append("missing_venue_or_area")
    if not date_text:
        blockers.append("missing_date_text")
    return blockers


def build(queue_payload: dict, reviews_payload: dict) -> dict:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    queue_rows = [row for row in queue_payload.get("queue") or [] if isinstance(row, dict)]
    reviews = review_index(reviews_payload)
    staged = []
    skipped = []

    for row in queue_rows:
        candidate_id = row.get("candidate_id") or ""
        review = reviews.get(candidate_id)
        reason = classify_skip(row, review)
        if reason:
            skipped.append({
                "candidate_id": candidate_id,
                "reason": reason,
                "decision": decision_of(review or {}),
            })
            continue
        staged.append(staged_row(row, review or {}, generated_at))

    ready_counts = Counter("ready" if row["ready_for_registration"] else "needs_fields" for row in staged)
    return {
        "generated_by": "stage_rare_signal_backcheck_reviews.py",
        "generated_at": generated_at,
        "input": {
            "backcheck_queue_generated_at": queue_payload.get("generated_at") or "",
        },
        "summary": {
            "review_count": len(reviews),
            "staged_count": len(staged),
            "skipped_count": len(skipped),
            "readiness_counts": dict(sorted(ready_counts.items())),
        },
        "policy": {
            "does_not_apply": True,
            "x_role": "internal_discovery_only_unless_registered_official_or_organizer_social",
            "requires_confirmable_source_url": True,
        },
        "registration_candidates": staged,
        "event_candidates": staged,
        "skipped": skipped,
    }


def md_cell(value) -> str:
    if isinstance(value, list):
        value = "; ".join(str(item) for item in value)
    text = str(value or "").replace("\n", " ").replace("|", "\\|").strip()
    return text[:180] + "..." if len(text) > 180 else text


def write_markdown(data: dict, path: Path) -> None:
    lines = [
        "# Rare Signal Registration Candidates",
        "",
        f"- generated_at: {data['generated_at']}",
        f"- staged_count: {data['summary']['staged_count']}",
        f"- skipped_count: {data['summary']['skipped_count']}",
        "- status: staged only; no Master RDB, Notion, or public JSON mutation",
        "",
        "| ready | event | date | venue/area | source | blockers | summary |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in data["event_candidates"]:
        venue_area = " / ".join(item for item in [row.get("venue") or "", row.get("area") or ""] if item)
        lines.append(
            f"| {md_cell('yes' if row['ready_for_registration'] else 'no')} | "
            f"{md_cell(row['event_name'])} | {md_cell(row['date_text'])} | "
            f"{md_cell(venue_area)} | {md_cell(row['confirmed_source_urls'])} | "
            f"{md_cell(row['registration_blockers'])} | {md_cell(row['public_summary'])} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--reviews", type=Path, default=DEFAULT_REVIEWS)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    args = parser.parse_args()

    queue_payload = load_json(args.queue, {"queue": []})
    reviews_payload = load_json(args.reviews, {"reviews": []})
    data = build(queue_payload, reviews_payload)
    write_json(args.out_json, data)
    write_markdown(data, args.out_md)
    print(
        f"rare signal registration candidates: {data['summary']['staged_count']} "
        f"(skipped {data['summary']['skipped_count']}) -> {args.out_json} / {args.out_md}"
    )


if __name__ == "__main__":
    main()
