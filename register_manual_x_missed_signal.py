#!/usr/bin/env python3
"""Register a manually found X post as a missed rare-signal seed.

The script does not fetch X. It records the URL, account, and Oto/Uchida
summary so the post can enter the rare-signal back-check flow and the account
can be considered for future collection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


DATA = Path("data")
DEFAULT_LOG = DATA / "manual_x_missed_signals.json"
DEFAULT_LOG_MD = DATA / "manual_x_missed_signals.md"
DEFAULT_RARE = DATA / "manual_x_rare_signal_candidates.json"
DEFAULT_ACCOUNTS = DATA / "x_manual_account_candidates.json"

X_STATUS_RE = re.compile(r"^/(?:i/web/)?(?P<handle>[^/]+)/status/(?P<tweet_id>\d+)")
VALID_TARGETS = {"event", "song", "venue", "existing_evidence"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path, default):
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_x_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().replace("twitter.com", "x.com")
    path = parsed.path.rstrip("/")
    return f"https://{host}{path}"


def parse_x_url(url: str) -> tuple[str, str]:
    normalized = normalize_x_url(url)
    parsed = urlparse(normalized)
    if parsed.netloc not in {"x.com", "www.x.com"}:
        raise ValueError("Xの投稿URLを指定してください")
    match = X_STATUS_RE.match(parsed.path)
    if not match:
        raise ValueError("X投稿URLは https://x.com/{handle}/status/{id} の形で指定してください")
    return match.group("handle"), match.group("tweet_id")


def candidate_id(url: str) -> str:
    return "manual_x_" + hashlib.sha1(normalize_x_url(url).encode("utf-8")).hexdigest()[:16]


def md_cell(value) -> str:
    text = str(value or "").replace("\n", " ").replace("|", "\\|").strip()
    return text[:180] + "..." if len(text) > 180 else text


def add_query(queries: list[str], *parts) -> None:
    query = " ".join(str(part).strip() for part in parts if str(part or "").strip())
    query = " ".join(query.split())
    if query and query not in queries:
        queries.append(query)


def backcheck_queries(args) -> list[str]:
    queries: list[str] = []
    for query in args.query or []:
        add_query(queries, query)
    add_query(queries, args.event_name, args.venue, args.date_text)
    add_query(queries, args.event_name, args.area, "公式")
    add_query(queries, args.event_name, args.venue, "主催")
    add_query(queries, args.event_name, "自治体")
    add_query(queries, args.venue, "盆踊り", args.date_text)
    return queries[:8]


def upsert_by_key(rows: list[dict], key: str, new_row: dict) -> tuple[list[dict], bool]:
    updated = False
    out = []
    for row in rows:
        if row.get(key) == new_row.get(key):
            merged = {**row, **new_row}
            out.append(merged)
            updated = True
        else:
            out.append(row)
    if not updated:
        out.append(new_row)
    return out, updated


def build_signal(args, generated_at: str) -> dict:
    url = normalize_x_url(args.url)
    handle, tweet_id = parse_x_url(url)
    return {
        "manual_signal_id": candidate_id(url),
        "registered_at": generated_at,
        "source_type": "manual_x_missed_signal",
        "source_url": url,
        "source_author": f"@{handle}",
        "tweet_id": tweet_id,
        "summary": args.summary.strip(),
        "event_name": args.event_name.strip(),
        "venue": args.venue.strip(),
        "area": args.area.strip(),
        "date_text": args.date_text.strip(),
        "promotion_target": args.promotion_target,
        "novelty_assessment": args.novelty,
        "notes": args.note.strip(),
        "status": "needs_backcheck",
    }


def signal_to_rare_candidate(signal: dict, queries: list[str]) -> dict:
    return {
        "candidate_id": signal["manual_signal_id"],
        "generated_at": signal["registered_at"],
        "source_type": "manual_x_missed_signal",
        "source_urls": [signal["source_url"]],
        "source_authors": [signal["source_author"]],
        "internal_source_excerpt": "",
        "oto_interpreted_summary": signal["summary"],
        "oto_notes": signal.get("notes") or "",
        "information_type": "manual_missed_x_signal",
        "promotion_target": signal["promotion_target"],
        "novelty_assessment": signal["novelty_assessment"],
        "novelty_reason": "手動で重要な見逃しX投稿として追加されたため、非X根拠で裏どりする。",
        "possible_event_name": signal["event_name"],
        "possible_venue": signal["venue"],
        "possible_area": signal["area"],
        "possible_date_text": signal["date_text"],
        "possible_song_names": [],
        "matched_existing_events": [],
        "matched_existing_venues": [],
        "matched_existing_songs": [],
        "web_backcheck_queries": queries,
        "backcheck_status": "needs_backcheck",
        "review_status": "needs_backcheck",
        "machine_digest_summary": "manual_missed_x_signal",
    }


def signal_to_account_candidate(signal: dict) -> dict:
    return {
        "handle": signal["source_author"],
        "source_url": signal["source_url"],
        "first_seen_manual_signal_id": signal["manual_signal_id"],
        "recommendation": "review",
        "reason": "manual_missed_important_event_signal",
        "event_name": signal["event_name"],
        "area": signal["area"],
        "note": "重要なX見逃し投稿の発信元。収集メンバー候補としてレビューする。",
    }


def write_log_markdown(payload: dict, path: Path) -> None:
    lines = [
        "# Manual X Missed Signals",
        "",
        f"- updated_at: {payload['updated_at']}",
        f"- count: {len(payload['signals'])}",
        "",
        "| status | author | event | date | area/venue | url | summary |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["signals"]:
        area_venue = " / ".join(value for value in [row.get("area"), row.get("venue")] if value)
        lines.append(
            f"| {md_cell(row.get('status'))} | {md_cell(row.get('source_author'))} | "
            f"{md_cell(row.get('event_name'))} | {md_cell(row.get('date_text'))} | "
            f"{md_cell(area_venue)} | {md_cell(row.get('source_url'))} | {md_cell(row.get('summary'))} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def register(args) -> dict:
    if args.promotion_target not in VALID_TARGETS:
        raise ValueError(f"--promotion-target は {', '.join(sorted(VALID_TARGETS))} のいずれか")
    generated_at = now_iso()
    signal = build_signal(args, generated_at)
    queries = backcheck_queries(args)
    rare_candidate = signal_to_rare_candidate(signal, queries)
    account_candidate = signal_to_account_candidate(signal)

    log_payload = load_json(args.log, {"signals": []})
    log_rows, log_updated = upsert_by_key(log_payload.get("signals") or [], "source_url", signal)
    log_payload = {
        "generated_by": "register_manual_x_missed_signal.py",
        "updated_at": generated_at,
        "signals": log_rows,
    }
    write_json(args.log, log_payload)
    write_log_markdown(log_payload, args.log_md)

    rare_payload = load_json(args.rare_out, {"candidates": []})
    rare_rows, rare_updated = upsert_by_key(rare_payload.get("candidates") or [], "candidate_id", rare_candidate)
    write_json(args.rare_out, {
        "generated_by": "register_manual_x_missed_signal.py",
        "updated_at": generated_at,
        "candidates": rare_rows,
    })

    account_payload = load_json(args.accounts_out, {"candidates": []})
    account_rows, account_updated = upsert_by_key(account_payload.get("candidates") or [], "handle", account_candidate)
    write_json(args.accounts_out, {
        "generated_by": "register_manual_x_missed_signal.py",
        "updated_at": generated_at,
        "candidates": account_rows,
    })

    return {
        "signal": signal,
        "rare_candidate": rare_candidate,
        "account_candidate": account_candidate,
        "updated": {
            "log": log_updated,
            "rare_candidate": rare_updated,
            "account_candidate": account_updated,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--summary", required=True, help="Oto/Uchida interpretation, not raw X copy")
    parser.add_argument("--event-name", default="")
    parser.add_argument("--venue", default="")
    parser.add_argument("--area", default="")
    parser.add_argument("--date-text", default="")
    parser.add_argument("--promotion-target", default="event")
    parser.add_argument("--novelty", default="unclear")
    parser.add_argument("--note", default="")
    parser.add_argument("--query", action="append", default=[])
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--log-md", type=Path, default=DEFAULT_LOG_MD)
    parser.add_argument("--rare-out", type=Path, default=DEFAULT_RARE)
    parser.add_argument("--accounts-out", type=Path, default=DEFAULT_ACCOUNTS)
    args = parser.parse_args()

    result = register(args)
    signal = result["signal"]
    print(f"manual X missed signal registered: {signal['manual_signal_id']}")
    print(f"- source: {signal['source_url']}")
    print(f"- account candidate: {result['account_candidate']['handle']}")
    print(f"- rare signal candidate: {result['rare_candidate']['candidate_id']}")


if __name__ == "__main__":
    main()
