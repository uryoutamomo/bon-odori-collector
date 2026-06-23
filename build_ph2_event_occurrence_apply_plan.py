"""Build a Ph2 event occurrence dry-run apply plan.

This is read-only review material. It turns the pre-cutover P0 plan and the
master DB dry-run queues into concrete mutation payloads, but it does not write
to Notion, public JSON, or the master SQLite DB.
"""

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from master_db import MASTER_DB, connect_existing, normalize_text


DATA = Path("data")
P0_PLAN = DATA / "pre_cutover_p0_apply_plan.json"
OUT_JSON = DATA / "ph2_event_occurrence_apply_plan.json"
OUT_MD = DATA / "ph2_event_occurrence_apply_plan.md"
REVIEW_DECISIONS = DATA / "ph2_event_occurrence_review_decisions.json"


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
    with connect_existing(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(query, params)]


def occurrence_by_notion_page(db_path):
    data = rows(
        db_path,
        """
        SELECT l.external_id AS notion_page_id,
               o.occurrence_id, o.series_id, s.canonical_name AS series_name,
               o.event_year, o.display_name, o.venue_id, v.canonical_name AS venue_name,
               o.date_start, o.date_end, o.date_status, o.lifecycle_status, o.confidence,
               o.source_kind, o.source_url
        FROM external_record_links l
        JOIN event_occurrences o ON o.occurrence_id = l.master_id
        JOIN event_series s ON s.series_id = o.series_id
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE l.system = 'notion'
          AND l.source_key = 'events'
          AND l.master_table = 'event_occurrences'
        """,
    )
    return {row["notion_page_id"]: row for row in data}


def historical_reference_date_keys(db_path):
    data = rows(
        db_path,
        """
        SELECT occurrence_id, date_start, COALESCE(date_end, '') AS date_end
        FROM occurrence_dates
        WHERE date_type = 'historical_reference'
        """,
    )
    return {
        (row["occurrence_id"], row["date_start"], row["date_end"])
        for row in data
    }


def venue_lookup(db_path):
    venue_rows = rows(
        db_path,
        """
        SELECT venue_id, canonical_name, normalized_name, area, address
        FROM venues
        """,
    )
    alias_rows = rows(
        db_path,
        """
        SELECT a.venue_id, a.alias, a.normalized_alias,
               v.canonical_name, v.normalized_name, v.area, v.address
        FROM venue_aliases a
        JOIN venues v ON v.venue_id = a.venue_id
        """,
    )
    by_norm = {}
    all_rows = []
    for row in venue_rows:
        row = {**row, "matched_by": "canonical", "matched_alias": ""}
        by_norm.setdefault(row["normalized_name"], []).append(row)
        all_rows.append(row)
    for row in alias_rows:
        lookup_row = {
            "venue_id": row["venue_id"],
            "canonical_name": row["canonical_name"],
            "normalized_name": row["normalized_name"],
            "area": row["area"],
            "address": row["address"],
            "matched_by": "alias",
            "matched_alias": row["alias"],
        }
        by_norm.setdefault(row["normalized_alias"], []).append(lookup_row)
    return {"by_norm": by_norm, "all": all_rows}


def venue_suggestions(lookup, name, limit=5):
    normalized = normalize_text(name)
    if not normalized:
        return []
    suggestions = []
    for row in lookup["all"]:
        candidate = row["normalized_name"]
        score = SequenceMatcher(None, normalized, candidate).ratio()
        if normalized in candidate or candidate in normalized:
            score = max(score, 0.92)
        if score < 0.45:
            continue
        suggestions.append({**row, "match_score": round(score, 3)})
    suggestions.sort(key=lambda row: (-row["match_score"], row["canonical_name"]))
    return suggestions[:limit]


def lookup_venue(by_norm, name):
    if not name:
        return {"status": "not_applicable", "matches": []}
    matches = by_norm["by_norm"].get(normalize_text(name), [])
    if matches:
        deduped = {}
        for row in matches:
            deduped.setdefault(row["venue_id"], row)
        matches = list(deduped.values())
    if not matches:
        return {
            "status": "missing_in_master",
            "matches": [],
            "suggestions": venue_suggestions(by_norm, name),
        }
    if len(matches) == 1:
        return {"status": "exact_match", "matches": matches, "suggestions": []}
    return {"status": "ambiguous_match", "matches": matches, "suggestions": venue_suggestions(by_norm, name)}


