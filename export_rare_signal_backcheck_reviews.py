#!/usr/bin/env python3
"""Convert staged review-console rare-signal decisions into back-check reviews."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from x_official_source_accounts import is_official_social_url


DATA = Path("data")
DEFAULT_INPUT = DATA / "review_console" / "staged" / "rare_signal_backcheck_decisions.json"
DEFAULT_OUT = DATA / "rare_signal_backcheck_reviews.json"
DEFAULT_OUT_MD = DATA / "rare_signal_backcheck_reviews.md"

URL_RE = re.compile(r"https?://[^\s、，。)）\]}＞>\"']+")
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


def hostname(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def is_social_url(url: str) -> bool:
    host = hostname(url)
    return any(host == domain or host.endswith("." + domain) for domain in SOCIAL_DOMAINS)


def urls_from_note(note: str) -> list[str]:
    urls = []
    for match in URL_RE.findall(note or ""):
        url = match.rstrip(".,")
        if url and url not in urls:
            urls.append(url)
    return urls


def non_x_urls(urls: list[str]) -> list[str]:
    return [url for url in urls if not is_social_url(url)]


def confirmable_urls(urls: list[str]) -> list[str]:
    return [url for url in urls if not is_social_url(url) or is_official_social_url(url)]


def decision_for(row: dict) -> str:
    apply_value = row.get("apply_value") or ""
    decision = row.get("decision") or ""
    if apply_value == "confirm_non_x_source":
        return "confirm"
    if apply_value == "needs_non_x_backcheck" or decision == "needs_research":
        return "hold"
    if decision == "reject":
        return "reject"
    if decision == "hold":
        return "hold"
    return "hold"


def review_from_row(row: dict) -> dict:
    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    note = row.get("note") or ""
    urls = confirmable_urls(urls_from_note(note))
    decision = decision_for(row)
    source_type = "non_x_backcheck" if urls else ""
    if urls and all(is_official_social_url(url) for url in urls):
        source_type = "official_or_organizer_social"
    review = {
        "candidate_id": raw.get("candidate_id") or "",
        "decision": decision,
        "source_review_decision": row.get("decision") or "",
        "source_apply_value": row.get("apply_value") or "",
        "confirmed_source_urls": urls,
        "confirmed_source_type": source_type,
        "venue": raw.get("possible_venue") or "",
        "area": raw.get("possible_area") or "",
        "date_text": raw.get("possible_date_text") or "",
        "public_summary": raw.get("oto_interpreted_summary") or "",
        "confirmation_notes": note,
        "reviewed_at": row.get("reviewed_at") or "",
        "reviewed_by": row.get("reviewer") or "",
    }
    if decision == "confirm" and not urls:
        review["decision"] = "hold"
        review["review_warning"] = "confirm_without_confirmable_url_in_note"
    return review


def build(staged_payload: dict) -> dict:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = [row for row in staged_payload.get("rows") or [] if isinstance(row, dict)]
    reviews = []
    skipped = []
    for row in rows:
        if row.get("source_id") != "rare_signal_backcheck":
            skipped.append({"item_id": row.get("item_id") or "", "reason": "wrong_source"})
            continue
        review = review_from_row(row)
        if not review["candidate_id"]:
            skipped.append({"item_id": row.get("item_id") or "", "reason": "missing_candidate_id"})
            continue
        reviews.append(review)
    return {
        "generated_by": "export_rare_signal_backcheck_reviews.py",
        "generated_at": generated_at,
        "input": {
            "staged_generated_at": staged_payload.get("generated_at") or "",
            "source_id": staged_payload.get("source_id") or "",
        },
        "summary": {
            "review_count": len(reviews),
            "skipped_count": len(skipped),
            "confirmed_count": sum(1 for row in reviews if row.get("decision") == "confirm"),
        },
        "reviews": reviews,
        "skipped": skipped,
    }


def md_cell(value) -> str:
    if isinstance(value, list):
        value = "; ".join(str(item) for item in value)
    text = str(value or "").replace("\n", " ").replace("|", "\\|").strip()
    return text[:180] + "..." if len(text) > 180 else text


def write_markdown(data: dict, path: Path) -> None:
    lines = [
        "# Rare Signal Backcheck Reviews",
        "",
        f"- generated_at: {data['generated_at']}",
        f"- review_count: {data['summary']['review_count']}",
        f"- confirmed_count: {data['summary']['confirmed_count']}",
        "",
        "| decision | candidate | source urls | note |",
        "| --- | --- | --- | --- |",
    ]
    for row in data["reviews"]:
        lines.append(
            f"| {md_cell(row['decision'])} | {md_cell(row['candidate_id'])} | "
            f"{md_cell(row['confirmed_source_urls'])} | {md_cell(row['confirmation_notes'])} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    args = parser.parse_args()

    data = build(load_json(args.input, {"rows": []}))
    write_json(args.out, data)
    write_markdown(data, args.out_md)
    print(
        f"rare signal backcheck reviews: {data['summary']['review_count']} "
        f"(confirmed {data['summary']['confirmed_count']}) -> {args.out} / {args.out_md}"
    )


if __name__ == "__main__":
    main()
