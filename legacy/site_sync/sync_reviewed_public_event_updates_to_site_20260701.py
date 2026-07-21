"""Sync reviewed 2026 event additions/removals to the site data file.

This intentionally uses the current site working tree as the base so existing
reviewed local data changes are preserved. It does not deploy the site.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
COLLECTOR_EVENTS = ROOT / "data" / "public" / "events_public.json"
SITE_EVENTS = ROOT.parent / "bon-odori-site" / "data" / "events_public.json"
OUT_JSON = ROOT / "data" / "reviewed_public_event_site_updates_20260701.json"
OUT_MD = ROOT / "data" / "reviewed_public_event_site_updates_20260701.md"
CONFIRM = "SYNC REVIEWED PUBLIC EVENT UPDATES 20260701"

UPSERT_EVENT_NAMES = [
    "SHIBUYA MIYASHITA PARK BON DANCE",
    "盆踊 〜BONDO〜",
    "木場二丁目 盆踊り大会",
    "木場一・六町会 盆踊り大会",
    "東陽一丁目町会 盆踊り大会",
]

REMOVE_EVENT_NAMES = [
    "品川第二地区 区民まつり・品川青年会 盆踊り大会（天妙国寺）",
]


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


def selected_collector_events(events: list[dict[str, Any]], names: list[str]) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    selected: list[dict[str, Any]] = []
    missing: list[str] = []
    ambiguous: list[str] = []
    for name in names:
        matches = [event for event in events if event.get("name") == name]
        if not matches:
            missing.append(name)
        elif len(matches) > 1:
            ambiguous.append(name)
        else:
            selected.append(matches[0])
    return selected, missing, ambiguous


def build_site_events(
    site_events: list[dict[str, Any]],
    upserts: list[dict[str, Any]],
    remove_names: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    upsert_names = {event["name"] for event in upserts}
    remove_set = set(remove_names)
    removed = [
        event
        for event in site_events
        if event.get("name") in remove_set
    ]
    kept = [
        event
        for event in site_events
        if event.get("name") not in remove_set and event.get("name") not in upsert_names
    ]
    return [*kept, *upserts], removed


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Reviewed public event site updates 20260701",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- write_performed: {result['write_performed']}",
        f"- collector_events: `{result['sources']['collector_events']}`",
        f"- site_events: `{result['sources']['site_events']}`",
        f"- site_count_before: {result['summary']['site_count_before']}",
        f"- proposed_count: {result['summary']['proposed_count']}",
        f"- upsert_count: {result['summary']['upsert_count']}",
        f"- removed_count: {result['summary']['removed_count']}",
        f"- missing_count: {result['summary']['missing_count']}",
        f"- ambiguous_count: {result['summary']['ambiguous_count']}",
        "",
        "## Upserts",
        "",
        "| event | date | venue | area | source_urls |",
        "| --- | --- | --- | --- | ---: |",
    ]
    for event in result["upsert_events"]:
        lines.append(
            "| {name} | {date} | {venue} | {area} | {source_count} |".format(
                name=event.get("name") or "",
                date=event.get("date") or "",
                venue=event.get("venue") or "",
                area=event.get("area") or "",
                source_count=len(event.get("source_urls") or []),
            )
        )
    lines.extend(["", "## Removed", ""])
    if result["removed_events"]:
        for event in result["removed_events"]:
            lines.append(f"- {event.get('name') or ''} / {event.get('venue') or ''}")
    else:
        lines.append("- none")
    if result["missing_event_names"]:
        lines.extend(["", "## Missing", ""])
        lines.extend(f"- {name}" for name in result["missing_event_names"])
    if result["ambiguous_event_names"]:
        lines.extend(["", "## Ambiguous", ""])
        lines.extend(f"- {name}" for name in result["ambiguous_event_names"])
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

    upserts, missing, ambiguous = selected_collector_events(collector_events, args.upsert_event_name)
    proposed_events, removed = build_site_events(site_events, upserts, args.remove_event_name)
    write_performed = False
    if args.write and not missing and not ambiguous:
        args.site_events.write_text(json.dumps(proposed_events, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_performed = True

    result = {
        "generated_by": "sync_reviewed_public_event_updates_to_site_20260701.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "write" if args.write else "dry_run",
        "write_performed": write_performed,
        "sources": {
            "collector_events": str(args.collector_events),
            "site_events": str(args.site_events),
        },
        "summary": {
            "site_count_before": len(site_events),
            "proposed_count": len(proposed_events),
            "upsert_count": len(upserts),
            "removed_count": len(removed),
            "missing_count": len(missing),
            "ambiguous_count": len(ambiguous),
        },
        "upsert_event_names": args.upsert_event_name,
        "remove_event_names": args.remove_event_name,
        "missing_event_names": missing,
        "ambiguous_event_names": ambiguous,
        "upsert_event_keys": [event_key(event) for event in upserts],
        "upsert_events": upserts,
        "removed_events": removed,
    }
    write_json(args.out_json, result)
    args.out_md.write_text(render_markdown(result), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collector-events", type=Path, default=COLLECTOR_EVENTS)
    parser.add_argument("--site-events", type=Path, default=SITE_EVENTS)
    parser.add_argument("--upsert-event-name", action="append", default=UPSERT_EVENT_NAMES)
    parser.add_argument("--remove-event-name", action="append", default=REMOVE_EVENT_NAMES)
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
        "reviewed public event site updates 20260701: "
        f"mode={result['mode']} upsert={result['summary']['upsert_count']} "
        f"removed={result['summary']['removed_count']} missing={result['summary']['missing_count']} "
        f"ambiguous={result['summary']['ambiguous_count']} write={result['write_performed']}"
    )
    return 1 if result["missing_event_names"] or result["ambiguous_event_names"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
