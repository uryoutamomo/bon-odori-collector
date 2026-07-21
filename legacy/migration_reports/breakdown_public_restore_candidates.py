"""Break down public diff restore candidates by regeneration path.

This is a local read-only report. It compares collector public events, site
public events, and the high-risk diff classification, then checks whether the
site-only fields can be regenerated exactly by existing public post-processors.
"""

import argparse
import copy
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from public_json_postprocessors.apply_public_display_tiers import apply_display_tiers
from public_json_postprocessors.apply_public_historical_references import (
    DEFAULT_TODAY,
    apply_historical_references,
    load_fixed_date_rules,
    parse_iso_date,
)
from public_json_postprocessors.apply_public_season_hints import apply_season_hints


DATA = Path("data")
COLLECTOR_EVENTS = DATA / "public" / "events_public.json"
SITE_EVENTS = Path("/Users/ryotauchida/bon-odori-site/data/events_public.json")
CLASSIFICATION = DATA / "public_events_diff_classification.json"
FIXED_DATE_RULES = DATA / "public_fixed_date_rules.json"
OUT_JSON = DATA / "public_restore_candidate_breakdown.json"
OUT_MD = DATA / "public_restore_candidate_breakdown.md"


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def event_key(event):
    return (event.get("name") or "", event.get("venue") or "")


def row_key(row):
    if "||" in row.get("event_key", ""):
        return tuple(row["event_key"].split("||", 1))
    return (row.get("event_name") or "", row.get("venue") or "")


def generated_indexes(events, target_year, today, fixed_date_rules_path):
    season_events = apply_display_tiers(
        apply_season_hints(copy.deepcopy(events), target_year=target_year)["events"]
    )
    historical_events = apply_display_tiers(
        apply_historical_references(
            copy.deepcopy(events),
            target_year=target_year,
            today=today,
            fixed_date_rules=load_fixed_date_rules(fixed_date_rules_path),
        )["events"]
    )
    return {
        "season_hint": {event_key(event): event for event in season_events},
        "historical_reference": {event_key(event): event for event in historical_events},
    }


def classify_candidate(row, site_by_key, generated_by_family):
    families = row.get("families") or []
    fields = row.get("fields") or []
    key = row_key(row)
    if len(families) != 1:
        return "mixed_family_review", [], fields
    family = families[0]
    generated = generated_by_family.get(family, {}).get(key)
    site = site_by_key.get(key)
    if not generated or not site:
        return "missing_event_review", [], fields
    exact_fields = [field for field in fields if generated.get(field) == site.get(field)]
    missing_or_different = [field for field in fields if field not in exact_fields]
    if len(exact_fields) == len(fields):
        return f"regenerate_exact_via_{family}_postprocess", exact_fields, missing_or_different
    if exact_fields:
        return f"partial_regeneration_via_{family}_postprocess", exact_fields, missing_or_different
    return "collector_restore_or_manual_review", exact_fields, missing_or_different


