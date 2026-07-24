#!/usr/bin/env python3
"""Sync only the `songs` field from collector public events into the site data.

Scope is deliberately narrow: song probability recomputation (RDB-native
calibration/inheritance) should reach production without dragging along
unrelated pending diffs in other high-risk fields (historical_slide,
date_prediction, historical_reference, detail, source_urls) that still need
individual review per public_json_postprocessors/guard_public_events_sync.py.
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
OUT_JSON = ROOT / "data" / "public_event_songs_site_sync.json"
OUT_MD = ROOT / "data" / "public_event_songs_site_sync.md"
CONFIRM = "SYNC PUBLIC EVENT SONGS"


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
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    collector_by_key = {event_key(event): event for event in collector_events}
    updated_events: list[dict[str, Any]] = []
    updated_rows: list[dict[str, Any]] = []

    for site_event in site_events:
        key = event_key(site_event)
        collector_event = collector_by_key.get(key)
        if not collector_event:
            updated_events.append(site_event)
            continue
        old_songs = site_event.get("songs") or []
        new_songs = collector_event.get("songs") or []
        if json.dumps(old_songs, ensure_ascii=False, sort_keys=True) == json.dumps(
            new_songs, ensure_ascii=False, sort_keys=True
        ):
            updated_events.append(site_event)
            continue
        updated = dict(site_event)
        updated["songs"] = new_songs
        updated_events.append(updated)
        updated_rows.append(
            {
                "event_key": key,
                "event_name": site_event.get("name") or "",
                "venue": site_event.get("venue") or "",
                "old_song_count": len(old_songs),
                "new_song_count": len(new_songs),
                "old_song_names": [s.get("name") for s in old_songs if isinstance(s, dict)],
                "new_song_names": [s.get("name") for s in new_songs if isinstance(s, dict)],
            }
        )

    site_keys = {event_key(event) for event in site_events}
    missing_site_keys = sorted(
        key
        for key in set(collector_by_key) - site_keys
        if collector_by_key[key].get("songs")
    )
    return updated_events, updated_rows, missing_site_keys


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Public event songs site sync",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- write_performed: {result['write_performed']}",
        f"- collector_events: `{result['sources']['collector_events']}`",
        f"- site_events: `{result['sources']['site_events']}`",
        f"- updated_event_count: {result['summary']['updated_event_count']}",
        f"- missing_site_key_count: {result['summary']['missing_site_key_count']}",
        "",
        "| event | venue | old songs | new songs |",
        "| --- | --- | --- | --- |",
    ]
    for row in result["updated_rows"][:220]:
        lines.append(
            f"| {row['event_name']} | {row['venue']} | "
            f"{row['old_song_count']}件: {', '.join(row['old_song_names'])} | "
            f"{row['new_song_count']}件: {', '.join(row['new_song_names'])} |"
        )
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
        args.site_events.write_text(
            json.dumps(proposed_events, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        write_performed = True

    result = {
        "generated_by": "sync_public_event_songs_to_site.py",
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
            "missing_site_key_count": len(missing_site_keys),
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
        "public event songs site sync: "
        f"mode={result['mode']} updated={result['summary']['updated_event_count']} "
        f"missing_site_keys={result['summary']['missing_site_key_count']} "
        f"write={result['write_performed']} out={args.out_json}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
