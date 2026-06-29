"""Guard public events JSON before any wholesale sync or deploy.

This script is read-only. It compares collector and site public events, then
simulates the existing public post-processors to verify whether site-only
historical/season fields are regenerated before sync.
"""

import argparse
import copy
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from apply_public_display_tiers import apply_display_tiers
from apply_public_historical_references import (
    DEFAULT_TODAY,
    apply_historical_references,
    load_fixed_date_rules,
    parse_iso_date,
)
from apply_public_season_hints import apply_season_hints
from classify_public_events_diff import (
    HIGH_RISK_FIELDS,
    changed_fields,
    classify_diff,
    compact_value,
    event_key,
    field_family,
    index_events,
    recommended_event_action,
    value_side,
)


DATA = Path("data")
COLLECTOR_EVENTS = DATA / "public" / "events_public.json"
SITE_EVENTS = Path("/Users/ryotauchida/bon-odori-site/data/events_public.json")
FIXED_DATE_RULES = DATA / "public_fixed_date_rules.json"
OUT_JSON = DATA / "public_events_sync_guard.json"
OUT_MD = DATA / "public_events_sync_guard.md"


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


def classify_rows(collector_rows, site_rows):
    collector = index_events(collector_rows)
    site = index_events(site_rows)
    records = []
    for key in sorted(set(collector) & set(site)):
        left = collector[key]
        right = site[key]
        for field in changed_fields(left, right):
            if field not in HIGH_RISK_FIELDS:
                continue
            records.append(
                {
                    "event_key": key,
                    "event_name": left.get("name") or right.get("name") or "",
                    "venue": left.get("venue") or right.get("venue") or "",
                    "field": field,
                    "family": field_family(field),
                    "side": value_side(left.get(field), right.get(field)),
                    "recommended_action": classify_diff(field, left.get(field), right.get(field)),
                    "collector_value": compact_value(left.get(field)),
                    "site_value": compact_value(right.get(field)),
                }
            )

    event_actions = defaultdict(lambda: {"fields": [], "families": set(), "actions": Counter(), "records": []})
    for record in records:
        item = event_actions[record["event_key"]]
        item["fields"].append(record["field"])
        item["families"].add(record["family"])
        item["actions"][record["recommended_action"]] += 1
        item["records"].append(record)

    event_rows = []
    for key, item in event_actions.items():
        actions = item["actions"]
        action = recommended_event_action(actions, item["records"])
        sample = next(record for record in records if record["event_key"] == key)
        event_rows.append(
            {
                "event_key": key,
                "event_name": sample["event_name"],
                "venue": sample["venue"],
                "recommended_action": action,
                "families": sorted(item["families"]),
                "field_count": len(item["fields"]),
                "fields": sorted(item["fields"]),
                "actions": dict(actions),
            }
        )

    return {
        "summary": {
            "collector_event_count": len(collector_rows),
            "site_event_count": len(site_rows),
            "collector_only_count": len(set(collector) - set(site)),
            "site_only_count": len(set(site) - set(collector)),
            "high_risk_diff_record_count": len(records),
            "high_risk_event_count": len(event_rows),
            "records_by_family": dict(Counter(record["family"] for record in records)),
            "records_by_action": dict(Counter(record["recommended_action"] for record in records)),
            "events_by_action": dict(Counter(row["recommended_action"] for row in event_rows)),
        },
        "event_rows": sorted(
            event_rows,
            key=lambda row: (row["recommended_action"], row["event_name"], row["venue"]),
        ),
        "records": records,
    }


def apply_required_postprocessors(events, target_year, today, fixed_date_rules_path):
    processed = copy.deepcopy(events)
    processed = apply_historical_references(
        processed,
        target_year=target_year,
        today=today,
        fixed_date_rules=load_fixed_date_rules(fixed_date_rules_path),
    )["events"]
    processed = apply_display_tiers(processed)
    processed = apply_season_hints(processed, target_year=target_year)["events"]
    return apply_display_tiers(processed)


def guard_decision(raw, postprocessed, allow_individual_review):
    failures = []
    warnings = []
    post_summary = postprocessed["summary"]
    if post_summary["collector_event_count"] != post_summary["site_event_count"]:
        failures.append("event_count_mismatch")
    if post_summary["collector_only_count"] or post_summary["site_only_count"]:
        failures.append("event_key_mismatch")

    post_actions = post_summary.get("events_by_action") or {}
    restore_count = post_actions.get("restore_collector_from_site_or_reenable_export_postprocess", 0)
    individual_count = post_actions.get("individual_review", 0)
    site_update_count = post_actions.get("site_update_candidate_after_review", 0)
    if restore_count:
        failures.append("restore_candidates_remain_after_required_postprocessors")
    if individual_count and not allow_individual_review:
        failures.append("individual_review_diffs_remain")
    if site_update_count and not allow_individual_review:
        failures.append("site_update_candidates_remain")

    raw_actions = raw["summary"].get("events_by_action") or {}
    if raw_actions.get("restore_collector_from_site_or_reenable_export_postprocess", 0) and not restore_count:
        warnings.append("raw_restore_candidates_resolved_by_required_postprocessors")

    status = "pass" if not failures else "block"
    deploy_note = (
        "Guard pass only means no blocking public sync diffs remain. "
        "Public deploy still requires separate operator approval."
    )
    return {
        "status": status,
        "failures": failures,
        "warnings": warnings,
        "safe_to_wholesale_sync": status == "pass",
        "public_deploy_requires_separate_approval": True,
        "deploy_approval_note": deploy_note,
    }