def date_range(start, end):
    if start and end and end != start:
        return f"{start} to {end}"
    return start or ""


def venue_label(name, status, suggestions=None):
    suggestions = suggestions or []
    if not suggestions:
        return f"{name} ({status})"
    top = suggestions[0]
    return f"{name} ({status}; suggestion: {top['canonical_name']} {top['match_score']})"


def decision_by_event(decisions):
    return {
        row["event_name"]: row
        for row in decisions.get("decisions") or []
        if row.get("event_name")
    }


def accepted_current_official_decision(row, venue_result, decision):
    if not decision:
        return False
    if decision.get("decision") != "accept_current_official_venue_change":
        return False
    if venue_result["status"] != "exact_match":
        return False
    matches = venue_result.get("matches") or []
    if len(matches) != 1:
        return False
    if decision.get("target_venue_id") != matches[0].get("venue_id"):
        return False
    if decision.get("source_url") and decision.get("source_url") != (row.get("source_url") or ""):
        return False
    return True


def accepted_historical_reference_decision(row, venue_result, decision):
    if not decision:
        return False
    if decision.get("decision") != "accept_historical_reference":
        return False
    if decision.get("source_url") and decision.get("source_url") != (row.get("source_url") or ""):
        return False
    if decision.get("historical_date_start") and decision.get("historical_date_start") != (row.get("historical_date_start") or ""):
        return False
    if decision.get("historical_date_end") and decision.get("historical_date_end") != (row.get("historical_date_end") or ""):
        return False
    target_venue_id = decision.get("target_venue_id") or ""
    if decision.get("accept_unregistered_venue"):
        target_venue_name = decision.get("target_venue_name") or decision.get("accepted_alias") or ""
        return bool(target_venue_name and target_venue_name == (row.get("historical_venue") or ""))
    if not target_venue_id:
        return venue_result["status"] == "not_applicable"
    for row in (venue_result.get("matches") or []):
        if row.get("venue_id") == target_venue_id:
            return True
    for row in (venue_result.get("suggestions") or []):
        if row.get("venue_id") == target_venue_id:
            return True
    return False


def proposed_venue_matches_target(occurrence, venue_result, proposed_name):
    if not occurrence:
        return False
    target_venue_id = occurrence.get("venue_id") or ""
    target_venue_name = occurrence.get("venue_name") or ""
    if proposed_name and proposed_name == target_venue_name:
        return True
    for row in (venue_result.get("matches") or []):
        if row.get("venue_id") == target_venue_id:
            return True
    for row in (venue_result.get("suggestions") or []):
        if row.get("venue_id") == target_venue_id and row.get("match_score", 0) >= 0.92:
            return True
    return False


def current_official_already_applied(row, occurrence, venue_result):
    if not occurrence:
        return False
    if occurrence.get("event_year") != 2026:
        return False
    if (occurrence.get("date_start") or "") != (row.get("proposed_date_start") or ""):
        return False
    if (occurrence.get("date_end") or "") != (row.get("proposed_date_end") or ""):
        return False
    if occurrence.get("date_status") != "confirmed":
        return False
    if row.get("confidence") and occurrence.get("confidence") != row.get("confidence"):
        return False
    if not proposed_venue_matches_target(occurrence, venue_result, row.get("proposed_venue") or ""):
        return False
    return True


