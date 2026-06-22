"""Build a local Ph2 cutover readiness report.

This is a read-only helper. It inspects the master SQLite dry-run DB and the
collector/site public JSON outputs, then emits review material for the next
event_series/event_occurrences migration step.
"""

import argparse
import json
import sqlite3
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from master_db import MASTER_DB


DATA = Path("data")
COLLECTOR_EVENTS = DATA / "public" / "events_public.json"
SITE_EVENTS = Path("/Users/ryotauchida/bon-odori-site/data/events_public.json")
OUT_JSON = DATA / "ph2_cutover_readiness.json"
OUT_MD = DATA / "ph2_cutover_readiness.md"

HIGH_RISK_PUBLIC_FIELDS = {
    "name",
    "venue",
    "area",
    "address",
    "lat",
    "lng",
    "date",
    "date_end",
    "status",
    "date_confidence",
    "date_prediction",
    "historical_reference",
    "historical_slide",
    "season_hint",
    "source_urls",
    "songs",
    "description",
    "detail",
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


def rows(db_path, query, params=()):
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(query, params)]


def one(db_path, query, params=()):
    with sqlite3.connect(db_path) as conn:
        return conn.execute(query, params).fetchone()[0]


def public_key(row):
    return f"{row.get('name') or ''}||{row.get('venue') or ''}"


def index_public(rows_):
    return {public_key(row): row for row in rows_}


def compare_public_events(collector_path, site_path):
    collector = load_json(collector_path, [])
    site = load_json(site_path, [])
    collector_by_key = index_public(collector)
    site_by_key = index_public(site)
    collector_keys = set(collector_by_key)
    site_keys = set(site_by_key)
    common = sorted(collector_keys & site_keys)

    field_diff_counts = Counter()
    high_risk_diff_counts = Counter()
    examples = defaultdict(list)
    rows_with_diff = 0
    for key in common:
        left = collector_by_key[key]
        right = site_by_key[key]
        diff_fields = sorted(set(left) | set(right))
        row_changed = False
        for field in diff_fields:
            if left.get(field) == right.get(field):
                continue
            row_changed = True
            field_diff_counts[field] += 1
            if field in HIGH_RISK_PUBLIC_FIELDS:
                high_risk_diff_counts[field] += 1
            if len(examples[field]) < 5:
                examples[field].append(
                    {
                        "event_key": key,
                        "collector": left.get(field),
                        "site": right.get(field),
                    }
                )
        if row_changed:
            rows_with_diff += 1

    return {
        "collector_path": str(collector_path),
        "site_path": str(site_path),
        "collector_event_count": len(collector),
        "site_event_count": len(site),
        "collector_only_count": len(collector_keys - site_keys),
        "site_only_count": len(site_keys - collector_keys),
        "common_event_count": len(common),
        "common_rows_with_diff": rows_with_diff,
        "collector_only": sorted(collector_keys - site_keys)[:40],
        "site_only": sorted(site_keys - collector_keys)[:40],
        "field_diff_counts": dict(field_diff_counts.most_common()),
        "high_risk_diff_counts": dict(high_risk_diff_counts.most_common()),
        "examples": dict(examples),
    }


