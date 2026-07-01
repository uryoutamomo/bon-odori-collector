#!/usr/bin/env python3
"""Merge collector public source URLs into the site data without deploying."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
COLLECTOR_EVENTS = ROOT / "data" / "public" / "events_public.json"
SITE_EVENTS = ROOT.parent / "bon-odori-site" / "data" / "events_public.json"
OUT_JSON = ROOT / "data" / "public_event_source_url_site_sync.json"
OUT_MD = ROOT / "data" / "public_event_source_url_site_sync.md"
CONFIRM = "SYNC PUBLIC EVENT SOURCE URLS"


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def event_key(event: dict[str, Any]) -> str:
    return f"{event.get('name') or ''}\u241f{event.get('venue') or ''}"


def source_url(source: Any) -> str:
    return str((source or {}).get("url") or "").strip() if isinstance(source, dict) else ""


def source_kind(source: Any) -> str:
    return str((source or {}).get("kind") or "web").strip() if isinstance(source, dict) else "web"


def has_source_url(source: Any) -> bool:
    return bool(source_url(source))


def source_rank(source: dict[str, Any]) -> tuple[int, int]:
    official_rank = 0 if source_kind(source) == "official" else 1
    return (official_rank, -len(source_url(source)))


def dedupe_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_url: dict[str, dict[str, Any]] = {}
    for source in sources:
        url = source_url(source)
        if not url:
            continue
        current = by_url.get(url)
        if current is None or source_rank(source) < source_rank(current):
            by_url[url] = source
    return sorted(by_url.values(), key=source_rank)


def merge_source_urls(site_sources: Any, collector_sources: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    site_list = [source for source in site_sources if isinstance(source, dict)] if isinstance(site_sources, list) else []
    collector_list = [source for source in collector_sources if isinstance(source, dict)] if isinstance(collector_sources, list) else []
    site_urls = {source_url(source) for source in site_list if has_source_url(source)}
    additions = [source for source in collector_list if has_source_url(source) and source_url(source) not in site_urls]
    if not additions:
        return site_list, []
    merged = dedupe_sources([source for source in site_list if has_source_url(source)] + additions)
    return merged, additions


def build_site_events(
    collector_events: list[dict[str, Any]],
    site_events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    collector_by_key = {event_key(event): event for event in collector_events}
    updated_events: list[dict[str, Any]] = []
    updated_rows: list[dict[str, Any]] = []
    missing_site_keys: list[str] = []

    for site_event in site_events:
        key = event_key(site_event)
        collector_event = collector_by_key.get(key)
        if not collector_event:
            updated_events.append(site_event)
            continue
        merged, additions = merge_source_urls(site_event.get("source_urls"), collector_event.get("source_urls"))
        if additions:
            updated = dict(site_event)
            updated["source_urls"] = merged
            updated_events.append(updated)
            updated_rows.append(
                {
                    "event_key": key,
                    "event_name": site_event.get("name") or "",
                    "venue": site_event.get("venue") or "",
                    "added_urls": [source_url(source) for source in additions],
                    "source_kinds": [source_kind(source) for source in additions],
                }
            )
        else:
            updated_events.append(site_event)

    site_keys = {event_key(event) for event in site_events}
    for key in sorted(set(collector_by_key) - site_keys):
        if any(has_source_url(source) for source in collector_by_key[key].get("source_urls") or []):
            missing_site_keys.append(key)
    return updated_events, updated_rows, missing_site_keys


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Public event source URL site sync",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- write_performed: {result['write_performed']}",
        f"- collector_events: `{result['sources']['collector_events']}`",
        f"- site_events: `{result['sources']['site_events']}`",
        f"- updated_event_count: {result['summary']['updated_event_count']}",
        f"- added_url_count: {result['summary']['added_url_count']}",
        f"- missing_site_key_count: {result['summary']['missing_site_key_count']}",
        f"- added_urls_by_kind: {result['summary']['added_urls_by_kind']}",
        "",
        "| event | venue | added urls |",
        "| --- | --- | --- |",
    ]
    for row in result["updated_rows"][:160]:
        lines.append(f"| {row['event_name']} | {row['venue']} | {'<br>'.join(row['added_urls'])} |")
    if result["missing_site_keys"]:
        lines.extend(["", "## Missing Site Keys", ""])
        lines.extend(f"- {key}" for key in result["missing_site_keys"][:80])
    lines.append("")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.write and args.confirm != CONFIRM:
        raise ValueError(f"--write requires --confirm {CONFIRM!r}")
    collector_events = load_json(args.collector_events, [])
    site_events = load_json(args.site_events, [])
    if not isinstance(collector_events, list):
        raise ValueError(f"{args.collector_events} is not a JSON array")
    if not isinstance(site_events, list):
        raise ValueError(f"{args.site_events} is not a JSON array")

    proposed_events, updated_rows, missing_site_keys = build_site_events(collector_events, site_events)
    write_performed = False
    if args.write:
        args.site_events.write_text(json.dumps(proposed_events, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_performed = True

    added_kinds = Counter(kind for row in updated_rows for kind in row["source_kinds"])
    result = {
        "generated_by": "sync_public_event_source_urls_to_site.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "write" if args.write else "dry_run",
        "write_performed": write_performed,
        "sources": {
            "collector_events": str(args.collector_events),
            "site_events": str(args.site_events),
        },
        "summary": {
            "collector_event_count": len(collector_events),
            "site_event_count": len(site_events),
            "updated_event_count": len(updated_rows),
            "added_url_count": sum(len(row["added_urls"]) for row in updated_rows),
            "missing_site_key_count": len(missing_site_keys),
            "added_urls_by_kind": dict(added_kinds),
        },
        "updated_rows": updated_rows,
        "missing_site_keys": missing_site_keys,
    }
    write_json(args.out_json, result)
    args.out_md.write_text(render_markdown(result), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collector-events", type=Path, default=COLLECTOR_EVENTS)
    parser.add_argument("--site-events", type=Path, default=SITE_EVENTS)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        result = run(args)
    except ValueError as exc:
        parser.error(str(exc))
    print(
        "public event source URL site sync: "
        f"mode={result['mode']} updated={result['summary']['updated_event_count']} "
        f"added_urls={result['summary']['added_url_count']} write={result['write_performed']} out={args.out_json}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
