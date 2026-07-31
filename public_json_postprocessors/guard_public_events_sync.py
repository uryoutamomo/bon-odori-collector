"""Guard public events JSON before any wholesale sync or deploy.

This script is read-only. It compares collector and site public events, then
simulates the existing public post-processors to verify whether site-only
historical/season fields are regenerated before sync.
"""

import argparse
import copy
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from public_json_postprocessors.apply_public_display_tiers import apply_display_tiers
from public_json_postprocessors.apply_public_historical_references import (
    apply_historical_references,
    load_fixed_date_rules,
    parse_iso_date,
)
from public_json_postprocessors.apply_public_season_hints import apply_season_hints
from public_json_postprocessors.classify_public_events_diff import (
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


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
COLLECTOR_EVENTS = DATA / "public" / "events_public.json"
SITE_EVENTS = Path("/Users/ryotauchida/bon-odori-site/data/events_public.json")
FIXED_DATE_RULES = DATA / "public_fixed_date_rules.json"
OUT_JSON = DATA / "public_events_sync_guard.json"
OUT_MD = DATA / "public_events_sync_guard.md"
MASTER_DB = DATA / "bon_odori_master.sqlite"
PUBLICATION_GAP_REVIEW = DATA / "publication_gap_review.json"
REVIEWED_APPROVALS = DATA / "public_sync_exact_approvals.json"
REVIEWED_APPROVALS_SCHEMA = "public_sync_exact_approvals_v1"


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


def canonical_event_sha256(event):
    payload = json.dumps(
        event,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def apply_reviewed_exact_approvals(collector_rows, site_rows, payload):
    """Apply value-pinned review approvals to a comparison-only site copy."""
    approved_site_rows = copy.deepcopy(site_rows)
    results = []
    seen_ids = set()

    schema = payload.get("schema") if isinstance(payload, dict) else None
    approvals = payload.get("approvals") if isinstance(payload, dict) else None
    if schema != REVIEWED_APPROVALS_SCHEMA or not isinstance(approvals, list):
        return {
            "site_rows": approved_site_rows,
            "summary": {
                "schema": schema,
                "status": "block",
                "approval_count": 0,
                "status_counts": {"invalid_manifest": 1},
                "failure_count": 1,
                "results": [
                    {
                        "id": "manifest",
                        "kind": "manifest",
                        "status": "invalid_manifest",
                    }
                ],
            },
        }

    collector = index_events(collector_rows)

    def site_positions():
        return {event_key(row): index for index, row in enumerate(approved_site_rows)}

    for approval in approvals:
        approval_id = str(approval.get("id") or "") if isinstance(approval, dict) else ""
        kind = approval.get("kind") if isinstance(approval, dict) else None
        result = {"id": approval_id, "kind": kind}
        if not approval_id or approval_id in seen_ids or kind not in {
            "same_key_update",
            "key_replacement",
            "removal",
            "addition",
        }:
            result["status"] = "invalid_approval"
            results.append(result)
            continue
        seen_ids.add(approval_id)

        positions = site_positions()
        if kind == "addition":
            # Approves an event that exists only on the collector side (newly
            # registered, e.g. from a poster/field report) being added to the
            # comparison-only site copy. Without this the guard blocks on
            # event_count_mismatch every time a new event is published, since
            # the other kinds can only update, rename, or drop existing rows.
            # Value-pinned like same_key_update: if the collector row changed
            # after review, this refuses rather than publishing something new
            # that nobody looked at.
            key = str(approval.get("event_key") or "")
            collector_event = collector.get(key)
            site_index = positions.get(key)
            result["event_key"] = key
            if collector_event is None:
                result["status"] = "inactive"
                results.append(result)
                continue
            collector_hash = canonical_event_sha256(collector_event)
            result["actual_collector_sha256"] = collector_hash
            if site_index is not None:
                site_hash = canonical_event_sha256(approved_site_rows[site_index])
                result["actual_site_sha256"] = site_hash
                result["status"] = (
                    "already_synced" if site_hash == collector_hash else "hash_mismatch"
                )
                results.append(result)
                continue
            if collector_hash == approval.get("collector_sha256"):
                approved_site_rows.append(copy.deepcopy(collector_event))
                result["status"] = "applied"
                results.append(result)
                continue
            result["status"] = "hash_mismatch"
            results.append(result)
            continue
        if kind == "removal":
            # Approves an event that exists only on the site side (collector
            # dropped it, e.g. a duplicate-suppression fix) being removed from
            # the comparison-only site copy. Value-pinned like same_key_update:
            # if the collector side has since resurrected the key, or the site
            # side no longer matches the approved snapshot, this refuses to
            # apply rather than silently drop something unexpected.
            key = str(approval.get("event_key") or "")
            collector_event = collector.get(key)
            site_index = positions.get(key)
            site_event = approved_site_rows[site_index] if site_index is not None else None
            result["event_key"] = key
            if collector_event is not None:
                result["status"] = "hash_mismatch"
                results.append(result)
                continue
            if site_event is None:
                result["status"] = "inactive"
                results.append(result)
                continue
            site_hash = canonical_event_sha256(site_event)
            result["actual_site_sha256"] = site_hash
            if site_hash == approval.get("site_sha256"):
                del approved_site_rows[site_index]
                result["status"] = "applied"
                results.append(result)
                continue
            result["status"] = "hash_mismatch"
            results.append(result)
            continue
        if kind == "same_key_update":
            key = str(approval.get("event_key") or "")
            collector_event = collector.get(key)
            site_index = positions.get(key)
            site_event = approved_site_rows[site_index] if site_index is not None else None
            result["event_key"] = key
            if collector_event is None and site_event is None:
                result["status"] = "inactive"
                results.append(result)
                continue
            if collector_event is not None and site_event is not None:
                collector_hash = canonical_event_sha256(collector_event)
                site_hash = canonical_event_sha256(site_event)
                result.update({"actual_site_sha256": site_hash, "actual_collector_sha256": collector_hash})
                if collector_hash == site_hash:
                    result["status"] = "already_synced"
                    results.append(result)
                    continue
                if (
                    site_hash == approval.get("site_sha256")
                    and collector_hash == approval.get("collector_sha256")
                ):
                    approved_site_rows[site_index] = copy.deepcopy(collector_event)
                    result["status"] = "applied"
                    results.append(result)
                    continue
            result["status"] = "hash_mismatch"
            results.append(result)
            continue

        site_key = str(approval.get("site_event_key") or "")
        collector_key = str(approval.get("collector_event_key") or "")
        collector_event = collector.get(collector_key)
        old_site_index = positions.get(site_key)
        new_site_index = positions.get(collector_key)
        old_site_event = approved_site_rows[old_site_index] if old_site_index is not None else None
        new_site_event = approved_site_rows[new_site_index] if new_site_index is not None else None
        result.update({"site_event_key": site_key, "collector_event_key": collector_key})
        if collector_event is None and old_site_event is None and new_site_event is None:
            result["status"] = "inactive"
            results.append(result)
            continue
        if collector_event is not None and old_site_event is None and new_site_event is not None:
            collector_hash = canonical_event_sha256(collector_event)
            new_site_hash = canonical_event_sha256(new_site_event)
            result.update(
                {"actual_site_sha256": new_site_hash, "actual_collector_sha256": collector_hash}
            )
            if collector_hash == new_site_hash:
                result["status"] = "already_synced"
                results.append(result)
                continue
        if collector_event is not None and old_site_event is not None and new_site_event is None:
            collector_hash = canonical_event_sha256(collector_event)
            old_site_hash = canonical_event_sha256(old_site_event)
            result.update(
                {"actual_site_sha256": old_site_hash, "actual_collector_sha256": collector_hash}
            )
            if (
                old_site_hash == approval.get("site_sha256")
                and collector_hash == approval.get("collector_sha256")
            ):
                approved_site_rows[old_site_index] = copy.deepcopy(collector_event)
                result["status"] = "applied"
                results.append(result)
                continue
        result["status"] = "hash_mismatch"
        results.append(result)

    status_counts = dict(Counter(result["status"] for result in results))
    failure_count = sum(
        count
        for status, count in status_counts.items()
        if status in {"invalid_approval", "hash_mismatch"}
    )
    return {
        "site_rows": approved_site_rows,
        "summary": {
            "schema": schema,
            "status": "pass" if failure_count == 0 else "block",
            "approval_count": len(approvals),
            "status_counts": status_counts,
            "failure_count": failure_count,
            "results": results,
        },
    }


def file_mtime(path):
    path = Path(path)
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def flow_artifact_warnings(master_db, publication_gap_review, collector_events):
    """Warn when the public-event flow appears to have skipped a review step."""
    warnings = []
    master_mtime = file_mtime(master_db)
    gap_mtime = file_mtime(publication_gap_review)
    collector_mtime = file_mtime(collector_events)

    if master_mtime is None:
        warnings.append("missing_master_rdb")
        return warnings
    if gap_mtime is None:
        warnings.append("missing_publication_gap_review")
    elif gap_mtime < master_mtime:
        warnings.append("master_rdb_newer_than_publication_gap_review")

    if collector_mtime is None:
        warnings.append("missing_collector_public_events")
    elif collector_mtime < master_mtime:
        warnings.append("master_rdb_newer_than_public_export")
    return warnings


def classify_rows(collector_rows, site_rows, today=None):
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
        action = recommended_event_action(actions, item["records"], collector[key], site[key], today)
        sample = next(record for record in records if record["event_key"] == key)
        end_date = collector[key].get("date_end") or collector[key].get("date")
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
                "ended_transition_end_date": end_date if action == "ended_transition_downgrade" else None,
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
    processed = apply_display_tiers(processed, target_year=target_year)
    processed = apply_season_hints(processed, target_year=target_year)["events"]
    return apply_display_tiers(processed, target_year=target_year)


def guard_decision(raw, postprocessed, allow_individual_review, approval_summary=None):
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
    if approval_summary and approval_summary.get("failure_count"):
        failures.append("reviewed_exact_approval_mismatch")

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

    raw = classify_rows(collector_events, site_events, today=today)
    postprocessed_events = apply_required_postprocessors(
        collector_events,
        args.target_year,
        today,
        args.fixed_date_rules,
    )
    postprocessed = classify_rows(postprocessed_events, site_events, today=today)
    reviewed_approvals_payload = load_json(args.reviewed_approvals, {})
    reviewed = apply_reviewed_exact_approvals(
        postprocessed_events,
        site_events,
        reviewed_approvals_payload,
    )
    approved = classify_rows(postprocessed_events, reviewed["site_rows"], today=today)
    decision = guard_decision(
        raw,
        approved,
        args.allow_individual_review,
        approval_summary=reviewed["summary"],
    )
    procedure_warnings = flow_artifact_warnings(
        args.master_db,
        args.publication_gap_review,
        args.collector_events,
    )
    decision["warnings"] = [*decision["warnings"], *procedure_warnings]

    data = {
        "generated_by": "guard_public_events_sync.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "read_only_public_sync_guard_no_writes",
        "sources": {
            "collector_events": str(args.collector_events),
            "site_events": str(args.site_events),
            "fixed_date_rules": str(args.fixed_date_rules),
            "master_db": str(args.master_db),
            "publication_gap_review": str(args.publication_gap_review),
            "reviewed_approvals": str(args.reviewed_approvals),
        },
        "parameters": {
            "target_year": args.target_year,
            "today": args.today,
            "allow_individual_review": bool(args.allow_individual_review),
        },
        "decision": decision,
        "procedure_warnings": procedure_warnings,
        "raw_classification": raw["summary"],
        "postprocessed_classification": postprocessed["summary"],
        "reviewed_exact_approvals": reviewed["summary"],
        "approved_classification": approved["summary"],
        "ended_transition_downgrades": [
            {
                "event_name": row["event_name"],
                "venue": row["venue"],
                "ended_on": row["ended_transition_end_date"],
            }
            for row in approved["event_rows"]
            if row["recommended_action"] == "ended_transition_downgrade"
        ],
        "blocking_examples": [
            row
            for row in approved["event_rows"]
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
        f"- procedure_warnings: {data['procedure_warnings']}",
        "",
        "## Procedure Warnings",
        "",
        "These warnings mean the public-event publication flow may have skipped a review step. They do not automatically approve or reject deploys; they should be resolved or consciously accepted before syncing/deploying.",
        "",
    ]
    if data["procedure_warnings"]:
        for warning in data["procedure_warnings"]:
            lines.append(f"- {warning}")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Raw Collector vs Site",
            "",
        ]
    )
    for key, value in data["raw_classification"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## After Required Public Postprocessors", ""])
    for key, value in data["postprocessed_classification"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Reviewed Exact Approvals", ""])
    approval_summary = data["reviewed_exact_approvals"]
    for key in ["schema", "status", "approval_count", "status_counts", "failure_count"]:
        lines.append(f"- {key}: {approval_summary.get(key)}")
    lines.extend(["", "## After Reviewed Exact Approvals", ""])
    for key, value in data["approved_classification"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Automatically Allowed Ended Transitions", ""])
    ended_transitions = data["ended_transition_downgrades"]
    lines.append(f"- count: {len(ended_transitions)}")
    if ended_transitions:
        lines.extend(["", "| event | venue | ended on |", "| --- | --- | --- |"])
        for row in ended_transitions:
            lines.append(f"| {row['event_name']} | {row['venue']} | {row['ended_on']} |")
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
    parser.add_argument("--master-db", default=str(MASTER_DB))
    parser.add_argument("--publication-gap-review", default=str(PUBLICATION_GAP_REVIEW))
    parser.add_argument("--reviewed-approvals", default=str(REVIEWED_APPROVALS))
    parser.add_argument("--target-year", type=int, required=True)
    parser.add_argument("--today", required=True)
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
        f"warnings={data['decision']['warnings']} "
        f"approved_actions={data['approved_classification']['events_by_action']}"
    )
    if summary_path:
        print(f"github_summary={summary_path}")
    if data["decision"]["status"] != "pass" and not args.report_only:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
