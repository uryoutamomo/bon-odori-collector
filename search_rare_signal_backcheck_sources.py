#!/usr/bin/env python3
"""Collect non-X web source candidates for rare signal back-check review.

This helper searches web results for each row in rare_signal_backcheck_queue.
It deliberately does not confirm candidates or create review decisions. The
output is a research aid for the review console / human back-check step.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from x_official_source_accounts import official_account_for_url


DATA = Path("data")
DEFAULT_IN = DATA / "rare_signal_backcheck_queue.json"
DEFAULT_OUT_JSON = DATA / "rare_signal_backcheck_search_results.json"
DEFAULT_OUT_MD = DATA / "rare_signal_backcheck_search_results.md"

SOCIAL_DOMAINS = (
    "x.com",
    "twitter.com",
    "t.co",
    "facebook.com",
    "instagram.com",
    "threads.net",
    "tiktok.com",
)
OFFICIAL_HINTS = (
    ".lg.jp",
    ".go.jp",
    "city.",
    "town.",
    "vill.",
    "ward.",
    "shotengai",
    "shoutengai",
    "syoutengai",
    "商店街",
)
LOCAL_MEDIA_HINTS = (
    "townnews",
    "machida",
    "itabashi-times",
    "akasaka",
    "keizai",
    "news",
    "local",
    "jimotononews",
)
TICKET_OR_PRESS_HINTS = ("prtimes", "peatix", "passmarket", "eventernote", "eplus")
NOISE_HINTS = (
    "map",
    "maps",
    "hotel",
    "jalan",
    "rakuten",
    "tripadvisor",
    "weather",
    "travel.yahoo",
    "trvbook",
)


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


def bing_rss_url(query: str) -> str:
    params = urllib.parse.urlencode({"format": "rss", "q": query})
    return f"https://www.bing.com/search?{params}"


def fetch_rss(query: str, timeout: int = 15) -> str:
    request = urllib.request.Request(
        bing_rss_url(query),
        headers={"User-Agent": "bon-odori-collector rare-signal-backcheck/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_rss(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    rows = []
    for item in root.findall(".//item"):
        rows.append(
            {
                "title": text_of(item, "title"),
                "url": text_of(item, "link"),
                "description": text_of(item, "description"),
            }
        )
    return rows


def text_of(item: ET.Element, tag: str) -> str:
    child = item.find(tag)
    return "".join(child.itertext()).strip() if child is not None else ""


def hostname(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.lower()
    except ValueError:
        return ""


def classify_url(url: str) -> str:
    host = hostname(url)
    low = url.lower()
    if not host:
        return "search_noise"
    if any(domain in host for domain in SOCIAL_DOMAINS):
        return "social"
    if any(hint in low for hint in NOISE_HINTS):
        return "search_noise"
    if any(hint in low for hint in OFFICIAL_HINTS):
        return "official_or_public"
    if any(hint in low for hint in LOCAL_MEDIA_HINTS):
        return "local_media"
    if any(hint in low for hint in TICKET_OR_PRESS_HINTS):
        return "ticket_or_press"
    return "generic_non_x"


def tokens(*values) -> set[str]:
    found: set[str] = set()
    for value in values:
        text = str(value or "")
        for raw in text.replace("　", " ").replace("/", " ").split():
            token = raw.strip("「」『』()（）[]【】,:：、。.-_")
            if len(token) >= 2:
                found.add(token)
    return found


def relevance_hint(row: dict, result: dict) -> str:
    row_tokens = tokens(
        row.get("primary_name"),
        row.get("possible_event_name"),
        row.get("possible_venue"),
        row.get("possible_area"),
        row.get("possible_date_text"),
    )
    result_tokens = tokens(result.get("title"), result.get("description"), result.get("url"))
    overlap = sorted(row_tokens & result_tokens)
    if row.get("possible_event_name") and row.get("possible_event_name") in (
        (result.get("title") or "") + " " + (result.get("description") or "")
    ):
        return "event_name_match"
    if row.get("possible_venue") and row.get("possible_venue") in (
        (result.get("title") or "") + " " + (result.get("description") or "")
    ):
        return "venue_match"
    if len(overlap) >= 2:
        return "token_overlap:" + ",".join(overlap[:4])
    if overlap:
        return "weak_overlap:" + ",".join(overlap[:3])
    return "unmatched"


def should_keep_result(row: dict, result: dict) -> bool:
    source_type = classify_url(result.get("url") or "")
    if source_type == "social" and official_account_for_url(result.get("url") or ""):
        return True
    if source_type in {"social", "search_noise"}:
        return False
    hint = relevance_hint(row, result)
    return hint == "event_name_match" or hint.startswith("token_overlap:")


def source_type_for_candidate(url: str) -> str:
    account = official_account_for_url(url)
    if account:
        return account.get("source_type") or "official_or_organizer_social"
    return classify_url(url)


def official_social_candidates(row: dict) -> list[dict]:
    candidates = []
    seen = set()
    urls = []
    urls.extend(row.get("confirmed_source_urls") or [])
    urls.extend(row.get("internal_discovery_urls") or [])
    urls.extend(row.get("source_urls") or [])
    for url in urls:
        url = str(url or "").strip()
        if not url or url in seen:
            continue
        account = official_account_for_url(url)
        if not account:
            continue
        seen.add(url)
        candidates.append(
            {
                "title": (
                    f"{account.get('name') or account.get('handle') or 'official account'} "
                    "X post"
                ),
                "url": url,
                "description": row.get("oto_interpreted_summary") or "",
                "source_type": account.get("source_type") or "official_or_organizer_social",
                "relevance_hint": "registered_official_social_account",
                "query": "internal_discovery_url",
                "account": account.get("handle") or "",
                "account_name": account.get("name") or "",
                "trust_level": account.get("trust_level") or "",
            }
        )
    return candidates


def default_fetcher(query: str, timeout: int) -> list[dict]:
    return parse_rss(fetch_rss(query, timeout=timeout))


def build(
    payload: dict,
    fetcher: Callable[[str, int], list[dict]] = default_fetcher,
    *,
    max_candidates: int | None = None,
    queries_per_candidate: int = 3,
    timeout: int = 15,
    sleep_seconds: float = 0.0,
) -> dict:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = [row for row in payload.get("queue") or [] if isinstance(row, dict)]
    if max_candidates is not None:
        rows = rows[:max_candidates]

    candidates = []
    query_count = 0
    result_count = 0
    non_x_result_count = 0
    source_type_counts: Counter[str] = Counter()
    official_social_source_count = 0

    for row in rows:
        attempts = []
        source_candidates = official_social_candidates(row)
        official_social_source_count += len(source_candidates)
        for candidate in source_candidates:
            source_type_counts[candidate["source_type"]] += 1
        seen_urls = set()
        for candidate in source_candidates:
            seen_urls.add(candidate["url"])
        queries = [q for q in row.get("search_queries") or [] if isinstance(q, str) and q.strip()]

        for query in queries[:queries_per_candidate]:
            query_count += 1
            try:
                results = fetcher(query, timeout)
                status = "ok"
                error = ""
            except Exception as exc:  # pragma: no cover - exercised by manual network runs
                results = []
                status = "error"
                error = str(exc)

            result_count += len(results)
            kept_for_attempt = 0
            for result in results:
                url = result.get("url") or ""
                source_type = classify_url(url)
                source_type_counts[source_type] += 1
                if source_type != "social":
                    non_x_result_count += 1
                if url in seen_urls or not should_keep_result(row, result):
                    continue
                seen_urls.add(url)
                kept_for_attempt += 1
                candidate_source_type = source_type_for_candidate(url)
                source_candidates.append(
                    {
                        "title": result.get("title") or "",
                        "url": url,
                        "description": result.get("description") or "",
                        "source_type": candidate_source_type,
                        "relevance_hint": (
                            "registered_official_social_account"
                            if candidate_source_type == "official_or_organizer_social"
                            else relevance_hint(row, result)
                        ),
                        "query": query,
                    }
                )

            attempts.append(
                {
                    "query": query,
                    "status": status,
                    "error": error,
                    "result_count": len(results),
                    "kept_count": kept_for_attempt,
                }
            )
            if sleep_seconds:
                time.sleep(sleep_seconds)

        candidates.append(
            {
                "candidate_id": row.get("candidate_id") or "",
                "primary_name": row.get("primary_name") or "",
                "possible_date_text": row.get("possible_date_text") or "",
                "possible_venue": row.get("possible_venue") or "",
                "oto_interpreted_summary": row.get("oto_interpreted_summary") or "",
                "backcheck_status": (
                    "source_candidates_found" if source_candidates else "no_candidate_sources_found"
                ),
                "attempts": attempts,
                "source_candidates": source_candidates,
            }
        )

    candidate_source_count = sum(len(row["source_candidates"]) for row in candidates)
    return {
        "generated_by": "search_rare_signal_backcheck_sources.py",
        "generated_at": generated_at,
        "input": {
            "rare_signal_backcheck_generated_at": payload.get("generated_at") or "",
            "max_candidates": max_candidates,
            "queries_per_candidate": queries_per_candidate,
        },
        "policy": {
            "does_not_confirm": True,
            "x_role": "discovery_only_unless_registered_official_or_organizer_social",
            "output_role": "source_candidates_for_manual_review",
        },
        "summary": {
            "candidate_count": len(candidates),
            "query_count": query_count,
            "result_count": result_count,
            "non_x_result_count": non_x_result_count,
            "candidate_source_count": candidate_source_count,
            "official_social_source_count": official_social_source_count,
            "source_type_counts": dict(sorted(source_type_counts.items())),
        },
        "candidates": candidates,
    }


def write_markdown(data: dict, path: Path) -> None:
    lines = [
        "# Rare Signal Backcheck Search Results",
        "",
        f"- generated_at: {data['generated_at']}",
        f"- candidate_count: {data['summary']['candidate_count']}",
        f"- query_count: {data['summary']['query_count']}",
        f"- candidate_source_count: {data['summary']['candidate_source_count']}",
        "- policy: search results are candidates only; they do not confirm rare signals.",
        "",
        "| candidate | source type | title | url | query | hint |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in data["candidates"]:
        if not row["source_candidates"]:
            lines.append(
                f"| {md_cell(row['primary_name'])} | none | no candidate source found |  |  |  |"
            )
            continue
        for source in row["source_candidates"]:
            lines.append(
                f"| {md_cell(row['primary_name'])} | {md_cell(source['source_type'])} | "
                f"{md_cell(source['title'])} | {md_cell(source['url'])} | "
                f"{md_cell(source['query'])} | {md_cell(source['relevance_hint'])} |"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_IN)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    parser.add_argument("--limit-candidates", type=int, default=None)
    parser.add_argument("--queries-per-candidate", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    args = parser.parse_args()

    payload = load_json(args.input, {"queue": []})
    data = build(
        payload,
        max_candidates=args.limit_candidates,
        queries_per_candidate=args.queries_per_candidate,
        timeout=args.timeout,
        sleep_seconds=args.sleep_seconds,
    )
    write_json(args.out_json, data)
    write_markdown(data, args.out_md)
    print(
        "rare signal backcheck search: "
        f"{data['summary']['candidate_source_count']} source candidates "
        f"from {data['summary']['query_count']} queries -> {args.out_json} / {args.out_md}"
    )


if __name__ == "__main__":
    main()
