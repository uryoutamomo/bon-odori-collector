#!/usr/bin/env python3
"""Build or apply Notion updates from master RDB sync jobs.

Default mode is a local dry-run: it reads pending notion_sync_jobs and writes
JSON/Markdown review material without calling Notion. Actual Notion writes
require --apply, non-dry-run jobs, and the confirmation phrase.
"""

import argparse
import json
import os
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from master_db import MASTER_DB
from notion_api import NotionApi
from notion_config import load_local_env


DATA = Path("data")
OUT_JSON = DATA / "master_to_notion_sync_dry_run.json"
OUT_MD = DATA / "master_to_notion_sync_dry_run.md"
NOTION_SNAPSHOT = DATA / "notion_snapshot.sqlite"
CONFIRM_PHRASE = "APPLY RDB TO NOTION"


def rows(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def load_payload(text):
    if not text:
        return {}
    return json.loads(text)


def atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".tmp-", suffix=".json", delete=False
    ) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        tmp_name = handle.name
    Path(tmp_name).replace(path)


def atomic_write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".tmp-", suffix=".md", delete=False
    ) as handle:
        handle.write(text)
        tmp_name = handle.name
    Path(tmp_name).replace(path)


def date_prop(start, end=None):
    if not start:
        return {"date": None}
    value = {"start": start}
    if end and end != start:
        value["end"] = end
    return {"date": value}


def select_prop(name):
    return {"select": {"name": name}} if name else {"select": None}


def rich_text_prop(text):
    if not text:
        return {"rich_text": []}
    chunks = [str(text)[i:i + 1900] for i in range(0, len(str(text)), 1900)]
    return {"rich_text": [{"text": {"content": chunk}} for chunk in chunks[:100]]}