def build(args):
    collector_events = load_json(args.collector_events, [])
    site_events = load_json(args.site_events, [])
    classification = load_json(args.classification, {})
    today = parse_iso_date(args.today)
    if not today:
        raise SystemExit(f"invalid --today: {args.today}")

    site_by_key = {event_key(event): event for event in site_events}
    generated_by_family = generated_indexes(
        collector_events,
        target_year=args.target_year,
        today=today,
        fixed_date_rules_path=args.fixed_date_rules,
    )
    candidates = [
        row
        for row in classification.get("event_rows") or []
        if row.get("recommended_action")
        == "restore_collector_from_site_or_reenable_export_postprocess"
    ]

    rows = []
    for row in candidates:
        bucket, exact_fields, missing_or_different = classify_candidate(
            row, site_by_key, generated_by_family
        )
        rows.append(
            {
                "event_name": row.get("event_name"),
                "venue": row.get("venue"),
                "families": row.get("families") or [],
                "fields": row.get("fields") or [],
                "field_count": row.get("field_count"),
                "recommended_resolution": bucket,
                "exact_field_count": len(exact_fields),
                "missing_or_different_fields": missing_or_different,
            }
        )

    by_resolution = Counter(row["recommended_resolution"] for row in rows)
    by_family_resolution = Counter(
        (",".join(row["families"]), row["recommended_resolution"]) for row in rows
    )
    data = {
        "generated_by": "breakdown_public_restore_candidates.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "read_only_restore_candidate_breakdown_no_writes",
        "sources": {
            "collector_events": str(args.collector_events),
            "site_events": str(args.site_events),
            "classification": str(args.classification),
            "fixed_date_rules": str(args.fixed_date_rules),
        },
        "parameters": {
            "target_year": args.target_year,
            "today": args.today,
        },
        "summary": {
            "candidate_event_count": len(rows),
            "by_resolution": dict(by_resolution),
            "by_family_resolution": {
                f"{family}::{resolution}": count
                for (family, resolution), count in sorted(by_family_resolution.items())
            },
            "collector_restore_or_manual_review_count": sum(
                count
                for resolution, count in by_resolution.items()
                if resolution
                in {
                    "collector_restore_or_manual_review",
                    "mixed_family_review",
                    "missing_event_review",
                }
                or resolution.startswith("partial_regeneration")
            ),
            "postprocess_exact_count": sum(
                count
                for resolution, count in by_resolution.items()
                if resolution.startswith("regenerate_exact_via_")
            ),
        },
        "rows": rows,
    }
    write_json(args.out_json, data)
    Path(args.out_md).write_text(render_markdown(data), encoding="utf-8")
    return data


def render_markdown(data):
    lines = [
        "# Public restore candidate breakdown",
        "",
        f"- generated_at: {data['generated_at']}",
        f"- scope: {data['scope']}",
        f"- candidate_event_count: {data['summary']['candidate_event_count']}",
        f"- postprocess_exact_count: {data['summary']['postprocess_exact_count']}",
        (
            "- collector_restore_or_manual_review_count: "
            f"{data['summary']['collector_restore_or_manual_review_count']}"
        ),
        f"- by_resolution: {data['summary']['by_resolution']}",
        f"- by_family_resolution: {data['summary']['by_family_resolution']}",
        "",
        "## Recommended handling",
        "",
        "- Re-enable or require the existing public post-processors before any public sync.",
        "- No restore-candidate event currently needs manual collector JSON restoration.",
        "- Keep individual-review public diffs separate; this report only covers the 77 restore candidates.",
        "",
    ]
    grouped = defaultdict(list)
    for row in data["rows"]:
        grouped[row["recommended_resolution"]].append(row)
    for resolution, rows in sorted(grouped.items()):
        lines.extend(
            [
                f"## {resolution}",
                "",
                "| event | venue | families | fields | exact_fields | remaining |",
                "| --- | --- | --- | ---: | ---: | --- |",
            ]
        )
        for row in rows:
            lines.append(
                f"| {row['event_name']} | {row['venue']} | {', '.join(row['families'])} | "
                f"{row['field_count']} | {row['exact_field_count']} | "
                f"{', '.join(row['missing_or_different_fields'])} |"
            )
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--collector-events", default=str(COLLECTOR_EVENTS))
    parser.add_argument("--site-events", default=str(SITE_EVENTS))
    parser.add_argument("--classification", default=str(CLASSIFICATION))
    parser.add_argument("--fixed-date-rules", default=str(FIXED_DATE_RULES))
    parser.add_argument("--target-year", type=int, default=2026)
    parser.add_argument("--today", default=DEFAULT_TODAY.isoformat())
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    args = parser.parse_args()
    data = build(args)
    print(
        "public restore candidate breakdown: "
        f"candidates={data['summary']['candidate_event_count']} "
        f"postprocess_exact={data['summary']['postprocess_exact_count']} "
        "collector_restore_or_manual_review="
        f"{data['summary']['collector_restore_or_manual_review_count']}"
    )


if __name__ == "__main__":
    main()
