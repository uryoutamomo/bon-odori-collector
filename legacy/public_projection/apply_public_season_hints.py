"""Attach low-confidence season hints to date_unknown public events."""

import argparse
import json
from pathlib import Path

from event_model.year_context import normalize_target_year
from export_public_events import write_public_js


DATA = Path("data")
PUBLIC_EVENTS = DATA / "public" / "events_public.json"
PUBLIC_EVENTS_JS = DATA / "public" / "events_public.js"
OUT_REPORT = DATA / "public_season_hint_dry_run.json"


SEASON_HINT_FIELDS = (
    "season_hint",
    "season_months",
    "season_jun",
    "season_hint_label",
    "season_confidence",
)


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def clear_season_hint_fields(event):
    for field in SEASON_HINT_FIELDS:
        event.pop(field, None)


def _month_label(month):
    return f"{month}月"


def build_label(months, jun):
    parts = []
    for month in months:
        label = _month_label(month)
        jun_label = jun.get(str(month))
        if jun_label:
            label += jun_label
        parts.append(label)
    return "・".join(parts) if parts else None


def public_season_hint(event, *, target_year):
    target_year = normalize_target_year(target_year)
    months = [
        int(month)
        for month in event.get("months") or []
        if isinstance(month, int) and 1 <= month <= 12
    ]
    jun = {
        str(month): label
        for month, label in (event.get("jun") or {}).items()
        if str(month).isdigit() and int(month) in months and label in {"上旬", "中旬", "下旬"}
    }
    hints = [
        hint
        for hint in event.get("hints") or []
        if (
            isinstance(hint, list)
            and len(hint) == 2
            and isinstance(hint[0], int)
            and isinstance(hint[1], int)
            and hint[0] in months
        )
    ]
    label = build_label(months, jun)
    if not months:
        return None
    return {
        "display_tier": "season_hint",
        "target_year": target_year,
        "months": months,
        "jun": jun,
        "hints": hints,
        "label": label,
        "confidence": "lowest",
        "basis": "例年の開催月・旬ヒント",
        "has_jun_hint": bool(jun),
        "has_sort_hint": bool(hints),
    }


def attach_season_hint_fields(event, hint):
    event["season_hint"] = hint
    event["season_months"] = hint["months"]
    event["season_jun"] = hint["jun"]
    event["season_hint_label"] = hint["label"]
    event["season_confidence"] = hint["confidence"]
    event["display_tier"] = "season_hint"


def apply_season_hints(events, *, target_year):
    target_year = normalize_target_year(target_year)
    applied = []
    skipped = []
    target_count = 0
    for event in events:
        if event.get("public_category") != "date_unknown":
            clear_season_hint_fields(event)
            continue
        target_count += 1
        hint = public_season_hint(event, target_year=target_year)
        before = {
            "season_hint": event.get("season_hint"),
            "season_months": event.get("season_months"),
            "season_hint_label": event.get("season_hint_label"),
        }
        if not hint:
            clear_season_hint_fields(event)
            skipped.append({
                "name": event.get("name"),
                "venue": event.get("venue"),
                "reason": "no_month_or_season_hint",
                "months": event.get("months") or [],
                "jun": event.get("jun") or {},
                "hints": event.get("hints") or [],
            })
            continue
        attach_season_hint_fields(event, hint)
        applied.append({
            "name": event.get("name"),
            "venue": event.get("venue"),
            "before": before,
            "after": {
                "season_months": event.get("season_months"),
                "season_jun": event.get("season_jun"),
                "season_hint_label": event.get("season_hint_label"),
                "season_confidence": event.get("season_confidence"),
            },
            "season_hint": hint,
        })
    return {
        "events": events,
        "report": {
            "generated_by": "apply_public_season_hints.py",
            "source": str(PUBLIC_EVENTS),
            "target_year": target_year,
            "target_category": "date_unknown",
            "target_count": target_count,
            "applied_count": len(applied),
            "skipped_count": len(skipped),
            "with_jun_hint_count": sum(1 for row in applied if row["season_hint"].get("has_jun_hint")),
            "with_sort_hint_count": sum(1 for row in applied if row["season_hint"].get("has_sort_hint")),
            "applied": applied,
            "skipped": skipped,
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-events", default=str(PUBLIC_EVENTS))
    parser.add_argument("--out-json", default=str(PUBLIC_EVENTS))
    parser.add_argument("--out-js", default=str(PUBLIC_EVENTS_JS))
    parser.add_argument("--report", default=str(OUT_REPORT))
    parser.add_argument("--target-year", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    events = load_json(args.public_events, [])
    result = apply_season_hints(events, target_year=args.target_year)
    from public_json_postprocessors.apply_public_display_tiers import apply_display_tiers

    result["events"] = apply_display_tiers(result["events"], target_year=args.target_year)
    result["report"]["dry_run"] = bool(args.dry_run)
    if not args.dry_run:
        write_json(args.out_json, result["events"])
        write_public_js(args.out_js, result["events"])
    write_json(args.report, result["report"])
    print(
        "public season hints: "
        f"applied={result['report']['applied_count']} "
        f"skipped={result['report']['skipped_count']}"
    )


if __name__ == "__main__":
    main()
