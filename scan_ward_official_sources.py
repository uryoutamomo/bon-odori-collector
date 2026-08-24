#!/usr/bin/env python3
"""Scan ward-owned source pages into official-source review candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from collection_support.proactive_search import BON_KEYWORDS, scan_official_sources


ROOT = Path(__file__).resolve().parent
DEFAULT_REGISTRY = ROOT / "data/ward_official_source_registry.json"
DEFAULT_OUTPUT = ROOT / "data/ward_official_source_candidates.json"
DEFAULT_MARKDOWN = ROOT / "data/ward_official_source_candidates.md"
SAFETY_BOUNDARY = "official-source review candidates only; no canonical or public event write"


def load_registry(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    priority_wards = set(payload.get("priority_wards") or [])
    sources = payload.get("sources")
    if not isinstance(sources, list):
        raise ValueError("ward official-source registry requires sources list")
    identifiers = [str(row.get("id") or "") for row in sources]
    if not all(identifiers) or len(identifiers) != len(set(identifiers)):
        raise ValueError("ward official-source registry ids must be non-empty and unique")
    for row in sources:
        if row.get("ward") not in priority_wards:
            raise ValueError(f"source ward is not registered as priority: {row.get('ward')}")
        host = urlparse(str(row.get("url") or "")).hostname or ""
        if not (host.endswith(".lg.jp") or host.endswith(".tokyo.jp")):
            raise ValueError(f"source is not on an official ward domain: {row.get('url')}")
    return [row for row in sources if row.get("enabled", True)]


def target_for(source: dict) -> dict:
    return {
        "venue": source["ward"],
        "event_name": source["title"],
        "aliases": [source["ward"]],
        "confirmation_terms": list(BON_KEYWORDS),
        "official_sources": [source["url"]],
        "official_source_type": "official",
    }


def stable_id(source_id: str, url: str) -> str:
    return "ward-official-" + hashlib.sha1(f"{source_id}|{url}".encode()).hexdigest()[:16]


def candidate_row(source: dict, scan: dict, year: int) -> dict:
    url = str(scan.get("source_url") or source["url"])
    title = str(scan.get("title") or source["title"])
    evidence = scan.get("evidence") if isinstance(scan.get("evidence"), dict) else {}
    memo = " / ".join(
        value for value in (
            f"ward registry: {source['id']}",
            str(evidence.get("text") or "")[:500],
            str(source.get("crawl_notes") or ""),
        ) if value
    )
    return {
        "id": stable_id(source["id"], url),
        "decision": "pending",
        "suggested_source_type": "official",
        "suggested_score": 90 if source.get("priority") == "high" else 85,
        "reason": "区公式source registryから盆踊り文脈を発見",
        "source_origin": "ward_official_source_registry",
        "source_registry_id": source["id"],
        "source_url": url,
        "source_domain": urlparse(url).netloc.lower(),
        "venue": "",
        "event_name": title,
        "region": source["ward"],
        "event_year": year,
        "event_date_text": ", ".join(scan.get("detected_dates") or []),
        "memo": memo,
        "registry_source_type": source.get("source_type") or "",
        "registry_format": source.get("format") or "",
    }


def scan_registry(sources: list[dict], year: int, *, timeout: int = 20, scan_fn=scan_official_sources) -> tuple[list[dict], list[dict]]:
    rows, source_reports = [], []
    for source in sources:
        scanned = scan_fn(target_for(source), year, timeout=timeout, max_links_per_source=12)
        confirmed = [row for row in scanned if row.get("status") == "confirmed"]
        rows.extend(candidate_row(source, row, year) for row in confirmed)
        source_reports.append(
            {
                "source_registry_id": source["id"],
                "ward": source["ward"],
                "url": source["url"],
                "checked_count": len(scanned),
                "confirmed_count": len(confirmed),
                "status": "confirmed" if confirmed else "no_bon_context_found",
            }
        )
    deduped = {row["id"]: row for row in rows}
    return sorted(deduped.values(), key=lambda row: (row["region"], row["source_url"])), source_reports


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown(path: Path, payload: dict) -> None:
    lines = [
        "# 区公式ソース発見候補",
        "",
        f"- safety: {payload['safety_boundary']}",
        f"- registry sources: {payload['registry_source_count']}",
        f"- candidates: {payload['candidate_count']}",
        "",
        "| 区 | ページ | URL | 日付候補 |",
        "|---|---|---|---|",
    ]
    for row in payload["rows"]:
        lines.append(f"| {row['region']} | {row['event_name'].replace('|', '｜')} | [link]({row['source_url']}) | {row['event_date_text']} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()
    sources = load_registry(args.registry)
    rows, source_reports = scan_registry(sources, args.year, timeout=args.timeout)
    payload = {
        "schema_version": 1,
        "generated_by": "scan_ward_official_sources.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_year": args.year,
        "safety_boundary": SAFETY_BOUNDARY,
        "canonical_write_count": 0,
        "registry_source_count": len(sources),
        "candidate_count": len(rows),
        "ward_counts": dict(Counter(row["region"] for row in rows)),
        "source_reports": source_reports,
        "rows": rows,
    }
    write_json(args.out_json, payload)
    write_markdown(args.out_md, payload)
    print(f"ward official sources: sources={len(sources)} candidates={len(rows)} -> {args.out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
