"""Clean schedule fragments from public event names.

By default this prints a dry-run plan. Pass --apply to write the cleaned JSON.
"""

import argparse
import json
from pathlib import Path

from export_public_events import apply_public_event_name_cleanup, clean_public_event_name, write_public_js
from operation_safety.manual_apply_guards import PUBLIC_JSON_ONE_OFF_CONFIRMATION, require_confirmation


ROOT = Path(__file__).resolve().parent
DEFAULT_PUBLIC = ROOT / "data/public/events_public.json"
DEFAULT_PUBLIC_JS = ROOT / "data/public/events_public.js"


def read_json(path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data):
    with Path(path).open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def build_plan(events):
    cleaned = apply_public_event_name_cleanup(events)
    changes = []
    for before, after in zip(events, cleaned):
        before_name = before.get("name") or ""
        after_name = after.get("name") or ""
        before_display = before.get("display_name") or ""
        after_display = after.get("display_name") or ""
        if before_name != after_name or before_display != after_display:
            changes.append({
                "area": after.get("area"),
                "venue": after.get("venue"),
                "public_category": after.get("public_category"),
                "before": before_name,
                "after": after_name,
                "display_name": after_display,
            })
    return cleaned, changes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--public", default=str(DEFAULT_PUBLIC))
    parser.add_argument("--public-js", default=str(DEFAULT_PUBLIC_JS))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        require_confirmation(
            args.apply,
            args.confirm,
            PUBLIC_JSON_ONE_OFF_CONFIRMATION,
            "public JSON event-name cleanup",
        )
    except ValueError as exc:
        parser.error(str(exc))

    public_path = Path(args.public)
    events = read_json(public_path)
    cleaned, changes = build_plan(events)
    bad_after = [
        event for event in cleaned
        if clean_public_event_name(event.get("name")) != (event.get("name") or "")
    ]

    summary = {
        "input": str(public_path),
        "events": len(events),
        "changes": len(changes),
        "remaining_name_schedule_fragments": len(bad_after),
        "applied": args.apply,
        "plan": changes,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.apply:
        write_json(public_path, cleaned)
        public_js_path = Path(args.public_js) if args.public_js else None
        if public_js_path:
            write_public_js(public_js_path, cleaned)


if __name__ == "__main__":
    main()
