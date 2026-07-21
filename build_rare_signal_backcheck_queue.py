#!/usr/bin/env python3
"""Build a web back-check queue from Oto-reviewed rare signal candidates.

This script does not perform web searches. It prepares a reviewable queue so
X-derived discoveries remain discovery signals until a non-X source confirms
the event, song, venue, or evidence.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from collection_support.tokyo23_scope import is_outside_tokyo_23_scope
from collection_support.x_official_source_accounts import official_account_for_url


DATA = Path("data")
DEFAULT_IN = DATA / "rare_signal_candidates.json"
DEFAULT_MANUAL_IN = DATA / "manual_x_rare_signal_candidates.json"
DEFAULT_OUT_JSON = DATA / "rare_signal_backcheck_queue.json"
DEFAULT_OUT_MD = DATA / "rare_signal_backcheck_queue.md"

DEFAULT_TARGETS = {"event", "song", "venue", "existing_evidence"}
SOCIAL_DOMAINS = ("x.com", "twitter.com", "t.co")


def load_json(path: Path, default):
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def md_cell(value) -> str:
    if isinstance(value, list):
        value = "; ".join(str(item) for item in value)
    text = str(value or "").replace("\n", " ").replace("|", "\\|").strip()
    return text[:180] + "..." if len(text) > 180 else text


def first_nonempty(*values) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def add_query(queries: list[str], *parts) -> None:
    query = " ".join(str(part).strip() for part in parts if str(part or "").strip())
    query = " ".join(query.split())
    if query and query not in queries:
        queries.append(query)


def expanded_queries(row: dict) -> list[str]:
    queries: list[str] = []
    for query in row.get("web_backcheck_queries") or []:
        if isinstance(query, str) and query.strip() and query.strip() not in queries:
            queries.append(query.strip())

    event = row.get("possible_event_name") or ""
    venue = row.get("possible_venue") or ""
    area = row.get("possible_area") or ""
    date = row.get("possible_date_text") or ""

    add_query(queries, event, venue, date)
    add_query(queries, event, area, "公式")
    add_query(queries, event, venue, "主催")
    add_query(queries, event, "自治体")
    add_query(queries, venue, "盆踊り", date)

    return queries[:8]


def suggested_source_types(row: dict) -> list[str]:
    if official_social_sources(row):
        return ["official_or_organizer_social", "municipality", "venue_site", "local_media"]
    if source_officiality_class(row) == "candidate_official_social":
        return ["official_social_account_review", "municipality", "venue_site", "local_media"]
    target = row.get("promotion_target") or ""
    if target == "song":
        return ["official_program", "organizer_page", "video_or_setlist_evidence", "local_media"]
    if target == "venue":
        return ["venue_site", "municipality", "organizer_page", "local_media"]
    if target == "existing_evidence":
        return ["official_or_organizer", "local_media", "venue_site", "trusted_field_report"]
    return ["official_or_organizer", "municipality", "venue_site", "local_media"]


def source_policy(row: dict) -> str:
    if official_social_sources(row):
        return "registered_official_social_review_required"
    if source_officiality_class(row) == "candidate_official_social":
        return "candidate_official_social_account_review_required"
    source_types = set()
    for url in row.get("source_urls") or []:
        hostish = str(url).lower()
        if any(domain in hostish for domain in SOCIAL_DOMAINS):
            source_types.add("x")
    if source_types == {"x"}:
        return "x_discovery_only_non_x_confirmation_required"
    return "discovery_source_requires_confirmation"


def source_officiality_class(row: dict) -> str:
    source_officiality = row.get("source_officiality")
    if not isinstance(source_officiality, dict):
        return ""
    return source_officiality.get("classification") or ""


def official_social_sources(row: dict) -> list[dict]:
    sources = []
    for url in row.get("source_urls") or []:
        account = official_account_for_url(str(url))
        if account:
            sources.append(
                {
                    "url": str(url),
                    "handle": account.get("handle") or "",
                    "name": account.get("name") or "",
                    "source_type": account.get("source_type") or "official_or_organizer_social",
                    "trust_level": account.get("trust_level") or "organizer_official",
                }
            )
    return sources


def row_to_queue(row: dict, generated_at: str) -> dict:
    matched_event_names = [
        item.get("name")
        for item in row.get("matched_existing_events") or []
        if isinstance(item, dict) and item.get("name")
    ]
    matched_venue_names = [
        item.get("name")
        for item in row.get("matched_existing_venues") or []
        if isinstance(item, dict) and item.get("name")
    ]
    primary_name = first_nonempty(
        row.get("possible_event_name"),
        row.get("possible_venue"),
        ", ".join(row.get("possible_song_names") or []),
        row.get("candidate_id"),
    )
    official_social = official_social_sources(row)
    source_officiality = row.get("source_officiality") if isinstance(row.get("source_officiality"), dict) else {}
    candidate_official = source_officiality.get("classification") == "candidate_official_social"
    return {
        "candidate_id": row.get("candidate_id") or "",
        "generated_at": generated_at,
        "backcheck_status": "pending",
        "source_policy": source_policy(row),
        "promotion_target": row.get("promotion_target") or "",
        "novelty_assessment": row.get("novelty_assessment") or "",
        "primary_name": primary_name,
        "possible_event_name": row.get("possible_event_name") or "",
        "possible_venue": row.get("possible_venue") or "",
        "possible_area": row.get("possible_area") or "",
        "possible_date_text": row.get("possible_date_text") or "",
        "possible_song_names": row.get("possible_song_names") or [],
        "oto_interpreted_summary": row.get("oto_interpreted_summary") or "",
        "novelty_reason": row.get("novelty_reason") or "",
        "matched_existing_events": matched_event_names,
        "matched_existing_venues": matched_venue_names,
        "suggested_source_types": suggested_source_types(row),
        "search_queries": expanded_queries(row),
        "confirmed_source_urls": [item["url"] for item in official_social],
        "confirmed_source_type": "official_or_organizer_social" if official_social else "",
        "confirmation_notes": (
            "registered official/organizer X account; review post text before publishing"
            if official_social else ""
        ),
        "decision": "pending",
        "next_action": (
            "review_official_social_post"
            if official_social
            else "review_source_account_then_find_confirmation"
            if candidate_official
            else "find_non_x_confirmation"
        ),
        "internal_discovery_urls": row.get("source_urls") or [],
        "official_social_sources": official_social,
        "source_officiality": source_officiality,
    }


def merge_payloads(payload: dict, manual_payload: dict | None = None) -> dict:
    merged = dict(payload or {})
    candidates = []
    seen = set()
    for source_payload in [payload or {}, manual_payload or {}]:
        for row in source_payload.get("candidates") or []:
            if not isinstance(row, dict):
                continue
            candidate_id = row.get("candidate_id") or ""
            if candidate_id and candidate_id in seen:
                continue
            if candidate_id:
                seen.add(candidate_id)
            candidates.append(row)
    merged["candidates"] = candidates
    if manual_payload:
        merged["manual_rare_signal_updated_at"] = manual_payload.get("updated_at") or manual_payload.get("generated_at") or ""
    return merged


def build(payload: dict, include_targets: set[str] | None = None, manual_payload: dict | None = None) -> dict:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = merge_payloads(payload, manual_payload)
    include_targets = include_targets or DEFAULT_TARGETS
    candidates = payload.get("candidates") or []
    rows = []
    skipped = []

    for row in candidates:
        if not isinstance(row, dict):
            continue
        target = row.get("promotion_target") or ""
        if target not in include_targets:
            skipped.append({
                "candidate_id": row.get("candidate_id") or "",
                "reason": "target_not_included",
                "promotion_target": target,
            })
            continue
        if (row.get("backcheck_status") or row.get("review_status")) not in {"", "needs_backcheck"}:
            skipped.append({
                "candidate_id": row.get("candidate_id") or "",
                "reason": "already_backchecked_or_not_pending",
                "promotion_target": target,
            })
            continue
        if is_outside_tokyo_23_scope(
            row.get("possible_event_name"),
            row.get("possible_venue"),
            row.get("possible_area"),
            row.get("oto_interpreted_summary"),
        ):
            skipped.append({
                "candidate_id": row.get("candidate_id") or "",
                "reason": "outside_tokyo_23_scope",
                "promotion_target": target,
                "possible_event_name": row.get("possible_event_name") or "",
                "possible_area": row.get("possible_area") or "",
                "possible_venue": row.get("possible_venue") or "",
            })
            continue
        rows.append(row_to_queue(row, generated_at))

    counts = Counter(row["promotion_target"] for row in rows)
    return {
        "generated_by": "build_rare_signal_backcheck_queue.py",
        "generated_at": generated_at,
        "input": {
            "rare_signal_generated_at": payload.get("generated_at") or "",
            "manual_rare_signal_updated_at": payload.get("manual_rare_signal_updated_at") or "",
            "include_targets": sorted(include_targets),
        },
        "summary": {
            "queue_count": len(rows),
            "skipped_count": len(skipped),
            "promotion_target_counts": dict(sorted(counts.items())),
        },
        "policy": {
            "x_role": "discovery_only_unless_registered_official_or_organizer_social",
            "public_text_source": "oto_interpreted_summary_and_confirmed_sources",
            "promotion_requires": "official_organizer_social_municipality_local_media_or_other_confirmation",
        },
        "queue": rows,
        "skipped": skipped,
    }


def write_markdown(data: dict, path: Path) -> None:
    lines = [
        "# Rare Signal Web Backcheck Queue",
        "",
        f"- generated_at: {data['generated_at']}",
        f"- queue_count: {data['summary']['queue_count']}",
        f"- skipped_count: {data['summary']['skipped_count']}",
        "- policy: X is discovery only; publish from Oto summary plus confirmed non-X sources.",
        "",
        "| status | target | name | date | area/venue | Oto summary | queries | source types |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in data["queue"]:
        area_venue = " / ".join(
            item for item in [row.get("possible_area") or "", row.get("possible_venue") or ""] if item
        )
        lines.append(
            f"| {md_cell(row['backcheck_status'])} | {md_cell(row['promotion_target'])} | "
            f"{md_cell(row['primary_name'])} | {md_cell(row['possible_date_text'])} | "
            f"{md_cell(area_venue)} | {md_cell(row['oto_interpreted_summary'])} | "
            f"{md_cell(row['search_queries'])} | {md_cell(row['suggested_source_types'])} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_targets(value: str) -> set[str]:
    targets = {item.strip() for item in value.split(",") if item.strip()}
    return targets or set(DEFAULT_TARGETS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_IN)
    parser.add_argument("--manual-input", type=Path, default=DEFAULT_MANUAL_IN)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    parser.add_argument(
        "--include-targets",
        default="event",
        help="Comma-separated promotion_target values to queue. Default: event",
    )
    args = parser.parse_args()

    payload = load_json(args.input, {"candidates": []})
    manual_payload = load_json(args.manual_input, {"candidates": []})
    data = build(payload, include_targets=parse_targets(args.include_targets), manual_payload=manual_payload)
    write_json(args.out_json, data)
    write_markdown(data, args.out_md)
    print(
        f"rare signal backcheck queue: {data['summary']['queue_count']} "
        f"(skipped {data['summary']['skipped_count']}) -> {args.out_json} / {args.out_md}"
    )


if __name__ == "__main__":
    main()
