#!/usr/bin/env python3
"""Sync selected public event additions from collector JSON to the site repo.

Default mode is dry-run. Write mode rebuilds the site events_public.json from
the site HEAD version plus the selected collector events, so unrelated local
or collector-side changes are not copied by accident.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
COLLECTOR_EVENTS = ROOT / "data" / "public" / "events_public.json"
SITE_REPO = ROOT.parent / "bon-odori-site"
SITE_EVENTS_REL = Path("data/events_public.json")
OUT_JSON = ROOT / "data" / "public_event_site_additions_sync.json"
OUT_MD = ROOT / "data" / "public_event_site_additions_sync.md"
CONFIRM = "SYNC PUBLIC EVENT ADDITIONS"


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def git_show_json(repo: Path, ref_path: str) -> list[dict[str, Any]]:
    data = subprocess.check_output(["git", "-C", str(repo), "show", f"HEAD:{ref_path}"])
    payload = json.loads(data.decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"HEAD:{ref_path} is not a JSON array")
    return payload


def git_has_worktree_diff(repo: Path, path: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo), "diff", "--quiet", "--", str(path)],
        check=False,
    )
    return result.returncode == 1


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


def build_site_events(base_events: list[dict[str, Any]], additions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    addition_names = {event["name"] for event in additions}
    base_without_selected_names = [event for event in base_events if event.get("name") not in addition_names]
    return [*base_without_selected_names, *additions]


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Public event site additions sync",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- write_performed: {result['write_performed']}",
        f"- collector_events: `{result['sources']['collector_events']}`",
        f"- site_events: `{result['sources']['site_events']}`",
        f"- selected_count: {result['summary']['selected_count']}",
        f"- missing_count: {result['summary']['missing_count']}",
        f"- ambiguous_count: {result['summary']['ambiguous_count']}",
        f"- site_local_data_diff_before_sync: {result['summary']['site_local_data_diff_before_sync']}",
        "",
        "| event | date | venue | area | source_urls |",
        "| --- | --- | --- | --- | ---: |",
    ]
    for event in result["selected_events"]:
        lines.append(
            "| {name} | {date} | {venue} | {area} | {source_count} |".format(
                name=event.get("name") or "",
                date=event.get("date") or "",
                venue=event.get("venue") or "",
                area=event.get("area") or "",
                source_count=len(event.get("source_urls") or []),
            )
        )
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
    if not args.event_name:
        raise ValueError("at least one --event-name is required")

    collector_events = load_json(args.collector_events, [])
    if not isinstance(collector_events, list):
        raise ValueError(f"{args.collector_events} is not a JSON array")
    site_head_events = git_show_json(args.site_repo, str(args.site_events_rel))
    additions, missing, ambiguous = selected_collector_events(collector_events, args.event_name)
    proposed_events = build_site_events(site_head_events, additions)
    site_events_path = args.site_repo / args.site_events_rel
    local_diff_before = git_has_worktree_diff(args.site_repo, args.site_events_rel)

    write_performed = False
    if args.write and not missing and not ambiguous:
        site_events_path.write_text(
            json.dumps(proposed_events, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        write_performed = True

    result = {
        "generated_by": "sync_public_event_additions_to_site.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "write" if args.write else "dry_run",
        "write_performed": write_performed,
        "sources": {
            "collector_events": str(args.collector_events),
            "site_repo": str(args.site_repo),
            "site_events": str(site_events_path),
            "site_head_ref": f"HEAD:{args.site_events_rel}",
        },
        "summary": {
            "selected_count": len(additions),
            "missing_count": len(missing),
            "ambiguous_count": len(ambiguous),
            "site_head_count": len(site_head_events),
            "proposed_count": len(proposed_events),
            "site_local_data_diff_before_sync": local_diff_before,
        },
        "requested_event_names": args.event_name,
        "missing_event_names": missing,
        "ambiguous_event_names": ambiguous,
        "selected_event_keys": [event_key(event) for event in additions],
        "selected_events": additions,
    }
    write_json(args.out_json, result)
    args.out_md.write_text(render_markdown(result), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collector-events", type=Path, default=COLLECTOR_EVENTS)
    parser.add_argument("--site-repo", type=Path, default=SITE_REPO)
    parser.add_argument("--site-events-rel", type=Path, default=SITE_EVENTS_REL)
    parser.add_argument("--event-name", action="append", default=[])
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
        "public event site additions sync: "
        f"mode={result['mode']} selected={result['summary']['selected_count']} "
        f"missing={result['summary']['missing_count']} ambiguous={result['summary']['ambiguous_count']} "
        f"write={result['write_performed']} out={args.out_json}"
    )
    return 1 if result["missing_event_names"] or result["ambiguous_event_names"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
