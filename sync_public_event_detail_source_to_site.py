#!/usr/bin/env python3
"""Sync only the `detail`/`source_urls` fields from collector public events into
the site data.

Scope is deliberately narrow, mirroring sync_public_event_songs_to_site.py: this
should reach production without dragging along unrelated pending diffs in other
high-risk fields still needing individual review per
public_json_postprocessors/guard_public_events_sync.py.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
COLLECTOR_EVENTS = ROOT / "data" / "public" / "events_public.json"
SITE_EVENTS = ROOT.parent / "bon-odori-site" / "data" / "events_public.json"
OUT_JSON = ROOT / "data" / "public_event_detail_source_site_sync.json"
OUT_MD = ROOT / "data" / "public_event_detail_source_site_sync.md"
CONFIRM = "SYNC PUBLIC EVENT DETAIL SOURCE"


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def event_key(event: dict[str, Any]) -> str:
    return f"{event.get('name') or ''}␟{event.get('venue') or ''}"


def build_site_events(
    collector_events: list[dict[str, Any]],
    site_events: list[dict[str, Any]],
    allowed_event_keys: set[str] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    collector_by_key = {event_key(event): event for event in collector_events}
    updated_events: list[dict[str, Any]] = []
    updated_rows: list[dict[str, Any]] = []

    for site_event in site_events:
        key = event_key(site_event)
        collector_event = collector_by_key.get(key)
        if not collector_event or (allowed_event_keys is not None and key not in allowed_event_keys):
            updated_events.append(site_event)
            continue
        old_detail = site_event.get("detail") or ""
        new_detail = collector_event.get("detail") or ""
        old_sources = site_event.get("source_urls") or []
        new_sources = collector_event.get("source_urls") or []
        detail_same = old_detail == new_detail
        sources_same = json.dumps(old_sources, ensure_ascii=False, sort_keys=True) == json.dumps(
            new_sources, ensure_ascii=False, sort_keys=True
        )
        if detail_same and sources_same:
            updated_events.append(site_event)
            continue
        updated = dict(site_event)
        updated["detail"] = new_detail
        updated["source_urls"] = new_sources
        updated_events.append(updated)
        updated_rows.append(
            {
                "event_key": key,
                "event_name": site_event.get("name") or "",
                "venue": site_event.get("venue") or "",
                "old_detail": old_detail,
                "new_detail": new_detail,
                "old_source_urls": old_sources,
                "new_source_urls": new_sources,
            }
        )

    return updated_events, updated_rows


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Public event detail/source_urls site sync",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- write_performed: {result['write_performed']}",
        f"- allowed_event_keys: {result['allowed_event_keys']}",
        f"- updated_event_count: {result['summary']['updated_event_count']}",
        "",
    ]
    for row in result["updated_rows"]:
        lines.extend(
            [
                f"## {row['event_name']} / {row['venue']}",
                f"- old detail: {row['old_detail']!r}",
                f"- new detail: {row['new_detail']!r}",
                f"- old source_urls: {row['old_source_urls']}",
                f"- new source_urls: {row['new_source_urls']}",
                "",
            ]
        )
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

    allowed_event_keys = set(args.event_key) if args.event_key else None
    proposed_events, updated_rows = build_site_events(collector_events, site_events, allowed_event_keys)
    write_performed = False
    if args.write:
        args.site_events.write_text(
            json.dumps(proposed_events, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        write_performed = True

    result = {
        "generated_by": "sync_public_event_detail_source_to_site.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "write" if args.write else "dry_run",
        "write_performed": write_performed,
        "allowed_event_keys": sorted(allowed_event_keys) if allowed_event_keys else None,
        "sources": {
            "collector_events": str(args.collector_events),
            "site_events": str(args.site_events),
        },
        "summary": {
            "collector_event_count": len(collector_events),
            "site_event_count": len(site_events),
            "updated_event_count": len(updated_rows),
        },
        "updated_rows": updated_rows,
    }
    write_json(args.out_json, result)
    args.out_md.write_text(render_markdown(result), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collector-events", type=Path, default=COLLECTOR_EVENTS)
    parser.add_argument("--site-events", type=Path, default=SITE_EVENTS)
    parser.add_argument(
        "--event-key",
        action="append",
        default=[],
        help="name␟venue key to restrict the sync to; repeatable. Omit to sync every diff found.",
    )
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
        "public event detail/source_urls site sync: "
        f"mode={result['mode']} updated={result['summary']['updated_event_count']} "
        f"write={result['write_performed']} out={args.out_json}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
