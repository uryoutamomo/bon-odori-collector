#!/usr/bin/env python3
"""Promote Oto-reviewed X news digest rows into rare signal candidates.

The input digest is machine-prepared and not trusted as final interpretation.
Only rows explicitly reviewed by Oto in a separate reviews file are promoted.
"""

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


DATA = Path("data")
DIGEST = DATA / "x_news_digest_for_oto.json"
REVIEWS = DATA / "x_news_digest_oto_reviews.json"
OUT_JSON = DATA / "rare_signal_candidates.json"
OUT_MD = DATA / "rare_signal_candidates.md"

PROMOTE_DECISIONS = {"promote", "accept", "採用", "昇格", "登録候補"}
HOLD_DECISIONS = {"hold", "保留"}
REJECT_DECISIONS = {"reject", "noise", "duplicate", "却下", "不採用", "重複"}
VALID_TARGETS = {"event", "song", "venue", "existing_evidence"}


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def review_rows(payload):
    rows = payload.get("reviews") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def review_index(payload):
    by_id = {}
    for row in review_rows(payload):
        candidate_id = row.get("candidate_id") or row.get("id") or ""
        if candidate_id:
            by_id[candidate_id] = row
    return by_id


def is_promote(review):
    return (review.get("decision") or "").strip() in PROMOTE_DECISIONS


def classify_skip(review):
    decision = (review.get("decision") or "").strip()
    if not decision:
        return "missing_decision"
    if decision in HOLD_DECISIONS:
        return "hold"
    if decision in REJECT_DECISIONS:
        return "reject"
    if decision not in PROMOTE_DECISIONS:
        return "unknown_decision"
    if not (review.get("oto_interpreted_summary") or "").strip():
        return "missing_oto_interpreted_summary"
    target = (review.get("promotion_target") or review.get("oto_promotion_target") or "").strip()
    if target and target not in VALID_TARGETS:
        return "invalid_promotion_target"
    return ""


def promote_row(digest_row, review, generated_at):
    def reviewed_or_digest(key, default=""):
        if key in review:
            return review.get(key) if review.get(key) is not None else default
        return digest_row.get(key) if digest_row.get(key) is not None else default

    target = (
        review.get("promotion_target")
        or review.get("oto_promotion_target")
        or digest_row.get("promotion_target")
        or "existing_evidence"
    )
    novelty = (
        review.get("oto_novelty_assessment")
        or review.get("novelty_assessment")
        or digest_row.get("novelty_assessment")
        or "unclear"
    )
    return {
        "candidate_id": digest_row["candidate_id"],
        "generated_at": generated_at,
        "source_type": "x_post",
        "source_urls": digest_row.get("source_urls") or [],
        "source_authors": digest_row.get("source_authors") or [],
        "internal_source_excerpt": digest_row.get("source_text_excerpt") or "",
        "oto_interpreted_summary": (review.get("oto_interpreted_summary") or "").strip(),
        "oto_notes": review.get("oto_notes") or review.get("note") or "",
        "information_type": reviewed_or_digest("information_type"),
        "promotion_target": target,
        "novelty_assessment": novelty,
        "novelty_reason": review.get("oto_novelty_reason") or review.get("novelty_reason") or digest_row.get("novelty_reason") or "",
        "possible_event_name": reviewed_or_digest("possible_event_name"),
        "possible_venue": reviewed_or_digest("possible_venue"),
        "possible_area": reviewed_or_digest("possible_area"),
        "possible_date_text": reviewed_or_digest("possible_date_text"),
        "possible_song_names": reviewed_or_digest("possible_song_names", []),
        "matched_existing_events": digest_row.get("matched_existing_events") or [],
        "matched_existing_venues": digest_row.get("matched_existing_venues") or [],
        "matched_existing_songs": digest_row.get("matched_existing_songs") or [],
        "source_officiality": digest_row.get("source_officiality") or {},
        "web_backcheck_queries": review.get("web_backcheck_queries") or digest_row.get("web_backcheck_queries") or [],
        "backcheck_status": review.get("backcheck_status") or "needs_backcheck",
        "review_status": "needs_backcheck",
        "machine_digest_summary": digest_row.get("machine_digest_summary") or "",
    }


def build(digest_payload, reviews_payload):
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    digest_rows = digest_payload.get("candidates") or []
    reviews = review_index(reviews_payload)
    promoted = []
    skipped = []

    for row in digest_rows:
        if not isinstance(row, dict):
            continue
        candidate_id = row.get("candidate_id") or ""
        review = reviews.get(candidate_id)
        if not review:
            continue
        reason = classify_skip(review)
        if reason:
            skipped.append({
                "candidate_id": candidate_id,
                "reason": reason,
                "decision": review.get("decision") or "",
            })
            continue
        promoted.append(promote_row(row, review, generated_at))

    target_counts = Counter(row["promotion_target"] for row in promoted)
    novelty_counts = Counter(row["novelty_assessment"] for row in promoted)
    return {
        "generated_by": "promote_x_news_digest_reviews.py",
        "generated_at": generated_at,
        "input": {
            "digest_generated_at": digest_payload.get("generated_at") or "",
        },
        "summary": {
            "review_count": len(reviews),
            "promoted_count": len(promoted),
            "skipped_count": len(skipped),
            "promotion_target_counts": dict(sorted(target_counts.items())),
            "novelty_counts": dict(sorted(novelty_counts.items())),
        },
        "candidates": promoted,
        "skipped": skipped,
    }


def md_cell(value):
    text = str(value or "").replace("\n", " ").replace("|", "\\|")
    return text[:180] + "..." if len(text) > 180 else text


def write_markdown(data, path):
    lines = [
        "# Rare Signal Candidates",
        "",
        f"- generated_at: {data['generated_at']}",
        f"- promoted_count: {data['summary']['promoted_count']}",
        f"- skipped_count: {data['summary']['skipped_count']}",
        "- status: Oto-reviewed candidates only",
        "",
        "| target | novelty | summary | reason | backcheck | source |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in data["candidates"]:
        lines.append(
            f"| {md_cell(row['promotion_target'])} | {md_cell(row['novelty_assessment'])} | "
            f"{md_cell(row['oto_interpreted_summary'])} | {md_cell(row['novelty_reason'])} | "
            f"{md_cell('; '.join(row.get('web_backcheck_queries') or []))} | "
            f"{md_cell((row.get('source_urls') or [''])[0])} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--digest", type=Path, default=DIGEST)
    parser.add_argument("--reviews", type=Path, default=REVIEWS)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    args = parser.parse_args()

    digest = load_json(args.digest, {"candidates": []})
    reviews = load_json(args.reviews, {"reviews": []})
    data = build(digest, reviews)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(data, args.out_md)
    print(
        f"rare signal promoted: {data['summary']['promoted_count']} "
        f"(skipped {data['summary']['skipped_count']}) -> {args.out_json} / {args.out_md}"
    )


if __name__ == "__main__":
    main()
