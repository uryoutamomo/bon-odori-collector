"""Compare legacy public state fields with the canonical two-axis projection."""

import argparse
import json
from collections import Counter
from pathlib import Path

from event_model.event_state_axes import (
    EventStateAxesError,
    axes_from_legacy_public_event,
    canonicalize_legacy_current_event_state,
    legacy_public_fields_from_axes,
    validate_event_state_axes,
)


DEFAULT_EVENTS = Path("data/public/events_public.json")


def event_identity(event):
    return "|".join(str(event.get(key) or "") for key in ("name", "venue", "date", "date_end"))


def compare_events(events, *, target_year=2026):
    rows = []
    pairs = Counter()
    for event in events:
        identity = event_identity(event)
        legacy_axes = axes_from_legacy_public_event(event, target_year=target_year)
        state = canonicalize_legacy_current_event_state(
            event.get("current_event_state") or legacy_axes["current_event_state"]
        )
        tier = event.get("date_certainty_tier") or legacy_axes["date_certainty_tier"]
        try:
            validate_event_state_axes(state, tier)
            projected = legacy_public_fields_from_axes(state, tier)
            errors = []
        except EventStateAxesError as exc:
            projected = {}
            errors = [str(exc)]

        expected = {
            "public_category": event.get("public_category"),
            "display_tier": event.get("display_tier"),
        }
        for key in ("public_category", "display_tier"):
            if projected.get(key) != expected[key]:
                errors.append(
                    f"{key}: expected={expected[key]!r} projected={projected.get(key)!r}"
                )
        if (state, tier) != (
            legacy_axes["current_event_state"],
            legacy_axes["date_certainty_tier"],
        ):
            errors.append(
                "axis mismatch: "
                f"stored={(state, tier)!r} legacy_derived={(legacy_axes['current_event_state'], legacy_axes['date_certainty_tier'])!r}"
            )
        pairs[(state, tier)] += 1
        rows.append(
            {
                "event_identity": identity,
                "name": event.get("name") or "",
                "current_event_state": state,
                "date_certainty_tier": tier,
                "expected_legacy": expected,
                "projected_legacy": projected,
                "errors": errors,
            }
        )

    mismatches = [row for row in rows if row["errors"]]
    return {
        "schema": "event_state_axes_shadow_compare_v1",
        "status": "pass" if not mismatches else "fail",
        "event_count": len(rows),
        "mismatch_count": len(mismatches),
        "axis_pair_counts": [
            {
                "current_event_state": state,
                "date_certainty_tier": tier,
                "count": count,
            }
            for (state, tier), count in sorted(pairs.items())
        ],
        "mismatches": mismatches,
    }


def render_markdown(report):
    lines = [
        "# Event state axes shadow comparison",
        "",
        f"- status: **{report['status']}**",
        f"- event_count: {report['event_count']}",
        f"- mismatch_count: {report['mismatch_count']}",
        "",
        "## Axis pairs",
        "",
        "| current_event_state | date_certainty_tier | count |",
        "| --- | --- | ---: |",
    ]
    for row in report["axis_pair_counts"]:
        lines.append(
            f"| {row['current_event_state']} | {row['date_certainty_tier']} | {row['count']} |"
        )
    if report["mismatches"]:
        lines.extend(["", "## Mismatches", ""])
        for row in report["mismatches"][:50]:
            lines.append(f"- `{row['event_identity']}`: {'; '.join(row['errors'])}")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--out-md", type=Path)
    parser.add_argument("--target-year", type=int, default=2026)
    args = parser.parse_args(argv)

    events = json.loads(args.events.read_text(encoding="utf-8"))
    report = compare_events(events, target_year=args.target_year)
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if args.out_md:
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "event_count", "mismatch_count")}, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
