#!/usr/bin/env python3
"""Guard the site public events JSON so deploy data diffs are additive only."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
SITE_REPO = ROOT.parent / "bon-odori-site"
SITE_EVENTS_REL = Path("data/events_public.json")
OUT_JSON = ROOT / "data" / "site_public_event_additions_guard.json"
OUT_MD = ROOT / "data" / "site_public_event_additions_guard.md"


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def git_show_json(repo: Path, ref_path: str) -> list[dict[str, Any]]:
    data = subprocess.check_output(["git", "-C", str(repo), "show", ref_path])
    payload = json.loads(data.decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{ref_path} is not a JSON array")
    return payload


def event_key(event: dict[str, Any]) -> str:
    return "\u241f".join(
        [
            str(event.get("name") or ""),
            str(event.get("venue") or ""),
            str(event.get("date") or ""),
            str(event.get("date_end") or ""),
        ]
    )


def index_events(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for event in events:
        key = event_key(event)
        if key in indexed:
            duplicates.append(key)
        indexed[key] = event
    if duplicates:
        raise ValueError(f"duplicate event keys: {duplicates[:5]}")
    return indexed


def classify_addition_diff(base_events: list[dict[str, Any]], current_events: list[dict[str, Any]]) -> dict[str, Any]:
    base = index_events(base_events)
    current = index_events(current_events)
    base_keys = set(base)
    current_keys = set(current)
    added_keys = sorted(current_keys - base_keys)
    removed_keys = sorted(base_keys - current_keys)
    modified_keys = sorted(key for key in base_keys & current_keys if base[key] != current[key])
    return {
        "added": [current[key] for key in added_keys],
        "removed": [base[key] for key in removed_keys],
        "modified": [
            {
                "event_key": key,
                "before": base[key],
                "after": current[key],
            }
            for key in modified_keys
        ],
    }


def modified_fields(item: dict[str, Any]) -> list[str]:
    before = item.get("before") or {}
    after = item.get("after") or {}
    return sorted(field for field in set(before) | set(after) if before.get(field) != after.get(field))


def guard_decision(
    diff: dict[str, Any],
    expected_names: list[str],
    expected_removed_names: list[str] | None = None,
    allow_source_url_modifications: bool = False,
) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []
    added_names = [event.get("name") or "" for event in diff["added"]]
    removed_names = [event.get("name") or "" for event in diff["removed"]]
    expected_removed_names = expected_removed_names or []
    if diff["removed"]:
        if expected_removed_names:
            expected_removed_counter = Counter(expected_removed_names)
            removed_counter = Counter(removed_names)
            if removed_counter != expected_removed_counter:
                failures.append("removed_events_do_not_match_expected_names")
        else:
            failures.append("removed_existing_public_events")
    if diff["modified"] and (
        not allow_source_url_modifications
        or any(modified_fields(item) != ["source_urls"] for item in diff["modified"])
    ):
        failures.append("modified_existing_public_events")
    if expected_names:
        expected_counter = Counter(expected_names)
        added_counter = Counter(added_names)
        if added_counter != expected_counter:
            failures.append("added_events_do_not_match_expected_names")
    if not diff["added"]:
        warnings.append("no_public_event_additions_detected")
    status = "pass" if not failures else "block"
    return {
        "status": status,
        "failures": failures,
        "warnings": warnings,
        "safe_to_deploy_data_delta": status == "pass",
        "deploy_requires_operator_approval": True,
        "deploy_approval_note": "Addition guard pass only means the data diff is additive; deploy still requires explicit operator approval.",
    }


def render_markdown(result: dict[str, Any]) -> str:
    decision = result["decision"]
    summary = result["summary"]
    lines = [
        "# Site public event additions guard",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- status: {decision['status']}",
        f"- safe_to_deploy_data_delta: {decision['safe_to_deploy_data_delta']}",
        f"- deploy_requires_operator_approval: {decision['deploy_requires_operator_approval']}",
        f"- failures: {decision['failures']}",
        f"- warnings: {decision['warnings']}",
        f"- base: `{result['sources']['site_base_ref']}`",
        f"- current: `{result['sources']['site_events']}`",
        f"- added_count: {summary['added_count']}",
        f"- removed_count: {summary['removed_count']}",
        f"- modified_count: {summary['modified_count']}",
        "",
        "## Added Events",
        "",
        "| event | date | venue | area |",
        "| --- | --- | --- | --- |",
    ]
    for event in result["diff"]["added"]:
        lines.append(
            "| {name} | {date} | {venue} | {area} |".format(
                name=event.get("name") or "",
                date=event.get("date") or "",
                venue=event.get("venue") or "",
                area=event.get("area") or "",
            )
        )
    if result["diff"]["removed"]:
        lines.extend(["", "## Removed Events", ""])
        lines.extend(f"- {event.get('name') or ''} / {event.get('venue') or ''}" for event in result["diff"]["removed"])
    if result["diff"]["modified"]:
        lines.extend(["", "## Modified Existing Events", ""])
        lines.extend(f"- {item['before'].get('name') or ''} / {item['before'].get('venue') or ''}" for item in result["diff"]["modified"])
    lines.append("")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    base_ref_path = f"{args.base_ref}:{args.site_events_rel}"
    base_events = git_show_json(args.site_repo, base_ref_path)
    site_events_path = args.site_repo / args.site_events_rel
    current_events = load_json(site_events_path, [])
    if not isinstance(current_events, list):
        raise ValueError(f"{site_events_path} is not a JSON array")
    diff = classify_addition_diff(base_events, current_events)
    decision = guard_decision(
        diff,
        args.expected_event_name,
        args.expected_removed_event_name,
        args.allow_source_url_modifications,
    )
    result = {
        "generated_by": "guard_site_public_event_additions.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "site_repo": str(args.site_repo),
            "site_base_ref": base_ref_path,
            "site_events": str(site_events_path),
        },
        "parameters": {
            "expected_event_names": args.expected_event_name,
            "expected_removed_event_names": args.expected_removed_event_name,
            "allow_source_url_modifications": args.allow_source_url_modifications,
        },
        "decision": decision,
        "summary": {
            "base_count": len(base_events),
            "current_count": len(current_events),
            "added_count": len(diff["added"]),
            "removed_count": len(diff["removed"]),
            "modified_count": len(diff["modified"]),
        },
        "diff": diff,
    }
    write_json(args.out_json, result)
    args.out_md.write_text(render_markdown(result), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-repo", type=Path, default=SITE_REPO)
    parser.add_argument("--site-events-rel", type=Path, default=SITE_EVENTS_REL)
    parser.add_argument("--base-ref", default="HEAD")
    parser.add_argument("--expected-event-name", action="append", default=[])
    parser.add_argument("--expected-removed-event-name", action="append", default=[])
    parser.add_argument("--allow-source-url-modifications", action="store_true")
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    args = parser.parse_args()
    try:
        result = run(args)
    except ValueError as exc:
        parser.error(str(exc))
    decision = result["decision"]
    print(
        "site public event additions guard: "
        f"status={decision['status']} failures={decision['failures']} "
        f"added={result['summary']['added_count']} removed={result['summary']['removed_count']} "
        f"modified={result['summary']['modified_count']} out={args.out_json}"
    )
    return 0 if decision["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