def current_official_mutation(row, occurrence, venue_result, decision=None):
    flags = []
    accepted_decision = accepted_current_official_decision(row, venue_result, decision)
    already_applied = current_official_already_applied(row, occurrence, venue_result)
    if not occurrence:
        flags.append("missing_target_occurrence")
    else:
        if occurrence["event_year"] != 2026:
            flags.append("target_year_not_2026")
        if occurrence["date_start"] and not already_applied:
            flags.append("target_already_has_date")
        if row.get("proposed_venue") and row.get("proposed_venue") != (occurrence.get("venue_name") or ""):
            if not accepted_decision and not already_applied:
                flags.append("venue_change")
    if venue_result["status"] != "exact_match" and not already_applied:
        flags.append(f"venue_lookup_{venue_result['status']}")
    if row.get("requires_human_review") and not accepted_decision and not already_applied:
        flags.append("human_review_required")

    return {
        "mutation_type": "update_existing_2026_occurrence_from_current_official_source",
        "event_name": row["event_name"],
        "task_id": row["task_id"],
        "notion_page_id": row["notion_page_id"],
        "target": occurrence or {},
        "proposed": {
            "date_start": row.get("proposed_date_start") or "",
            "date_end": row.get("proposed_date_end") or "",
            "date_status": "confirmed",
            "confidence": row.get("confidence") or "unknown",
            "venue_name": row.get("proposed_venue") or "",
            "venue_lookup_status": venue_result["status"],
            "venue_matches": venue_result["matches"],
            "venue_suggestions": venue_result.get("suggestions") or [],
            "source_kind": "official_current_year",
            "source_url": row.get("source_url") or "",
            "source_checked_at": row.get("source_checked_at") or "",
        },
        "rdb_payload": {
            "table": "event_occurrences",
            "operation": "update",
            "set": {
                "date_start": row.get("proposed_date_start") or "",
                "date_end": row.get("proposed_date_end") or "",
                "date_status": "confirmed",
                "confidence": row.get("confidence") or "unknown",
                "source_kind": "official_current_year",
                "source_url": row.get("source_url") or "",
            },
            "also_insert_occurrence_dates": True,
            "venue_update_policy": (
                "update_if_exact_match_after_review"
                if row.get("requires_human_review")
                else "update_if_exact_match"
            ),
        },
        "notion_payload": {
            "direction": "rdb_to_notion_dry_run",
            "target_table": "event_occurrences",
            "action": "set_confirmed_2026_date",
            "fields": {
                "開催日": date_range(row.get("proposed_date_start"), row.get("proposed_date_end")),
                "状態": "確認済み",
                "情報源URL": row.get("source_url") or "",
                "会場": row.get("proposed_venue") or "",
            },
            "confirmed_overwrite_allowed": False,
        },
        "review": {
            "requires_human_review": bool(
                row.get("requires_human_review", False) and not accepted_decision and not already_applied
            ),
            "flags": flags,
            "block_apply_until_resolved": bool(flags) and not already_applied,
            "already_applied": already_applied,
            "notes": row.get("notes") or "",
            "accepted_decision": decision if accepted_decision else {},
        },
    }


def historical_reference_already_applied(row, occurrence, existing_historical_dates):
    if not occurrence:
        return False
    key = (
        occurrence.get("occurrence_id") or "",
        row.get("historical_date_start") or "",
        row.get("historical_date_end") or "",
    )
    return key in existing_historical_dates


def historical_reference_mutation(row, occurrence, venue_result, decision=None, existing_historical_dates=None):
    flags = []
    accepted_decision = accepted_historical_reference_decision(row, venue_result, decision)
    already_applied = historical_reference_already_applied(row, occurrence, existing_historical_dates or set())
    if not occurrence:
        flags.append("missing_target_occurrence")
    if row.get("historical_venue") and venue_result["status"] != "exact_match" and not accepted_decision and not already_applied:
        flags.append(f"historical_venue_lookup_{venue_result['status']}")
    if row.get("requires_human_review") and not accepted_decision and not already_applied:
        flags.append("human_review_required")
    return {
        "mutation_type": "append_historical_reference_without_confirming_2026",
        "event_name": row["event_name"],
        "task_id": row["task_id"],
        "notion_page_id": row["notion_page_id"],
        "target": occurrence or {},
        "historical_reference": {
            "year": int((row.get("historical_date_start") or "2025")[:4]),
            "date_start": row.get("historical_date_start") or "",
            "date_end": row.get("historical_date_end") or "",
            "venue_name": row.get("historical_venue") or "",
            "venue_lookup_status": venue_result["status"],
            "venue_matches": venue_result["matches"],
            "venue_suggestions": venue_result.get("suggestions") or [],
            "accepted_venue_id": decision.get("target_venue_id", "") if accepted_decision else "",
            "accepted_venue_name": decision.get("target_venue_name", "") if accepted_decision else "",
            "evidence_urls": decision.get("evidence_urls", []) if accepted_decision else [],
            "primary_evidence_url": decision.get("primary_evidence_url", "") if accepted_decision else "",
            "confidence": row.get("confidence") or "unknown",
            "source_url": row.get("source_url") or "",
        },
        "rdb_payload": {
            "table": "historical_promotion_candidates_or_future_historical_occurrences",
            "operation": "append_review_note",
            "does_not_update_event_occurrences_date_cache": True,
            "does_not_set_2026_confirmed_date": True,
        },
        "notion_payload": {
            "direction": "rdb_to_notion_dry_run",
            "target_table": "event_occurrences",
            "action": "append_historical_reference_note",
            "fields": {
                "過去実績メモ": date_range(row.get("historical_date_start"), row.get("historical_date_end")),
                "情報源URL": row.get("source_url") or "",
            },
            "confirmed_overwrite_allowed": False,
        },
        "review": {
            "requires_human_review": bool(row.get("requires_human_review", False) and not accepted_decision and not already_applied),
            "flags": flags,
            "block_apply_until_resolved": bool(flags) and not already_applied,
            "already_applied": already_applied,
            "notes": row.get("notes") or "",
            "accepted_decision": decision if accepted_decision else {},
        },
    }