def master_db_summary(db_path):
    if not Path(db_path).exists():
        return {"missing": True}
    counts = {
        "event_series": one(db_path, "SELECT COUNT(*) FROM event_series"),
        "event_occurrences": one(db_path, "SELECT COUNT(*) FROM event_occurrences"),
        "occurrence_dates": one(db_path, "SELECT COUNT(*) FROM occurrence_dates"),
        "predicted_occurrence_dates": one(db_path, "SELECT COUNT(*) FROM predicted_occurrence_dates"),
        "historical_promotion_candidates": one(db_path, "SELECT COUNT(*) FROM historical_promotion_candidates"),
        "event_investigation_tasks": one(db_path, "SELECT COUNT(*) FROM event_investigation_tasks"),
    }
    by_year = Counter(
        row["event_year"]
        for row in rows(db_path, "SELECT event_year FROM event_occurrences")
    )
    by_status = Counter(
        row["date_status"]
        for row in rows(db_path, "SELECT date_status FROM event_occurrences")
    )
    by_lifecycle = Counter(
        row["lifecycle_status"]
        for row in rows(db_path, "SELECT lifecycle_status FROM event_occurrences")
    )
    missing = {
        "date_start": one(db_path, "SELECT COUNT(*) FROM event_occurrences WHERE COALESCE(date_start, '') = ''"),
        "venue_id": one(db_path, "SELECT COUNT(*) FROM event_occurrences WHERE venue_id IS NULL"),
        "source_url": one(db_path, "SELECT COUNT(*) FROM event_occurrences WHERE COALESCE(source_url, '') = ''"),
    }
    duplicate_series_names = rows(
        db_path,
        """
        SELECT normalized_name, COUNT(*) AS c
        FROM event_series
        GROUP BY normalized_name
        HAVING c > 1
        ORDER BY c DESC, normalized_name
        LIMIT 30
        """,
    )
    split_risks = rows(
        db_path,
        """
        SELECT event_name, known_venue_names_json, priority_label, priority_score, recommended_action
        FROM event_investigation_tasks
        WHERE json_array_length(known_venue_names_json) > 1
           OR recommended_action LIKE '%split%'
        ORDER BY priority_label, priority_score DESC, event_name
        LIMIT 30
        """,
    )
    prediction_status = Counter(
        row["application_status"]
        for row in rows(db_path, "SELECT application_status FROM predicted_occurrence_dates")
    )
    prediction_basis = Counter(
        row["basis_type"]
        for row in rows(db_path, "SELECT basis_type FROM predicted_occurrence_dates")
    )
    dry_run_sync_jobs = Counter(
        row["status"]
        for row in rows(
            db_path,
            """
            SELECT status
            FROM notion_sync_jobs
            WHERE direction = 'rdb_to_notion_dry_run'
            """,
        )
    )
    return {
        "missing": False,
        "path": str(db_path),
        "counts": counts,
        "occurrences_by_year": dict(sorted(by_year.items())),
        "occurrences_by_date_status": dict(by_status),
        "occurrences_by_lifecycle_status": dict(by_lifecycle),
        "missing_core_fields": missing,
        "duplicate_series_name_examples": duplicate_series_names,
        "occurrence_split_risk_examples": split_risks,
        "predicted_dates_by_application_status": dict(prediction_status),
        "predicted_dates_by_basis_type": dict(prediction_basis),
        "dry_run_sync_jobs_by_status": dict(dry_run_sync_jobs),
    }