def parse_iso_datetime(value):
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def md_escape(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def status_from_payload_or_occurrence(payload, occurrence):
    fields = payload.get("fields") or {}
    if fields.get("状態"):
        return fields["状態"]
    if occurrence.get("date_status") == "confirmed":
        return "確認済み"
    if occurrence.get("date_status") == "ended":
        return "終了"
    return "要確認"


def event_occurrence(conn, occurrence_id):
    result = rows(
        conn,
        """
        SELECT o.occurrence_id, o.display_name, o.event_year, o.venue_id,
               v.canonical_name AS venue_name, o.date_start, o.date_end,
               o.date_status, o.lifecycle_status, o.confidence, o.source_url
        FROM event_occurrences o
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE o.occurrence_id = ?
        """,
        (occurrence_id,),
    )
    return result[0] if result else None


def notion_page_for(conn, source_key, master_table, master_id):
    result = rows(
        conn,
        """
        SELECT external_id
        FROM external_record_links
        WHERE system = 'notion'
          AND source_key = ?
          AND master_table = ?
          AND master_id = ?
          AND relation_kind = 'primary'
        LIMIT 1
        """,
        (source_key, master_table, master_id),
    )
    return result[0]["external_id"] if result else ""


def notion_snapshot_event(snapshot_db, page_id):
    if not snapshot_db or not Path(snapshot_db).exists() or not page_id:
        return {}
    with sqlite3.connect(snapshot_db) as conn:
        result = rows(
            conn,
            """
            SELECT e.page_id, e.event_name, e.venue_ids_json, e.start_date,
                   e.end_date, e.status, e.source_url, p.last_edited_time
            FROM notion_events e
            JOIN notion_pages p ON p.page_id = e.page_id
            WHERE e.page_id = ?
            """,
            (page_id,),
        )
    if not result:
        return {}
    row = result[0]
    row["venue_ids"] = json.loads(row.pop("venue_ids_json") or "[]")
    row["venue_names"] = notion_venue_names(snapshot_db, row["venue_ids"])
    return row


def notion_snapshot_venue(snapshot_db, page_id):
    if not snapshot_db or not Path(snapshot_db).exists() or not page_id:
        return {}
    with sqlite3.connect(snapshot_db) as conn:
        result = rows(
            conn,
            """
            SELECT v.page_id, v.venue_name, v.area, v.address, v.access,
                   v.scale, v.public_intro, p.last_edited_time
            FROM notion_venues v
            JOIN notion_pages p ON p.page_id = v.page_id
            WHERE v.page_id = ?
            """,
            (page_id,),
        )
    return result[0] if result else {}


def notion_venue_names(snapshot_db, venue_ids):
    if not venue_ids:
        return []
    placeholders = ",".join("?" for _ in venue_ids)
    with sqlite3.connect(snapshot_db) as conn:
        result = rows(
            conn,
            f"""
            SELECT page_id, venue_name
            FROM notion_venues
            WHERE page_id IN ({placeholders})
            ORDER BY venue_name
            """,
            venue_ids,
        )
    names_by_id = {row["page_id"]: row["venue_name"] for row in result}
    return [names_by_id.get(page_id, page_id) for page_id in venue_ids]


def proposed_values(properties, target):
    date_value = ((properties.get("開催日") or {}).get("date") or {})
    status_value = (((properties.get("状態") or {}).get("select") or {}).get("name") or "")
    source_url = (properties.get("情報源URL") or {}).get("url") or ""
    relation = (properties.get("会場") or {}).get("relation") or []
    return {
        "start_date": date_value.get("start") or "",
        "end_date": date_value.get("end") or "",
        "status": status_value,
        "source_url": source_url,
        "venue_ids": [row.get("id") for row in relation if row.get("id")],
        "venue_names": [target.get("venue_name")] if target.get("venue_name") else [],
    }


def field_diffs(current, proposed):
    specs = [
        ("開催日", "start_date"),
        ("終了日", "end_date"),
        ("状態", "status"),
        ("情報源URL", "source_url"),
        ("会場", "venue_names"),
        ("会場ページID", "venue_ids"),
    ]
    diffs = []
    for label, key in specs:
        current_value = current.get(key) if current else ""
        proposed_value = proposed.get(key) if proposed else ""
        if isinstance(current_value, list):
            current_value = ", ".join(current_value)
        if isinstance(proposed_value, list):
            proposed_value = ", ".join(proposed_value)
        diffs.append(
            {
                "field": label,
                "current": current_value or "",
                "proposed": proposed_value or "",
                "changed": (current_value or "") != (proposed_value or ""),
            }
        )
    return diffs


def venue_field_diffs(current, proposed):
    diffs = []
    for label, key in [("住所", "address")]:
        current_value = current.get(key) if current else ""
        proposed_value = proposed.get(key) if proposed else ""
        diffs.append(
            {
                "field": label,
                "current": current_value or "",
                "proposed": proposed_value or "",
                "changed": (current_value or "") != (proposed_value or ""),
            }
        )
    return diffs


def pending_jobs(conn, args):
    directions = ["rdb_to_notion"]
    if args.include_dry_run_jobs:
        directions.append("rdb_to_notion_dry_run")
    placeholders = ",".join("?" for _ in directions)
    params = directions + [args.status]
    where = [f"direction IN ({placeholders})", "status = ?"]
    if args.target_table:
        where.append("target_table = ?")
        params.append(args.target_table)
    if args.job_id:
        where.append("job_id = ?")
        params.append(args.job_id)
    if args.requested_by:
        where.append("requested_by = ?")
        params.append(args.requested_by)
    return rows(
        conn,
        f"""
        SELECT job_id, direction, target_table, target_id, notion_source_key,
               notion_page_id, status, requested_by, requested_at, payload_json
        FROM notion_sync_jobs
        WHERE {' AND '.join(where)}
        ORDER BY requested_at, job_id
        """,
        params,
    )


def build_event_occurrence_update(conn, job, snapshot_db):
    payload = load_payload(job["payload_json"])
    occurrence = event_occurrence(conn, job["target_id"])
    issues = []
    if not occurrence:
        issues.append({"severity": "high", "issue_type": "missing_event_occurrence"})
        return {"job": job, "payload": payload, "issues": issues, "properties": {}, "skip_reason": "missing_target"}

    notion_page_id = job.get("notion_page_id") or notion_page_for(
        conn, "events", "event_occurrences", occurrence["occurrence_id"]
    )
    if not notion_page_id:
        issues.append({"severity": "high", "issue_type": "missing_notion_event_page"})

    venue_page_id = ""
    if occurrence.get("venue_id"):
        venue_page_id = notion_page_for(conn, "venues", "venues", occurrence["venue_id"])
        if not venue_page_id:
            issues.append({"severity": "medium", "issue_type": "missing_notion_venue_page"})

    properties = {
        "開催日": date_prop(occurrence.get("date_start"), occurrence.get("date_end")),
        "状態": select_prop(status_from_payload_or_occurrence(payload, occurrence)),
    }
    source_url = (payload.get("fields") or {}).get("情報源URL") or occurrence.get("source_url")
    if source_url:
        properties["情報源URL"] = {"url": source_url}
    if venue_page_id:
        properties["会場"] = {"relation": [{"id": venue_page_id}]}

    current = notion_snapshot_event(snapshot_db, notion_page_id)
    current_last_edited = parse_iso_datetime(current.get("last_edited_time"))
    requested_at = parse_iso_datetime(job.get("requested_at"))
    if current_last_edited and requested_at and current_last_edited > requested_at:
        issues.append(
            {
                "severity": "high",
                "issue_type": "notion_page_changed_after_job_requested",
                "notion_last_edited_time": current.get("last_edited_time"),
                "job_requested_at": job.get("requested_at"),
            }
        )
    proposed = proposed_values(properties, {
        "venue_name": occurrence.get("venue_name") or "",
    })
    return {
        "job": dict(job, payload_json=None),
        "payload": payload,
        "target": {
            "notion_page_id": notion_page_id,
            "occurrence_id": occurrence["occurrence_id"],
            "event_name": occurrence["display_name"],
            "venue_id": occurrence.get("venue_id") or "",
            "venue_name": occurrence.get("venue_name") or "",
            "venue_notion_page_id": venue_page_id,
            "date_start": occurrence.get("date_start") or "",
            "date_end": occurrence.get("date_end") or "",
            "date_status": occurrence.get("date_status") or "",
            "source_url": source_url or "",
        },
        "current_notion_snapshot": current,
        "proposed_notion_values": proposed,
        "field_diffs": field_diffs(current, proposed),
        "properties": properties,
        "issues": issues,
        "skip_reason": "validation_issue" if any(row["severity"] == "high" for row in issues) else "",
    }


def venue(conn, venue_id):
    result = rows(
        conn,
        """
        SELECT venue_id, canonical_name, area, address, source_url
        FROM venues
        WHERE venue_id = ?
        """,
        (venue_id,),
    )
    return result[0] if result else None


def build_venue_update(conn, job, snapshot_db):
    payload = load_payload(job["payload_json"])
    target = venue(conn, job["target_id"])
    issues = []
    if not target:
        issues.append({"severity": "high", "issue_type": "missing_venue"})
        return {"job": job, "payload": payload, "issues": issues, "properties": {}, "skip_reason": "missing_target"}
    notion_page_id = job.get("notion_page_id") or notion_page_for(
        conn, "venues", "venues", target["venue_id"]
    )
    if not notion_page_id:
        issues.append({"severity": "high", "issue_type": "missing_notion_venue_page"})
    properties = {
        "住所": rich_text_prop(target.get("address") or ""),
    }
    current = notion_snapshot_venue(snapshot_db, notion_page_id)
    current_last_edited = parse_iso_datetime(current.get("last_edited_time"))
    requested_at = parse_iso_datetime(job.get("requested_at"))
    if current_last_edited and requested_at and current_last_edited > requested_at:
        issues.append(
            {
                "severity": "high",
                "issue_type": "notion_page_changed_after_job_requested",
                "notion_last_edited_time": current.get("last_edited_time"),
                "job_requested_at": job.get("requested_at"),
            }
        )
    proposed = {
        "address": target.get("address") or "",
    }
    return {
        "job": dict(job, payload_json=None),
        "payload": payload,
        "target": {
            "notion_page_id": notion_page_id,
            "venue_id": target["venue_id"],
            "venue_name": target["canonical_name"],
            "address": target.get("address") or "",
        },
        "current_notion_snapshot": current,
        "proposed_notion_values": proposed,
        "field_diffs": venue_field_diffs(current, proposed),
        "properties": properties,
        "issues": issues,
        "skip_reason": "validation_issue" if any(row["severity"] == "high" for row in issues) else "",
    }


def predicted_occurrence_date(conn, predicted_date_id):
    result = rows(
        conn,
        """
        SELECT p.predicted_date_id, p.target_event_name, p.predicted_year,
               p.date_start, p.date_end, p.date_status, p.basis_type_label,
               p.rule_type, p.basis, p.confidence, p.score,
               p.application_status, p.target_series_id, p.target_occurrence_id,
               p.source_payload_json, s.canonical_name AS series_name
        FROM predicted_occurrence_dates p
        JOIN event_series s ON s.series_id = p.target_series_id
        WHERE p.predicted_date_id = ?
        """,
        (predicted_date_id,),
    )
    return result[0] if result else None


def build_predicted_occurrence_date_update(conn, job, snapshot_db):
    payload = load_payload(job["payload_json"])
    target = predicted_occurrence_date(conn, job["target_id"])
    issues = []
    if not target:
        issues.append({"severity": "high", "issue_type": "missing_predicted_occurrence_date"})
        return {"job": job, "payload": payload, "issues": issues, "properties": {}, "skip_reason": "missing_target"}

    source_payload = load_payload(target.get("source_payload_json"))
    venue_name = source_payload.get("venue") or ""
    issues.append(
        {
            "severity": "medium",
            "issue_type": "predicted_occurrence_date_jobs_are_review_only",
            "detail": "sync_master_to_notion does not create predicted Notion events directly",
        }
    )
    field_diffs_ = [
        {"field": "開催日", "current": "", "proposed": target.get("date_start") or "", "changed": True},
        {"field": "終了日", "current": "", "proposed": target.get("date_end") or "", "changed": bool(target.get("date_end"))},
        {"field": "状態", "current": "", "proposed": target.get("date_status") or "", "changed": True},
        {"field": "予測根拠", "current": "", "proposed": target.get("basis") or "", "changed": bool(target.get("basis"))},
        {"field": "会場候補", "current": "", "proposed": venue_name, "changed": bool(venue_name)},
    ]
    return {
        "job": dict(job, payload_json=None),
        "payload": payload,
        "target": {
            "predicted_date_id": target["predicted_date_id"],
            "event_name": target["target_event_name"],
            "series_id": target["target_series_id"],
            "series_name": target["series_name"],
            "target_occurrence_id": target.get("target_occurrence_id") or "",
            "predicted_year": target["predicted_year"],
            "date_start": target.get("date_start") or "",
            "date_end": target.get("date_end") or "",
            "date_status": target.get("date_status") or "",
            "basis_type_label": target.get("basis_type_label") or "",
            "rule_type": target.get("rule_type") or "",
            "basis": target.get("basis") or "",
            "confidence": target.get("confidence") or "",
            "score": target.get("score"),
            "application_status": target.get("application_status") or "",
            "venue_name": venue_name,
        },
        "current_notion_snapshot": {},
        "proposed_notion_values": {
            "start_date": target.get("date_start") or "",
            "end_date": target.get("date_end") or "",
            "status": target.get("date_status") or "",
            "venue_names": [venue_name] if venue_name else [],
        },
        "field_diffs": field_diffs_,
        "properties": {},
        "issues": issues,
        "skip_reason": "prediction_review_only",
    }


def build_update(conn, job, snapshot_db):
    if job["target_table"] == "event_occurrences" and job["notion_source_key"] == "events":
        return build_event_occurrence_update(conn, job, snapshot_db)
    if job["target_table"] == "venues" and job["notion_source_key"] == "venues":
        return build_venue_update(conn, job, snapshot_db)
    if job["target_table"] == "predicted_occurrence_dates" and job["notion_source_key"] == "events":
        return build_predicted_occurrence_date_update(conn, job, snapshot_db)
    return {
        "job": dict(job, payload_json=None),
        "payload": load_payload(job["payload_json"]),
        "properties": {},
        "issues": [{"severity": "medium", "issue_type": "unsupported_job_target"}],
        "skip_reason": "unsupported_job_target",
    }


def validate_apply(args, updates):
    if not args.apply:
        return
    if args.confirm != CONFIRM_PHRASE:
        raise ValueError(f"--apply requires --confirm '{CONFIRM_PHRASE}'")
    dry_run_jobs = [row for row in updates if row["job"]["direction"] == "rdb_to_notion_dry_run"]
    if dry_run_jobs:
        raise ValueError("--apply refuses rdb_to_notion_dry_run jobs")
    blocked = [row for row in updates if row.get("skip_reason")]
    if blocked:
        raise ValueError(f"--apply refuses jobs with validation issues; blocked={len(blocked)}")


def apply_updates(conn, updates):
    load_local_env()
    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    now = datetime.now(timezone.utc).isoformat()
    applied = []
    for update in updates:
        page_id = update["target"]["notion_page_id"]
        response = api.update_page(page_id, update["properties"])
        result = {
            "notion_page_id": page_id,
            "notion_last_edited_time": response.get("last_edited_time", ""),
        }
        conn.execute(
            """
            UPDATE notion_sync_jobs
            SET status = 'applied',
                applied_at = ?,
                result_json = ?
            WHERE job_id = ?
            """,
            (now, json.dumps(result, ensure_ascii=False, sort_keys=True), update["job"]["job_id"]),
        )
        applied.append(update["job"]["job_id"])
    conn.commit()
    return applied


def render_markdown(result):
    target_tables = set(result["summary"].get("jobs_by_target_table") or {})
    event_names = [
        (row.get("target") or {}).get("event_name") or (row.get("target") or {}).get("venue_name")
        for row in result.get("updates") or []
        if (row.get("target") or {}).get("event_name") or (row.get("target") or {}).get("venue_name")
    ]
    apply_event_name = event_names[0] if len(set(event_names)) == 1 else "<reviewed event name>"
    if target_tables == {"venues"}:
        sequence_lines = [
            "1. RDB venue review apply queues the venue sync job.",
            "2. Refresh Notion snapshot immediately before Notion apply: `python3 build_notion_rdb.py`",
            "3. Venue sync only after review: `python3 sync_master_to_notion.py --target-table venues --requested-by apply_ph2_shinagawa_second_venue_review.py --apply --confirm 'APPLY RDB TO NOTION'`",
        ]
    else:
        sequence_lines = [
            f"1. RDB apply only: `python3 dry_run_ph2_event_occurrence_apply.py --apply --event-name '{apply_event_name}' --confirm 'APPLY PH2 EVENT OCCURRENCE'`",
            "2. Refresh Notion snapshot immediately before Notion apply: `python3 build_notion_rdb.py`",
            "3. Notion sync only after review: `python3 sync_master_to_notion.py --requested-by dry_run_ph2_event_occurrence_apply.py --apply --confirm 'APPLY RDB TO NOTION'`",
        ]
    lines = [
        "# Master RDB -> Notion sync dry-run",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- master_db: `{result['sources']['master_db']}`",
        f"- selected_jobs: {result['summary']['selected_jobs']}",
        f"- ready_jobs: {result['summary']['ready_jobs']}",
        f"- skipped_jobs: {result['summary']['skipped_jobs']}",
        f"- applied_jobs: {result['summary']['applied_jobs']}",
        f"- issues_by_severity: {result['summary']['issues_by_severity']}",
        "",
        "## Apply Sequence",
        "",
        *sequence_lines,
        "",
        "Both apply steps require separate review and explicit approval before running against production inputs.",
        "The snapshot refresh is mandatory because drift detection uses `data/notion_snapshot.sqlite`.",
        "",
        "| job | target | date | status | venue | page | result |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in result["updates"]:
        target = row.get("target") or {}
        props = row.get("properties") or {}
        date_value = ((props.get("開催日") or {}).get("date") or {})
        status_value = (((props.get("状態") or {}).get("select") or {}).get("name") or "")
        result_text = row.get("skip_reason") or "ready"
        lines.append(
            "| {job} | {event} | {date} | {status} | {venue} | {page} | {result} |".format(
                job=row["job"]["job_id"],
                event=(target.get("event_name") or target.get("venue_name") or "").replace("|", "\\|"),
                date=(date_value.get("start") or target.get("date_start") or ""),
                status=(status_value or target.get("date_status") or ""),
                venue=(target.get("venue_name") or "").replace("|", "\\|"),
                page=target.get("notion_page_id") or "",
                result=result_text,
            )
        )
    if result["issues"]:
        lines.extend(["", "## Issues", ""])
        for issue in result["issues"]:
            lines.append(f"- {issue['severity']} {issue['issue_type']}: {issue}")
    lines.extend(["", "## Field Diffs", ""])
    for row in result["updates"]:
        target = row.get("target") or {}
        last_edited = md_escape((row.get("current_notion_snapshot") or {}).get("last_edited_time"))
        last_edited_line = f"- Notion last edited: {last_edited}" if last_edited else "- Notion last edited:"
        lines.extend(
            [
                f"### {md_escape(target.get('event_name') or target.get('venue_name'))}",
                "",
                f"- job: `{row['job']['job_id']}`",
                last_edited_line,
                f"- job requested at: {md_escape(row['job'].get('requested_at'))}",
                "",
                "| field | current Notion snapshot | proposed | changed |",
                "| --- | --- | --- | --- |",
            ]
        )
        for diff in row.get("field_diffs") or []:
            lines.append(
                f"| {md_escape(diff['field'])} | {md_escape(diff['current'])} | "
                f"{md_escape(diff['proposed'])} | {diff['changed']} |"
            )
        lines.append("")
    return "\n".join(lines)


def run(args):
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(args.master_db) as conn:
        jobs = pending_jobs(conn, args)
        updates = [build_update(conn, job, args.notion_snapshot_db) for job in jobs]
        validate_apply(args, updates)
        applied = apply_updates(conn, updates) if args.apply else []

    issues = []
    for update in updates:
        for issue in update.get("issues") or []:
            issue = dict(issue)
            issue["job_id"] = update["job"]["job_id"]
            issues.append(issue)
    summary = {
        "selected_jobs": len(updates),
        "ready_jobs": sum(1 for row in updates if not row.get("skip_reason")),
        "skipped_jobs": sum(1 for row in updates if row.get("skip_reason")),
        "applied_jobs": len(applied),
        "jobs_by_direction": dict(Counter(row["job"]["direction"] for row in updates)),
        "jobs_by_target_table": dict(Counter(row["job"]["target_table"] for row in updates)),
        "issues_by_severity": dict(Counter(row["severity"] for row in issues)),
    }
    result = {
        "generated_by": "sync_master_to_notion.py",
        "generated_at": now,
        "mode": "apply" if args.apply else "dry_run",
        "apply_performed": bool(args.apply),
        "sources": {
            "master_db": str(args.master_db),
            "notion_snapshot_db": str(args.notion_snapshot_db),
        },
        "options": {
            "target_table": args.target_table,
            "job_id": args.job_id or "",
            "requested_by": args.requested_by or "",
            "include_dry_run_jobs": args.include_dry_run_jobs,
        },
        "summary": summary,
        "applied_job_ids": applied,
        "updates": updates,
        "issues": issues,
    }
    atomic_write_json(args.out_json, result)
    atomic_write_text(args.out_md, render_markdown(result))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-db", type=Path, default=MASTER_DB)
    parser.add_argument("--notion-snapshot-db", type=Path, default=NOTION_SNAPSHOT)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    parser.add_argument("--target-table", default="event_occurrences")
    parser.add_argument("--job-id", default="")
    parser.add_argument("--requested-by", default="")
    parser.add_argument("--status", default="pending")
    parser.add_argument("--include-dry-run-jobs", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        result = run(args)
    except ValueError as exc:
        parser.error(str(exc))
    print(
        "master to notion sync: "
        f"mode={result['mode']} "
        f"selected={result['summary']['selected_jobs']} "
        f"ready={result['summary']['ready_jobs']} "
        f"skipped={result['summary']['skipped_jobs']} "
        f"applied={result['summary']['applied_jobs']} "
        f"out={args.out_json}"
    )
    return 1 if result["summary"]["issues_by_severity"].get("high") else 0


if __name__ == "__main__":
    raise SystemExit(main())