def investigation_task(row):
    return {
        "mutation_type": "keep_investigation_queue",
        "event_name": row["event_name"],
        "task_id": row["task_id"],
        "notion_page_id": row["notion_page_id"],
        "recommended_action": row.get("recommended_action") or "",
        "source_url": row.get("source_url") or "",
        "review": {
            "requires_human_review": row.get("requires_human_review", False),
            "flags": ["no_apply_payload"],
            "block_apply_until_resolved": True,
            "notes": row.get("notes") or "",
        },
    }


def predicted_date_jobs(db_path):
    return rows(
        db_path,
        """
        SELECT p.predicted_date_id, p.target_event_name, p.predicted_year, p.date_start,
               p.date_end, p.basis_type, p.rule_type, p.basis, p.confidence, p.score,
               p.application_status, p.target_occurrence_id, p.target_series_id,
               j.job_id, j.notion_page_id, j.status AS notion_job_status, j.payload_json
        FROM predicted_occurrence_dates p
        LEFT JOIN notion_sync_jobs j
          ON j.target_table = 'predicted_occurrence_dates'
         AND j.target_id = p.predicted_date_id
        ORDER BY p.application_status, p.target_event_name
        """,
    )


def build(args):
    p0_plan = load_json(args.p0_plan, {})
    decisions = decision_by_event(load_json(args.review_decisions, {}))
    occurrence_by_page = occurrence_by_notion_page(args.master_db)
    existing_historical_dates = historical_reference_date_keys(args.master_db)
    venues = venue_lookup(args.master_db)
    mutations = []
    for row in p0_plan.get("rows") or []:
        occurrence = occurrence_by_page.get(row["notion_page_id"])
        if row["bucket"] == "current_2026_apply_candidate":
            venue_result = lookup_venue(venues, row.get("proposed_venue"))
            mutations.append(current_official_mutation(row, occurrence, venue_result, decisions.get(row["event_name"])))
        elif row["bucket"] in {"historical_reference_only", "historical_reference_recorded"}:
            venue_result = lookup_venue(venues, row.get("historical_venue"))
            mutations.append(
                historical_reference_mutation(
                    row,
                    occurrence,
                    venue_result,
                    decisions.get(row["event_name"]),
                    existing_historical_dates,
                )
            )
        else:
            mutations.append(investigation_task(row))

    predicted = predicted_date_jobs(args.master_db)
    by_type = Counter(row["mutation_type"] for row in mutations)
    blocked = [row for row in mutations if row["review"]["block_apply_until_resolved"]]
    already_applied = [
        row for row in mutations
        if row["mutation_type"] == "update_existing_2026_occurrence_from_current_official_source"
        and row["review"].get("already_applied")
    ]
    already_applied_historical = [
        row for row in mutations
        if row["mutation_type"] == "append_historical_reference_without_confirming_2026"
        and row["review"].get("already_applied")
    ]
    data = {
        "generated_by": "build_ph2_event_occurrence_apply_plan.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "read_only_local_review_material",
        "sources": {
            "master_db": str(args.master_db),
            "p0_plan": str(args.p0_plan),
            "review_decisions": str(args.review_decisions),
        },
        "write_policy": {
            "notion_write": "dry_run_payload_only",
            "public_json_write": "not_allowed_by_this_plan",
            "historical_dates": "historical_reference_only; never confirmed 2026 dates",
            "legacy_song_occurrence_generation": "unchanged; keep frozen",
        },
        "summary": {
            "mutation_count": len(mutations),
            "mutations_by_type": dict(by_type),
            "blocked_or_review_required_count": len(blocked),
            "already_applied_current_official_count": len(already_applied),
            "already_applied_historical_reference_count": len(already_applied_historical),
            "predicted_date_job_count": len(predicted),
            "predicted_date_jobs_by_application_status": dict(
                Counter(row["application_status"] for row in predicted)
            ),
        },
        "write_order": [
            "1. Apply current official 2026 updates through the reviewed RDB-primary path when review flags are resolved.",
            "2. Append historical references as evidence notes; do not alter 2026 confirmed dates.",
            "3. Keep predicted dates as candidate/review jobs unless promoted by official current-year evidence.",
            "4. Regenerate local public JSON dry-run and compare collector/site before any deploy.",
        ],
        "mutations": mutations,
        "predicted_date_jobs": predicted,
    }
    write_json(args.out_json, data)
    Path(args.out_md).write_text(render_markdown(data), encoding="utf-8")
    return data


