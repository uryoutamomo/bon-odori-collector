"""Build a compact review packet for the Ph2 master RDB work.

This is a local report generator. It does not move, delete, commit, or apply
anything. The output is intended for koto/Claude review after a pause.
"""

import argparse
import json
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


DATA = Path("data")
APPLY_PLAN = DATA / "ph2_event_occurrence_apply_plan.json"
CUTOVER = DATA / "ph2_cutover_readiness.json"
PUBLIC_DIFF_CLASSIFICATION = DATA / "public_events_diff_classification.json"
PUBLIC_RESTORE_BREAKDOWN = DATA / "public_restore_candidate_breakdown.json"
PUBLIC_SYNC_GUARD = DATA / "public_events_sync_guard.json"
SONG_COLLAPSE_ANALYSIS = DATA / "song_occurrence_collapse_analysis.json"
PUBLIC_INDIVIDUAL_PRIORITY = DATA / "public_individual_review_priority.json"
OUT_JSON = DATA / "ph2_review_packet.json"
OUT_MD = DATA / "ph2_review_packet.md"

SCRIPT_REVIEW_FILES = {
    "master_db.py",
    "build_master_rdb.py",
    "audit_master_rdb.py",
    "export_master_rdb_song_occurrences.py",
    "build_observed_promotion_candidates.py",
    "build_historical_promotion_candidates.py",
    "build_registered_event_investigation_queue.py",
    "legacy/build-reports/build_pre_cutover_p0_apply_plan.py",
    "legacy/build-reports/build_ph2_cutover_readiness.py",
    "legacy/build-reports/build_ph2_event_occurrence_apply_plan.py",
    "legacy/build-reports/build_ph2_review_packet.py",
    "analyze_song_occurrence_collapse.py",
    "breakdown_public_restore_candidates.py",
    "classify_public_events_diff.py",
    "dry_run_ph2_event_occurrence_apply.py",
    "guard_public_events_sync.py",
    "prioritize_public_individual_review.py",
}


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


