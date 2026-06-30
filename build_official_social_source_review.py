#!/usr/bin/env python3
"""Build a review queue for official/organizer social source accounts."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from x_source_officiality import assess_source_officiality, load_account_profiles


DATA = Path("data")
DEFAULT_IN = DATA / "rare_signal_candidates.json"
DEFAULT_ACCOUNT_CANDIDATES = DATA / "x_candidate_accounts.json"
DEFAULT_OUT_JSON = DATA / "official_social_source_review_candidates.json"
DEFAULT_OUT_MD = DATA / "official_social_source_review_candidates.md"
REVIEWABLE_CLASSES = {"candidate_official_social", "community_source_candidate"}


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


def source_key(row: dict) -> str:
    officiality = row.get("source_officiality") or {}
    handle = officiality.get("handle") or ""
    if handle:
        return handle.lower()
    authors = row.get("source_authors") or []
    return str(authors[0] if authors else "").lower()


def review_row(row: dict, profiles: dict[str, dict]) -> dict | None:
    officiality = row.get("source_officiality")
    if not isinstance(officiality, dict) or not officiality:
        officiality = assess_source_officiality(row, account_profiles=profiles)
    classification = officiality.get("classification") or ""
    if classification not in REVIEWABLE_CLASSES:
        return None
    handle = officiality.get("handle") or (row.get("source_authors") or [""])[0]
    return {
        "review_status": "pending",
        "recommendation": (
            "register_if_profile_confirms_org"
            if classification == "candidate_official_social"
            else "watch_or_register_after_more_evidence"
        ),
        "handle": handle,
        "account_name": officiality.get("account_name") or "",
        "classification": classification,
        "score": officiality.get("score") or 0,
        "reasons": officiality.get("reasons") or [],
        "candidate_id": row.get("candidate_id") or "",
        "source_urls": row.get("source_urls") or [],
        "event_name": row.get("possible_event_name") or "",
        "venue": row.get("possible_venue") or "",
        "area": row.get("possible_area") or "",
        "date_text": row.get("possible_date_text") or "",
        "summary": row.get("oto_interpreted_summary") or row.get("machine_digest_summary") or "",
    }


def build(payload: dict, account_profiles: dict[str, dict] | None = None) -> dict:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    profiles = account_profiles or {}
    candidates = [row for row in payload.get("candidates") or [] if isinstance(row, dict)]
    by_handle = {}
    for row in candidates:
        review = review_row(row, profiles)
        if not review:
            continue
        key = (review.get("handle") or "").lower()
        existing = by_handle.get(key)
        if existing and existing.get("score", 0) >= review.get("score", 0):
            existing.setdefault("related_candidates", []).append(review["candidate_id"])
            continue
        review["related_candidates"] = [review["candidate_id"]]
        by_handle[key] = review

    rows = sorted(by_handle.values(), key=lambda row: (-row.get("score", 0), row.get("handle", "")))
    counts = Counter(row["classification"] for row in rows)
    return {
        "generated_by": "build_official_social_source_review.py",
        "generated_at": generated_at,
        "input": {
            "rare_signal_generated_at": payload.get("generated_at") or "",
        },
        "summary": {
            "candidate_account_count": len(rows),
            "classification_counts": dict(sorted(counts.items())),
        },
        "policy": {
            "does_not_register": True,
            "registered_accounts_live_in": "data/x_official_source_accounts.json",
            "review_rule": "Register only accounts whose profile/name clearly represents the organizer, municipality, venue, shrine, temple, town association, or shopping district.",
        },
        "accounts": rows,
    }


def write_markdown(data: dict, path: Path) -> None:
    lines = [
        "# Official Social Source Review Candidates",
        "",
        f"- generated_at: {data['generated_at']}",
        f"- candidate_account_count: {data['summary']['candidate_account_count']}",
        "- status: review only; does not mutate the official account registry",
        "",
        "| status | class | score | handle | name | event | date | source | reasons |",
        "| --- | --- | ---: | --- | --- | --- | --- | --- | --- |",
    ]
    for row in data["accounts"]:
        lines.append(
            f"| {md_cell(row['review_status'])} | {md_cell(row['classification'])} | "
            f"{md_cell(row['score'])} | {md_cell(row['handle'])} | {md_cell(row['account_name'])} | "
            f"{md_cell(row['event_name'])} | {md_cell(row['date_text'])} | "
            f"{md_cell(row['source_urls'])} | {md_cell(row['reasons'])} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_IN)
    parser.add_argument("--account-candidates", type=Path, default=DEFAULT_ACCOUNT_CANDIDATES)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    args = parser.parse_args()

    data = build(
        load_json(args.input, {"candidates": []}),
        account_profiles=load_account_profiles(args.account_candidates),
    )
    write_json(args.out_json, data)
    write_markdown(data, args.out_md)
    print(
        f"official social source review: {data['summary']['candidate_account_count']} "
        f"accounts -> {args.out_json} / {args.out_md}"
    )


if __name__ == "__main__":
    main()