def git_status_summary(repo):
    result = subprocess.run(
        ["git", "status", "--short", "--untracked-files=all"],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    groups = Counter()
    files_by_group = defaultdict(list)
    for line in lines:
        path = line[3:]
        if path in {
            "master_db.py",
            "build_master_rdb.py",
            "audit_master_rdb.py",
            "export_master_rdb_song_occurrences.py",
            "build_observed_promotion_candidates.py",
            "build_historical_promotion_candidates.py",
            "build_registered_event_investigation_queue.py",
            "build_ph2_cutover_readiness.py",
            "build_ph2_event_occurrence_apply_plan.py",
            "build_predicted_occurrence_research_queue.py",
            "build_pre_cutover_p0_apply_plan.py",
        }:
            group = "review_commit_candidate_scripts"
        elif path == "docs/master-rdb-migration-ph0-design.md":
            group = "review_commit_candidate_docs"
        elif path.startswith("data/master_rdb") or path.startswith("data/bon_odori_master"):
            group = "master_rdb_generated_artifacts"
        elif path.startswith("data/current_public_dry_run") or path.startswith("data/master_rdb_public_"):
            group = "public_export_dry_run_artifacts"
        elif (
            path.startswith("data/ph2_cutover_readiness")
            or path.startswith("data/ph2_event_occurrence_apply_plan")
            or path.startswith("data/predicted_occurrence_research_queue")
            or path.startswith("data/pre_cutover_p0_apply_plan")
        ):
            group = "new_review_reports"
        elif path in {
            "data/historical_promotion_candidates.json",
            "data/historical_promotion_candidates.md",
            "data/observed_promotion_candidates.json",
            "data/observed_promotion_candidates.md",
            "data/pre_cutover_p0_research.md",
            "data/registered_event_investigation_queue.json",
            "data/registered_event_investigation_queue.md",
        }:
            group = "review_queue_reports"
        elif path.startswith("data/public/"):
            group = "public_output_modified"
        elif path in {
            "build_youtube_song_master.py",
            "data/youtube_song_master.json",
            "data/youtube_song_master_review.md",
        }:
            group = "youtube_song_master_side_changes"
        elif path == ".gitignore":
            group = "repo_housekeeping"
        else:
            group = "other"
        groups[group] += 1
        files_by_group[group].append(line)
    return {
        "changed_file_count": len(lines),
        "groups": dict(groups),
        "files_by_group": dict(files_by_group),
        "files": lines,
    }


def build(args):
    repo = Path(args.repo)
    data = {
        "generated_by": "build_ph2_cutover_readiness.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "read_only_local_review_material",
        "master_db": master_db_summary(args.master_db),
        "public_events_compare": compare_public_events(args.collector_events, args.site_events),
        "git_status": git_status_summary(repo),
        "recommended_next_actions": [
            "Keep data/song_occurrences.json and prediction snapshots frozen until Ph2/Ph3 explicitly reopens the legacy path.",
            "Do not copy collector data/public/events_public.json wholesale to bon-odori-site until high-risk field diffs are classified.",
            "Use predicted_occurrence_dates and event_investigation_tasks as review queues, not as automatic public updates.",
            "Process data/predicted_occurrence_research_queue.md from P0 downward; only promote predictions after current-year source confirmation.",
            "Proceed with Ph2 dry-run against event_series/event_occurrences before any large Notion or public JSON write.",
        ],
    }
    write_json(args.out_json, data)
    Path(args.out_md).write_text(render_markdown(data), encoding="utf-8")
    return data


def render_markdown(data):
    db = data["master_db"]
    public = data["public_events_compare"]
    git_status = data["git_status"]
    lines = [
        "# Ph2 cutover readiness",
        "",
        f"- generated_at: {data['generated_at']}",
        f"- scope: {data['scope']}",
        "",
        "## Master DB",
        "",
    ]
    if db.get("missing"):
        lines.append("- master DB missing")
    else:
        for key, value in db["counts"].items():
            lines.append(f"- {key}: {value}")
        lines.extend(
            [
                f"- occurrences_by_year: {db['occurrences_by_year']}",
                f"- occurrences_by_date_status: {db['occurrences_by_date_status']}",
                f"- missing_core_fields: {db['missing_core_fields']}",
                f"- predicted_dates_by_application_status: {db['predicted_dates_by_application_status']}",
                f"- dry_run_sync_jobs_by_status: {db['dry_run_sync_jobs_by_status']}",
                "",
                "### Duplicate Series Name Examples",
                "",
            ]
        )
        for row in db["duplicate_series_name_examples"][:20]:
            lines.append(f"- {row['normalized_name']}: {row['c']}")
        lines.extend(["", "### Occurrence Split Risk Examples", ""])
        for row in db["occurrence_split_risk_examples"][:20]:
            lines.append(
                f"- {row['event_name']}: venues={row['known_venue_names_json']} "
                f"priority={row['priority_label']} score={row['priority_score']}"
            )

    lines.extend(
        [
            "",
            "## Collector vs Site Public Events",
            "",
            f"- collector_event_count: {public['collector_event_count']}",
            f"- site_event_count: {public['site_event_count']}",
            f"- collector_only_count: {public['collector_only_count']}",
            f"- site_only_count: {public['site_only_count']}",
            f"- common_rows_with_diff: {public['common_rows_with_diff']}",
            f"- high_risk_diff_counts: {public['high_risk_diff_counts']}",
            "",
            "### Top Field Diffs",
            "",
        ]
    )
    for field, count in list(public["field_diff_counts"].items())[:30]:
        lines.append(f"- {field}: {count}")
    lines.extend(["", "### High-Risk Diff Examples", ""])
    for field in HIGH_RISK_PUBLIC_FIELDS:
        for example in public["examples"].get(field, [])[:3]:
            lines.append(f"- {field}: {example['event_key']}")
        if public["examples"].get(field):
            lines.append("")

    lines.extend(
        [
            "## Worktree Triage",
            "",
            f"- changed_file_count: {git_status['changed_file_count']}",
            f"- groups: {git_status['groups']}",
            "",
            "### Suggested Review Buckets",
            "",
            "- review_commit_candidate_scripts/docs: keep together as migration implementation review.",
            "- master_rdb_generated_artifacts/review_queue_reports/new_review_reports: keep as generated review evidence, or regenerate during review.",
            "- public_output_modified: do not deploy wholesale; only release scoped Ph1 public song outputs.",
            "- youtube_song_master_side_changes: review separately from the master RDB cutover.",
            "",
            "## Recommended Next Actions",
            "",
        ]
    )
    for action in data["recommended_next_actions"]:
        lines.append(f"- {action}")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    parser.add_argument("--master-db", default=str(MASTER_DB))
    parser.add_argument("--collector-events", default=str(COLLECTOR_EVENTS))
    parser.add_argument("--site-events", default=str(SITE_EVENTS))
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    args = parser.parse_args()
    data = build(args)
    public = data["public_events_compare"]
    print(
        "ph2 cutover readiness: "
        f"public_common_diffs={public['common_rows_with_diff']} "
        f"high_risk_fields={public['high_risk_diff_counts']} "
        f"worktree_files={data['git_status']['changed_file_count']}"
    )


if __name__ == "__main__":
    main()