def git_status(repo):
    result = subprocess.run(
        ["git", "status", "--short", "--untracked-files=all"],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def classify_path(path):
    if path in SCRIPT_REVIEW_FILES:
        return "A_scripts_review"
    if path == "docs/master-rdb-migration-ph0-design.md":
        return "A_design_doc_review"
    if path in {
        "data/ph2_review_packet.json",
        "data/ph2_review_packet.md",
        "data/ph2_cutover_readiness.json",
        "data/ph2_cutover_readiness.md",
        "data/ph2_event_occurrence_apply_plan.json",
        "data/ph2_event_occurrence_apply_plan.md",
        "data/ph2_event_occurrence_apply_dry_run_report.json",
        "data/ph2_event_occurrence_apply_dry_run_report.md",
        "data/ph2_event_occurrence_apply_dry_run_audit.json",
        "data/ph2_event_occurrence_apply_dry_run_audit.md",
        "data/ph2_event_occurrence_apply_guard_test_report.json",
        "data/ph2_event_occurrence_apply_guard_test_report.md",
        "data/ph2_event_occurrence_apply_guard_test_audit.json",
        "data/ph2_event_occurrence_apply_guard_test_audit.md",
        "data/public_events_diff_classification.json",
        "data/public_events_diff_classification.md",
        "data/public_restore_candidate_breakdown.json",
        "data/public_restore_candidate_breakdown.md",
        "data/public_events_sync_guard.json",
        "data/public_events_sync_guard.md",
        "data/public_individual_review_priority.json",
        "data/public_individual_review_priority.md",
        "data/song_occurrence_collapse_analysis.json",
        "data/song_occurrence_collapse_analysis.md",
        "data/pre_cutover_p0_apply_plan.json",
        "data/pre_cutover_p0_apply_plan.md",
    }:
        return "B_ph2_review_reports"
    if path in {
        "data/registered_event_investigation_queue.json",
        "data/registered_event_investigation_queue.md",
        "data/observed_promotion_candidates.json",
        "data/observed_promotion_candidates.md",
        "data/historical_promotion_candidates.json",
        "data/historical_promotion_candidates.md",
        "data/pre_cutover_p0_research.md",
    }:
        return "C_review_queue_evidence"
    if path.startswith("data/bon_odori_master") or path.startswith("data/master_rdb"):
        return "D_generated_master_rdb_artifacts"
    if path.startswith("data/current_public_dry_run") or path.startswith("data/master_rdb_public_"):
        return "E_public_export_dry_run_artifacts"
    if path.startswith("data/public/"):
        return "F_public_output_modified_do_not_wholesale_deploy"
    if path in {
        "build_youtube_song_master.py",
        "data/youtube_song_master.json",
        "data/youtube_song_master_review.md",
    }:
        return "G_youtube_song_master_side_changes"
    if path == ".gitignore":
        return "H_repo_housekeeping"
    return "Z_other"


def worktree_review_buckets(repo):
    lines = git_status(repo)
    buckets = defaultdict(list)
    for line in lines:
        path = line[3:]
        buckets[classify_path(path)].append(line)
    return {
        "changed_file_count": len(lines),
        "bucket_counts": {key: len(value) for key, value in sorted(buckets.items())},
        "buckets": {key: value for key, value in sorted(buckets.items())},
        "recommended_review_order": [
            "A_scripts_review",
            "A_design_doc_review",
            "B_ph2_review_reports",
            "C_review_queue_evidence",
            "F_public_output_modified_do_not_wholesale_deploy",
            "G_youtube_song_master_side_changes",
            "D_generated_master_rdb_artifacts",
            "E_public_export_dry_run_artifacts",
            "H_repo_housekeeping",
        ],
    }


def classify_venue_decision(name, status, suggestions, current_venue="", mutation_type=""):
    top = suggestions[0] if suggestions else {}
    top_name = top.get("canonical_name") or ""
    top_score = float(top.get("match_score") or 0)
    if status == "exact_match":
        return "same_venue_confirmed"
    if top_score >= 0.9 and (top_name in name or name in top_name):
        return "alias_candidate"
    if mutation_type == "update_existing_2026_occurrence_from_current_official_source" and current_venue and name != current_venue:
        return "venue_change_review_required"
    if suggestions:
        return "possible_alias_review"
    return "new_or_missing_venue_review"


def venue_review_rows(apply_plan):
    output = []
    for mutation in apply_plan.get("mutations") or []:
        mutation_type = mutation.get("mutation_type")
        if mutation_type == "update_existing_2026_occurrence_from_current_official_source":
            proposed = mutation.get("proposed") or {}
            venue_name = proposed.get("venue_name") or ""
            if not venue_name:
                continue
            suggestions = proposed.get("venue_suggestions") or []
            current_venue = (mutation.get("target") or {}).get("venue_name") or ""
            decision = classify_venue_decision(
                venue_name,
                proposed.get("venue_lookup_status"),
                suggestions,
                current_venue=current_venue,
                mutation_type=mutation_type,
            )
            output.append(
                {
                    "event_name": mutation["event_name"],
                    "purpose": "current_2026_official_update",
                    "proposed_venue": venue_name,
                    "current_venue": current_venue,
                    "lookup_status": proposed.get("venue_lookup_status"),
                    "top_suggestion": suggestions[0] if suggestions else {},
                    "decision_bucket": decision,
                    "review_flags": (mutation.get("review") or {}).get("flags") or [],
                    "notes": (mutation.get("review") or {}).get("notes") or "",
                }
            )
        elif mutation_type == "append_historical_reference_without_confirming_2026":
            ref = mutation.get("historical_reference") or {}
            venue_name = ref.get("venue_name") or ""
            if not venue_name:
                continue
            suggestions = ref.get("venue_suggestions") or []
            decision = classify_venue_decision(
                venue_name,
                ref.get("venue_lookup_status"),
                suggestions,
                current_venue=(mutation.get("target") or {}).get("venue_name") or "",
                mutation_type=mutation_type,
            )
            output.append(
                {
                    "event_name": mutation["event_name"],
                    "purpose": "historical_reference_only",
                    "proposed_venue": venue_name,
                    "current_venue": (mutation.get("target") or {}).get("venue_name") or "",
                    "lookup_status": ref.get("venue_lookup_status"),
                    "top_suggestion": suggestions[0] if suggestions else {},
                    "decision_bucket": decision,
                    "review_flags": (mutation.get("review") or {}).get("flags") or [],
                    "notes": (mutation.get("review") or {}).get("notes") or "",
                }
            )
    output.sort(key=lambda row: (row["decision_bucket"], row["purpose"], row["event_name"]))
    return output


def public_diff_review(cutover):
    public = cutover.get("public_events_compare") or {}
    high = public.get("high_risk_diff_counts") or {}
    return {
        "event_counts_match": public.get("collector_event_count") == public.get("site_event_count"),
        "collector_only_count": public.get("collector_only_count"),
        "site_only_count": public.get("site_only_count"),
        "common_rows_with_diff": public.get("common_rows_with_diff"),
        "high_risk_diff_counts": high,
        "suggested_handling": {
            "historical_reference": "classify before any site wholesale sync",
            "historical_slide": "classify before any site wholesale sync",
            "season_hint": "classify before any site wholesale sync",
            "date_prediction": "review individually; only 2 examples currently",
            "detail": "review individually; only 2 examples currently",
        },
        "examples": public.get("examples") or {},
    }


def public_diff_classification_summary(classification):
    if not classification:
        return {
            "available": False,
            "summary": {},
            "field_level_site_update_candidates": [],
            "restore_examples": [],
            "individual_review_examples": [],
        }
    event_rows = classification.get("event_rows") or []
    records = classification.get("records") or []
    return {
        "available": True,
        "summary": classification.get("summary") or {},
        "field_level_site_update_candidates": [
            record
            for record in records
            if record.get("recommended_action") == "site_update_candidate_after_review"
        ][:20],
        "restore_examples": [
            row
            for row in event_rows
            if row.get("recommended_action")
            == "restore_collector_from_site_or_reenable_export_postprocess"
        ][:20],
        "individual_review_examples": [
            row for row in event_rows if row.get("recommended_action") == "individual_review"
        ][:20],
    }


def public_restore_breakdown_summary(breakdown):
    if not breakdown:
        return {
            "available": False,
            "summary": {},
            "examples": [],
        }
    rows = breakdown.get("rows") or []
    return {
        "available": True,
        "summary": breakdown.get("summary") or {},
        "examples": rows[:30],
    }


def public_sync_guard_summary(guard):
    if not guard:
        return {
            "available": False,
            "decision": {},
            "raw_classification": {},
            "postprocessed_classification": {},
            "blocking_examples": [],
        }
    return {
        "available": True,
        "decision": guard.get("decision") or {},
        "raw_classification": guard.get("raw_classification") or {},
        "postprocessed_classification": guard.get("postprocessed_classification") or {},
        "blocking_examples": (guard.get("blocking_examples") or [])[:20],
    }


def song_collapse_summary(analysis):
    if not analysis:
        return {
            "available": False,
            "summary": {},
            "rows": [],
        }
    return {
        "available": True,
        "summary": analysis.get("summary") or {},
        "rows": (analysis.get("rows") or [])[:10],
    }


def individual_priority_summary(priority):
    if not priority:
        return {
            "available": False,
            "summary": {},
            "top_rows": [],
        }
    rows = priority.get("rows") or []
    return {
        "available": True,
        "summary": priority.get("summary") or {},
        "top_rows": [row for row in rows if row.get("priority") in {"P0", "P1"}][:20],
    }


def build(args):
    apply_plan = load_json(args.apply_plan, {})
    cutover = load_json(args.cutover, {})
    public_diff_classification = load_json(args.public_diff_classification, {})
    public_restore_breakdown = load_json(args.public_restore_breakdown, {})
    public_sync_guard = load_json(args.public_sync_guard, {})
    song_collapse = load_json(args.song_collapse_analysis, {})
    public_individual_priority = load_json(args.public_individual_priority, {})
    venue_rows = venue_review_rows(apply_plan)
    restore_summary = public_restore_breakdown.get("summary") or {}
    guard_post_actions = (
        (public_sync_guard.get("postprocessed_classification") or {}).get("events_by_action")
        or {}
    )
    guard_status = (public_sync_guard.get("decision") or {}).get("status")
    guard_individual_count = guard_post_actions.get("individual_review", 0)
    priority_summary = public_individual_priority.get("summary") or {}
    data = {
        "generated_by": "build_ph2_review_packet.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "local_review_packet_no_writes",
        "sources": {
            "apply_plan": str(args.apply_plan),
            "cutover": str(args.cutover),
            "public_diff_classification": str(args.public_diff_classification),
            "public_restore_breakdown": str(args.public_restore_breakdown),
            "public_sync_guard": str(args.public_sync_guard),
            "song_collapse_analysis": str(args.song_collapse_analysis),
            "public_individual_priority": str(args.public_individual_priority),
        },
        "worktree": worktree_review_buckets(args.repo),
        "venue_review": {
            "row_count": len(venue_rows),
            "by_decision_bucket": dict(Counter(row["decision_bucket"] for row in venue_rows)),
            "rows": venue_rows,
        },
        "public_diff_review": public_diff_review(cutover),
        "public_diff_classification": public_diff_classification_summary(public_diff_classification),
        "public_restore_breakdown": public_restore_breakdown_summary(public_restore_breakdown),
        "public_sync_guard": public_sync_guard_summary(public_sync_guard),
        "song_collapse_analysis": song_collapse_summary(song_collapse),
        "public_individual_priority": individual_priority_summary(public_individual_priority),
        "koto_review_request": {
            "reviewer": "こと（Claude Code）",
            "from": "おと（Codex）",
            "request": [
                "Review scripts in A_scripts_review, especially dry_run_ph2_event_occurrence_apply.py safety gates.",
                "Review whether venue_review alias candidates can be accepted or need separate venue records.",
                "Review that only 品川区民まつり 荏原第一地区 is ready for actual DB apply before broader Ph2.",
                "Use public_diff_classification before any events_public.json sync decision.",
                (
                    "Use public_restore_candidate_breakdown: "
                    f"{restore_summary.get('postprocess_exact_count')} restore candidates regenerate exactly "
                    "via existing public post-processors."
                ),
                (
                    "Use public_events_sync_guard.py as a blocking pre-sync check; "
                    + (
                        f"current status passes with {guard_individual_count} postprocessed individual-review diffs."
                        if guard_status == "pass"
                        else f"current status blocks because {guard_individual_count} postprocessed individual-review diffs remain."
                    )
                ),
                "Treat the 2 missing public song rows as intentional duplicate collapse unless reviewer disagrees.",
                (
                    "Review public_individual_review_priority first: "
                    f"P0/P1 is {priority_summary.get('p0_p1_event_count')} raw-diff events; "
                    "use public_sync_guard blocking examples for the smaller postprocessed set."
                ),
                "For public diffs: keep raw individual-review rows separate from postprocess-regenerated restore candidates.",
            ],
            "do_not_do_without_uchida_go": [
                "write to Notion",
                "apply to data/bon_odori_master.sqlite",
                "deploy public site",
                "unfreeze legacy song occurrence generation",
            ],
        },
    }
    write_json(args.out_json, data)
    Path(args.out_md).write_text(render_markdown(data), encoding="utf-8")
    return data


def render_markdown(data):
    lines = [
        "# Ph2 review packet",
        "",
        f"- generated_at: {data['generated_at']}",
        f"- scope: {data['scope']}",
        "",
        "## Review Order",
        "",
    ]
    worktree = data["worktree"]
    lines.append(f"- changed_file_count: {worktree['changed_file_count']}")
    lines.append(f"- bucket_counts: {worktree['bucket_counts']}")
    for bucket in worktree["recommended_review_order"]:
        if bucket not in worktree["buckets"]:
            continue
        lines.extend(["", f"### {bucket}", ""])
        for item in worktree["buckets"][bucket][:80]:
            lines.append(f"- `{item}`")

    venue = data["venue_review"]
    lines.extend(
        [
            "",
            "## Venue Review",
            "",
            f"- row_count: {venue['row_count']}",
            f"- by_decision_bucket: {venue['by_decision_bucket']}",
            "",
            "| decision | event | purpose | proposed | current | suggestion | flags |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in venue["rows"]:
        suggestion = row["top_suggestion"].get("canonical_name") or ""
        if suggestion:
            suggestion = f"{suggestion} ({row['top_suggestion'].get('match_score')})"
        lines.append(
            f"| {row['decision_bucket']} | {row['event_name']} | {row['purpose']} | "
            f"{row['proposed_venue']} | {row['current_venue']} | {suggestion} | {', '.join(row['review_flags'])} |"
        )

    public = data["public_diff_review"]
    lines.extend(
        [
            "",
            "## Public Diff Review",
            "",
            f"- event_counts_match: {public['event_counts_match']}",
            f"- collector_only_count: {public['collector_only_count']}",
            f"- site_only_count: {public['site_only_count']}",
            f"- common_rows_with_diff: {public['common_rows_with_diff']}",
            f"- high_risk_diff_counts: {public['high_risk_diff_counts']}",
            "",
            "Suggested handling:",
        ]
    )
    for key, value in public["suggested_handling"].items():
        lines.append(f"- {key}: {value}")

    classified = data["public_diff_classification"]
    lines.extend(["", "## Classified Public Diff Actions", ""])
    if not classified["available"]:
        lines.append("- classification: missing")
    else:
        summary = classified["summary"]
        lines.extend(
            [
                f"- high_risk_event_count: {summary.get('high_risk_event_count')}",
                f"- high_risk_diff_record_count: {summary.get('high_risk_diff_record_count')}",
                f"- records_by_family: {summary.get('records_by_family')}",
                f"- records_by_action: {summary.get('records_by_action')}",
                f"- events_by_action: {summary.get('events_by_action')}",
                "",
                "### Field-Level Site Update Candidates",
                "",
                "| event | venue | field |",
                "| --- | --- | --- |",
            ]
        )
        for row in classified["field_level_site_update_candidates"]:
            lines.append(f"| {row['event_name']} | {row['venue']} | {row['field']} |")
        if not classified["field_level_site_update_candidates"]:
            lines.append("| none |  |  |")

        lines.extend(
            [
                "",
                "### Restore or Export Postprocess Examples",
                "",
                "| event | venue | families | fields |",
                "| --- | --- | --- | ---: |",
            ]
        )
        for row in classified["restore_examples"]:
            lines.append(
                f"| {row['event_name']} | {row['venue']} | "
                f"{', '.join(row['families'])} | {row['field_count']} |"
            )

        lines.extend(
            [
                "",
                "### Individual Review Examples",
                "",
                "| event | venue | families | fields |",
                "| --- | --- | --- | ---: |",
            ]
        )
        for row in classified["individual_review_examples"]:
            lines.append(
                f"| {row['event_name']} | {row['venue']} | "
                f"{', '.join(row['families'])} | {row['field_count']} |"
            )

    restore = data["public_restore_breakdown"]
    lines.extend(["", "## Public Restore Candidate Breakdown", ""])
    if not restore["available"]:
        lines.append("- restore_breakdown: missing")
    else:
        summary = restore["summary"]
        lines.extend(
            [
                f"- candidate_event_count: {summary.get('candidate_event_count')}",
                f"- postprocess_exact_count: {summary.get('postprocess_exact_count')}",
                (
                    "- collector_restore_or_manual_review_count: "
                    f"{summary.get('collector_restore_or_manual_review_count')}"
                ),
                f"- by_resolution: {summary.get('by_resolution')}",
                "",
                "| event | venue | resolution | fields |",
                "| --- | --- | --- | ---: |",
            ]
        )
        for row in restore["examples"]:
            lines.append(
                f"| {row['event_name']} | {row['venue']} | "
                f"{row['recommended_resolution']} | {row['field_count']} |"
            )

    guard = data["public_sync_guard"]
    lines.extend(["", "## Public Sync Guard", ""])
    if not guard["available"]:
        lines.append("- sync_guard: missing")
    else:
        decision = guard["decision"]
        post = guard["postprocessed_classification"]
        lines.extend(
            [
                f"- status: {decision.get('status')}",
                f"- safe_to_wholesale_sync: {decision.get('safe_to_wholesale_sync')}",
                f"- failures: {decision.get('failures')}",
                f"- warnings: {decision.get('warnings')}",
                f"- postprocessed_events_by_action: {post.get('events_by_action')}",
                "",
                "| action | event | venue | families | fields |",
                "| --- | --- | --- | --- | ---: |",
            ]
        )
        for row in guard["blocking_examples"]:
            lines.append(
                f"| {row['recommended_action']} | {row['event_name']} | {row['venue']} | "
                f"{', '.join(row['families'])} | {row['field_count']} |"
            )

    collapse = data["song_collapse_analysis"]
    lines.extend(["", "## Song Occurrence Collapse Analysis", ""])
    if not collapse["available"]:
        lines.append("- song_collapse_analysis: missing")
    else:
        summary = collapse["summary"]
        lines.extend(
            [
                f"- intentional_duplicate_collapse_count: {summary.get('intentional_duplicate_collapse_count')}",
                f"- review_required_count: {summary.get('review_required_count')}",
                f"- missing_public_song_row_count: {summary.get('missing_public_song_row_count')}",
                "",
                "| decision | event | venue | role | source_titles | exported_titles |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for row in collapse["rows"]:
            lines.append(
                f"| {row['decision']} | {row['event_name']} | {row['venue']} | {row['role']} | "
                f"{', '.join(row['source_titles'])} | {', '.join(row['exported_titles'])} |"
            )

    priority = data["public_individual_priority"]
    lines.extend(["", "## Public Individual Review Priority", ""])
    if not priority["available"]:
        lines.append("- public_individual_priority: missing")
    else:
        summary = priority["summary"]
        lines.extend(
            [
                f"- individual_review_event_count: {summary.get('individual_review_event_count')}",
                f"- p0_p1_event_count: {summary.get('p0_p1_event_count')}",
                f"- by_priority: {summary.get('by_priority')}",
                "",
                "| priority | bucket | event | venue | review_fields |",
                "| --- | --- | --- | --- | ---: |",
            ]
        )
        for row in priority["top_rows"]:
            lines.append(
                f"| {row['priority']} | {row['bucket']} | {row['event_name']} | "
                f"{row['venue']} | {row['review_field_count']} |"
            )

    request = data["koto_review_request"]
    lines.extend(["", "## Koto Review Request", ""])
    lines.append(f"From: {request['from']}")
    lines.append(f"To: {request['reviewer']}")
    lines.extend(["", "Please review:", ""])
    for item in request["request"]:
        lines.append(f"- {item}")
    lines.extend(["", "Do not do without Uchida GO:", ""])
    for item in request["do_not_do_without_uchida_go"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    parser.add_argument("--apply-plan", default=str(APPLY_PLAN))
    parser.add_argument("--cutover", default=str(CUTOVER))
    parser.add_argument("--public-diff-classification", default=str(PUBLIC_DIFF_CLASSIFICATION))
    parser.add_argument("--public-restore-breakdown", default=str(PUBLIC_RESTORE_BREAKDOWN))
    parser.add_argument("--public-sync-guard", default=str(PUBLIC_SYNC_GUARD))
    parser.add_argument("--song-collapse-analysis", default=str(SONG_COLLAPSE_ANALYSIS))
    parser.add_argument("--public-individual-priority", default=str(PUBLIC_INDIVIDUAL_PRIORITY))
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    args = parser.parse_args()
    data = build(args)
    print(
        "ph2 review packet: "
        f"files={data['worktree']['changed_file_count']} "
        f"venue_rows={data['venue_review']['row_count']} "
        f"venue_buckets={data['venue_review']['by_decision_bucket']}"
    )


if __name__ == "__main__":
    main()