def build(args):
    collector_events = load_json(args.collector_events, [])
    site_events = load_json(args.site_events, [])
    today = parse_iso_date(args.today)
    if not today:
        raise SystemExit(f"invalid --today: {args.today}")

    raw = classify_rows(collector_events, site_events)
    postprocessed_events = apply_required_postprocessors(
        collector_events,
        args.target_year,
        today,
        args.fixed_date_rules,
    )
    postprocessed = classify_rows(postprocessed_events, site_events)
    decision = guard_decision(raw, postprocessed, args.allow_individual_review)

    data = {
        "generated_by": "guard_public_events_sync.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "read_only_public_sync_guard_no_writes",
        "sources": {
            "collector_events": str(args.collector_events),
            "site_events": str(args.site_events),
            "fixed_date_rules": str(args.fixed_date_rules),
        },
        "parameters": {
            "target_year": args.target_year,
            "today": args.today,
            "allow_individual_review": bool(args.allow_individual_review),
        },
        "decision": decision,
        "raw_classification": raw["summary"],
        "postprocessed_classification": postprocessed["summary"],
        "blocking_examples": [
            row
            for row in postprocessed["event_rows"]
            if row["recommended_action"]
            in {
                "individual_review",
                "site_update_candidate_after_review",
                "restore_collector_from_site_or_reenable_export_postprocess",
            }
        ][:40],
    }
    write_json(args.out_json, data)
    Path(args.out_md).write_text(render_markdown(data), encoding="utf-8")
    return data


def render_markdown(data):
    lines = [
        "# Public events sync guard",
        "",
        "**Note**: This guard checks for blocking diffs only. Guard status `pass` means no blocking issues remain, but is NOT a deploy approval. Deploy decisions require explicit confirmation from the operator.",
        "",
        f"- generated_at: {data['generated_at']}",
        f"- scope: {data['scope']}",
        f"- status: {data['decision']['status']}",
        f"- safe_to_wholesale_sync: {data['decision']['safe_to_wholesale_sync']}",
        f"- public_deploy_requires_separate_approval: {data['decision']['public_deploy_requires_separate_approval']}",
        f"- deploy_approval_note: {data['decision']['deploy_approval_note']}",
        f"- failures: {data['decision']['failures']}",
        f"- warnings: {data['decision']['warnings']}",
        "",
        "## Raw Collector vs Site",
        "",
    ]
    for key, value in data["raw_classification"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## After Required Public Postprocessors", ""])
    for key, value in data["postprocessed_classification"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## Blocking Examples",
            "",
            "| action | event | venue | families | fields |",
            "| --- | --- | --- | --- | ---: |",
        ]
    )
    for row in data["blocking_examples"]:
        lines.append(
            f"| {row['recommended_action']} | {row['event_name']} | {row['venue']} | "
            f"{', '.join(row['families'])} | {row['field_count']} |"
        )
    lines.append("")
    return "\n".join(lines)


def append_github_summary(markdown_path, explicit_path=None):
    target = explicit_path or os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return None
    markdown_path = Path(markdown_path)
    if not markdown_path.exists():
        return None
    summary_path = Path(target)
    with summary_path.open("a", encoding="utf-8") as handle:
        handle.write("\n\n")
        handle.write(markdown_path.read_text(encoding="utf-8"))
        handle.write("\n")
    return str(summary_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--collector-events", default=str(COLLECTOR_EVENTS))
    parser.add_argument("--site-events", default=str(SITE_EVENTS))
    parser.add_argument("--fixed-date-rules", default=str(FIXED_DATE_RULES))
    parser.add_argument("--target-year", type=int, default=2026)
    parser.add_argument("--today", default=DEFAULT_TODAY.isoformat())
    parser.add_argument("--allow-individual-review", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    parser.add_argument("--append-github-summary", action="store_true")
    parser.add_argument("--github-summary")
    args = parser.parse_args()
    data = build(args)
    summary_path = None
    if args.append_github_summary or args.github_summary:
        summary_path = append_github_summary(args.out_md, args.github_summary)
    print(
        "public events sync guard: "
        f"status={data['decision']['status']} "
        f"failures={data['decision']['failures']} "
        f"postprocessed_actions={data['postprocessed_classification']['events_by_action']}"
    )
    if summary_path:
        print(f"github_summary={summary_path}")
    if data["decision"]["status"] != "pass" and not args.report_only:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