def render_markdown(data):
    lines = [
        "# Ph2 event occurrence apply plan",
        "",
        f"- generated_at: {data['generated_at']}",
        f"- mutation_count: {data['summary']['mutation_count']}",
        f"- mutations_by_type: {data['summary']['mutations_by_type']}",
        f"- blocked_or_review_required_count: {data['summary']['blocked_or_review_required_count']}",
        f"- already_applied_current_official_count: {data['summary']['already_applied_current_official_count']}",
        f"- already_applied_historical_reference_count: {data['summary']['already_applied_historical_reference_count']}",
        f"- predicted_date_job_count: {data['summary']['predicted_date_job_count']}",
        f"- predicted_date_jobs_by_application_status: {data['summary']['predicted_date_jobs_by_application_status']}",
        "",
        "## Current Official 2026 Mutations",
        "",
        "| event | current | proposed | venue | flags | apply |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in data["mutations"]:
        if row["mutation_type"] != "update_existing_2026_occurrence_from_current_official_source":
            continue
        target = row["target"]
        proposed = row["proposed"]
        flags = ", ".join(row["review"]["flags"])
        apply_status = (
            "already_applied"
            if row["review"].get("already_applied")
            else ("blocked" if row["review"]["block_apply_until_resolved"] else "ready_after_review")
        )
        lines.append(
            f"| {row['event_name']} | {date_range(target.get('date_start'), target.get('date_end'))} / "
            f"{target.get('venue_name') or ''} | {date_range(proposed['date_start'], proposed['date_end'])} | "
            f"{venue_label(proposed['venue_name'], proposed['venue_lookup_status'], proposed.get('venue_suggestions'))} | {flags} | "
            f"{apply_status} |"
        )
    lines.extend(
        [
            "",
            "## Historical Reference Mutations",
            "",
            "| event | historical date | venue | confidence | flags | apply |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in data["mutations"]:
        if row["mutation_type"] != "append_historical_reference_without_confirming_2026":
            continue
        ref = row["historical_reference"]
        apply_status = (
            "already_applied"
            if row["review"].get("already_applied")
            else ("blocked" if row["review"]["block_apply_until_resolved"] else "ready_after_review")
        )
        lines.append(
            f"| {row['event_name']} | {date_range(ref['date_start'], ref['date_end'])} | "
            f"{venue_label(ref['venue_name'], ref['venue_lookup_status'], ref.get('venue_suggestions'))} | {ref['confidence']} | "
            f"{', '.join(row['review']['flags'])} | {apply_status} |"
        )
    lines.extend(
        [
            "",
            "## Keep In Queue",
            "",
            "| event | action | note |",
            "| --- | --- | --- |",
        ]
    )
    for row in data["mutations"]:
        if row["mutation_type"] != "keep_investigation_queue":
            continue
        lines.append(f"| {row['event_name']} | {row['recommended_action']} | {row['review']['notes']} |")
    lines.extend(
        [
            "",
            "## Predicted Date Jobs",
            "",
            "| event | predicted | basis | status | notion job |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for row in data["predicted_date_jobs"]:
        lines.append(
            f"| {row['target_event_name']} | {date_range(row['date_start'], row['date_end'])} | "
            f"{row['basis']} | {row['application_status']} | {row.get('notion_job_status') or ''} |"
        )
    lines.extend(["", "## Write Order", ""])
    for item in data["write_order"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-db", default=str(MASTER_DB))
    parser.add_argument("--p0-plan", default=str(P0_PLAN))
    parser.add_argument("--review-decisions", default=str(REVIEW_DECISIONS))
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    args = parser.parse_args()
    data = build(args)
    print(
        "ph2 event occurrence apply plan: "
        f"mutations={data['summary']['mutation_count']} "
        f"blocked={data['summary']['blocked_or_review_required_count']} "
        f"predicted_jobs={data['summary']['predicted_date_job_count']}"
    )


if __name__ == "__main__":
    main()
