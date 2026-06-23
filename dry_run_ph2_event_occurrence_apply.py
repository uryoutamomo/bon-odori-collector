"""Dry-run apply Ph2 event occurrence mutations on a copied SQLite DB.

By default this script never writes to Notion, queues Notion sync jobs, writes
public JSON, or touches the source master DB. It copies the master DB and
applies only unblocked mutations from the Ph2 apply plan.

The source master DB can only be updated with an explicit --apply invocation
that names exactly one event and repeats the required confirmation phrase.
"""

import argparse
import json
import shutil
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from master_db import MASTER_DB, connect_existing, stable_id


DATA = Path("data")
PLAN_JSON = DATA / "ph2_event_occurrence_apply_plan.json"
OUT_DB = DATA / "ph2_event_occurrence_apply_dry_run.sqlite"
OUT_JSON = DATA / "ph2_event_occurrence_apply_dry_run_report.json"
OUT_MD = DATA / "ph2_event_occurrence_apply_dry_run_report.md"
CONFIRM_PHRASE = "APPLY PH2 EVENT OCCURRENCE"
BACKUP_DIR = DATA / "backups"
MUTATION_TYPES = {
    "current_official": "update_existing_2026_occurrence_from_current_official_source",
    "historical_reference": "append_historical_reference_without_confirming_2026",
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


def rows(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def scalar(conn, query, params=()):
    return conn.execute(query, params).fetchone()[0]


def copy_db(source, out_db):
    source = Path(source)
    out_db = Path(out_db)
    if not source.exists():
        raise FileNotFoundError(source)
    out_db.parent.mkdir(parents=True, exist_ok=True)
    if out_db.exists():
        out_db.unlink()
    shutil.copy2(source, out_db)


def backup_db(source, now):
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(source)
    stamp = now.replace("-", "").replace(":", "").replace("+00:00", "Z")
    backup = BACKUP_DIR / f"{source.stem}.{stamp}{source.suffix}.bak"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup)
    return backup


def validate_apply_request(args):
    if not args.apply:
        return
    if args.include_blocked:
        raise ValueError("--apply refuses --include-blocked")
    if not args.event_name:
        raise ValueError("--apply requires --event-name")
    if args.confirm != CONFIRM_PHRASE:
        raise ValueError(f"--apply requires --confirm '{CONFIRM_PHRASE}'")
    if Path(args.out_db) == Path(args.master_db):
        raise ValueError("--out-db must not equal --master-db")


def target_occurrence(conn, occurrence_id):
    result = rows(
        conn,
        """
        SELECT o.occurrence_id, o.series_id, s.canonical_name AS series_name,
               o.event_year, o.display_name, o.venue_id, v.canonical_name AS venue_name,
               o.date_start, o.date_end, o.date_status, o.lifecycle_status, o.confidence,
               o.source_kind, o.source_url
        FROM event_occurrences o
        JOIN event_series s ON s.series_id = o.series_id
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE o.occurrence_id = ?
        """,
        (occurrence_id,),
    )
    return result[0] if result else {}


def exact_venue_id(mutation):
    proposed = mutation.get("proposed") or {}
    if proposed.get("venue_lookup_status") != "exact_match":
        return None
    matches = proposed.get("venue_matches") or []
    if len(matches) != 1:
        return None
    return matches[0]["venue_id"]


def apply_current_official(conn, mutation, now):
    target = mutation["target"]
    proposed = mutation["proposed"]
    occurrence_id = target["occurrence_id"]
    before = target_occurrence(conn, occurrence_id)
    venue_id = exact_venue_id(mutation)

    update_fields = {
        "date_start": proposed["date_start"],
        "date_end": proposed["date_end"],
        "date_status": proposed["date_status"],
        "confidence": proposed["confidence"],
        "source_kind": proposed["source_kind"],
        "source_url": proposed["source_url"],
        "updated_at": now,
    }
    if venue_id:
        update_fields["venue_id"] = venue_id
    assignments = ", ".join(f"{key} = ?" for key in update_fields)
    params = list(update_fields.values()) + [occurrence_id]
    conn.execute(f"UPDATE event_occurrences SET {assignments} WHERE occurrence_id = ?", params)

    occurrence_date_id = stable_id(
        "odate",
        occurrence_id,
        proposed["date_start"],
        proposed["date_end"],
        proposed["source_url"],
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO occurrence_dates(
          occurrence_date_id, occurrence_id, date_start, date_end, date_type,
          confidence, basis, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            occurrence_date_id,
            occurrence_id,
            proposed["date_start"],
            proposed["date_end"],
            proposed["date_status"],
            proposed["confidence"],
            proposed["source_url"],
            now,
        ),
    )

    after = target_occurrence(conn, occurrence_id)
    return {
        "mutation_type": mutation["mutation_type"],
        "action": "update_current_official_2026_occurrence",
        "event_name": mutation["event_name"],
        "occurrence_id": occurrence_id,
        "notion_page_id": mutation["notion_page_id"],
        "before": before,
        "after": after,
        "inserted_occurrence_date_id": occurrence_date_id,
        "inserted_notion_sync_job_id": "",
        "notion_sync_job_queued": False,
    }


def apply_historical_reference(conn, mutation, now):
    target = mutation["target"]
    ref = mutation["historical_reference"]
    occurrence_id = target["occurrence_id"]
    before = target_occurrence(conn, occurrence_id)
    occurrence_date_id = stable_id(
        "odate",
        "historical_reference",
        occurrence_id,
        ref["date_start"],
        ref.get("date_end") or "",
        ref.get("source_url") or "",
    )
    basis = {
        "source": "ph2_historical_reference",
        "source_url": ref.get("source_url") or "",
        "primary_evidence_url": ref.get("primary_evidence_url") or "",
        "evidence_urls": ref.get("evidence_urls") or [],
        "historical_venue_name": ref.get("venue_name") or "",
        "accepted_venue_name": ref.get("accepted_venue_name") or "",
        "venue_lookup_status": ref.get("venue_lookup_status") or "",
        "does_not_confirm_target_year": True,
    }
    conn.execute(
        """
        INSERT OR REPLACE INTO occurrence_dates(
          occurrence_date_id, occurrence_id, date_start, date_end, date_type,
          confidence, basis, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            occurrence_date_id,
            occurrence_id,
            ref["date_start"],
            ref.get("date_end") or None,
            "historical_reference",
            ref.get("confidence") or "unknown",
            json.dumps(basis, ensure_ascii=False, sort_keys=True),
            now,
        ),
    )
    after = target_occurrence(conn, occurrence_id)
    return {
        "mutation_type": mutation["mutation_type"],
        "action": "append_historical_reference_without_confirming_2026",
        "event_name": mutation["event_name"],
        "occurrence_id": occurrence_id,
        "notion_page_id": mutation["notion_page_id"],
        "before": before,
        "after": after,
        "inserted_occurrence_date_id": occurrence_date_id,
        "inserted_occurrence_date_type": "historical_reference",
        "inserted_notion_sync_job_id": "",
        "historical_reference": ref,
    }


def consistency_checks(conn, applied):
    issues = []
    fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_rows:
        issues.append(
            {
                "severity": "high",
                "issue_type": "foreign_key_check_failed",
                "count": len(fk_rows),
                "sample": [tuple(row) for row in fk_rows[:10]],
            }
        )
    for item in applied:
        occurrence_id = item["occurrence_id"]
        duplicate_dates = scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM (
              SELECT occurrence_id, date_start, COALESCE(date_end, ''), date_type, COUNT(*) c
              FROM occurrence_dates
              WHERE occurrence_id = ?
              GROUP BY occurrence_id, date_start, COALESCE(date_end, ''), date_type
              HAVING c > 1
            )
            """,
            (occurrence_id,),
        )
        if duplicate_dates:
            issues.append(
                {
                    "severity": "medium",
                    "issue_type": "duplicate_occurrence_date_after_apply",
                    "occurrence_id": occurrence_id,
                    "count": duplicate_dates,
                }
            )
        if item.get("mutation_type") != MUTATION_TYPES["current_official"]:
            continue
        occurrence = target_occurrence(conn, occurrence_id)
        date_cache_rows = rows(
            conn,
            """
            SELECT date_start, COALESCE(date_end, '') AS date_end, date_type
            FROM occurrence_dates
            WHERE occurrence_id = ?
              AND date_type IN ('confirmed', 'ended', 'predicted', 'historical_reference')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (occurrence_id,),
        )
        if date_cache_rows:
            latest = date_cache_rows[0]
            if (
                occurrence.get("date_start") != latest["date_start"]
                or (occurrence.get("date_end") or "") != latest["date_end"]
                or occurrence.get("date_status") != latest["date_type"]
            ):
                issues.append(
                    {
                        "severity": "high",
                        "issue_type": "date_cache_mismatch_after_apply",
                        "occurrence_id": occurrence_id,
                        "occurrence": occurrence,
                        "latest_date_row": latest,
                    }
                )
    return issues


def select_mutations(plan, event_name=None, include_blocked=False, mutation_type="current_official"):
    selected = []
    skipped = []
    expected_type = MUTATION_TYPES[mutation_type]
    for mutation in plan.get("mutations") or []:
        if mutation.get("mutation_type") != expected_type:
            skipped.append(
                {
                    "event_name": mutation.get("event_name"),
                    "reason": "not_selected_mutation_type",
                    "mutation_type": mutation.get("mutation_type"),
                }
            )
            continue
        if event_name and mutation.get("event_name") != event_name:
            skipped.append({"event_name": mutation.get("event_name"), "reason": "event_filter"})
            continue
        review = mutation.get("review") or {}
        if review.get("already_applied"):
            skipped.append({"event_name": mutation.get("event_name"), "reason": "already_applied"})
            continue
        blocked = review.get("block_apply_until_resolved")
        if blocked and not include_blocked:
            skipped.append(
                {
                    "event_name": mutation.get("event_name"),
                    "reason": "blocked_or_review_required",
                    "flags": review.get("flags") or [],
                }
            )
            continue
        selected.append(mutation)
    return selected, skipped


def apply_mutation(conn, mutation, now):
    if mutation.get("mutation_type") == MUTATION_TYPES["current_official"]:
        return apply_current_official(conn, mutation, now)
    if mutation.get("mutation_type") == MUTATION_TYPES["historical_reference"]:
        return apply_historical_reference(conn, mutation, now)
    raise ValueError(f"unsupported mutation_type: {mutation.get('mutation_type')}")


def run(args):
    validate_apply_request(args)
    plan = load_json(args.plan, {})
    selected, skipped = select_mutations(
        plan,
        event_name=args.event_name,
        include_blocked=args.include_blocked,
        mutation_type=args.mutation_type,
    )
    if args.apply and len(selected) != 1:
        raise ValueError(f"--apply requires exactly one selected mutation; selected={len(selected)}")
    target_db = Path(args.master_db if args.apply else args.out_db)
    backup_path = ""
    now = datetime.now(timezone.utc).isoformat()
    if not args.apply:
        copy_db(args.master_db, args.out_db)
    else:
        backup_path = str(backup_db(args.master_db, now))
    applied = []
    committed = False
    rolled_back = False
    with connect_existing(target_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        for mutation in selected:
            applied.append(apply_mutation(conn, mutation, now))
        issues = consistency_checks(conn, applied)
        summary_counts = {
            "event_occurrences": scalar(conn, "SELECT COUNT(*) FROM event_occurrences"),
            "occurrence_dates": scalar(conn, "SELECT COUNT(*) FROM occurrence_dates"),
            "notion_sync_jobs": scalar(conn, "SELECT COUNT(*) FROM notion_sync_jobs"),
            "ph2_event_occurrence_sync_jobs": scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM notion_sync_jobs
                WHERE requested_by = 'dry_run_ph2_event_occurrence_apply.py'
                """,
            ),
        }
        has_high_issue = any(row.get("severity") == "high" for row in issues)
        if args.apply and has_high_issue:
            conn.rollback()
            rolled_back = True
        else:
            conn.commit()
            committed = True

    result = {
        "generated_by": "dry_run_ph2_event_occurrence_apply.py",
        "generated_at": now,
        "scope": (
            "source_master_db_apply_no_notion_no_public_json"
            if args.apply
            else "copied_sqlite_only_no_notion_no_public_json"
        ),
        "sources": {
            "master_db": str(args.master_db),
            "plan": str(args.plan),
        },
        "outputs": {
            "target_db": str(target_db),
            "dry_run_db": "" if args.apply else str(args.out_db),
            "backup_db": backup_path,
        },
        "options": {
            "event_name": args.event_name,
            "include_blocked": args.include_blocked,
            "mutation_type": args.mutation_type,
            "apply": args.apply,
        },
        "write_guard": {
            "db_committed": committed,
            "rolled_back": rolled_back,
            "rollback_reason": "high_severity_issue" if rolled_back else "",
        },
        "summary": {
            "selected_count": len(selected),
            "applied_count": len(applied),
            "skipped_count": len(skipped),
            "issues_count": len(issues),
            "issues_by_severity": dict(Counter(row["severity"] for row in issues)),
            "dry_run_table_counts": summary_counts,
        },
        "applied": applied,
        "skipped": skipped,
        "issues": issues,
    }
    write_json(args.out_json, result)
    Path(args.out_md).write_text(render_markdown(result), encoding="utf-8")
    return result


def render_markdown(result):
    mode = "APPLY" if result["options"].get("apply") else "DRY-RUN"
    lines = [
        "# Ph2 event occurrence dry-run apply",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {mode}",
        f"- scope: {result['scope']}",
        f"- target_db: `{result['outputs']['target_db']}`",
        f"- dry_run_db: `{result['outputs']['dry_run_db']}`",
        f"- backup_db: `{result['outputs'].get('backup_db') or ''}`",
        f"- db_committed: {result.get('write_guard', {}).get('db_committed')}",
        f"- rolled_back: {result.get('write_guard', {}).get('rolled_back')}",
        f"- selected_count: {result['summary']['selected_count']}",
        f"- applied_count: {result['summary']['applied_count']}",
        f"- skipped_count: {result['summary']['skipped_count']}",
        f"- issues_count: {result['summary']['issues_count']}",
        f"- issues_by_severity: {result['summary']['issues_by_severity']}",
        f"- dry_run_table_counts: {result['summary']['dry_run_table_counts']}",
        "",
        "## Applied",
        "",
        "| event | action | before | after | inserted |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in result["applied"]:
        before = row["before"]
        after = row["after"]
        before_value = f"{before.get('date_start') or ''} to {before.get('date_end') or ''} / {before.get('venue_name') or ''}"
        after_value = f"{after.get('date_start') or ''} to {after.get('date_end') or ''} / {after.get('venue_name') or ''}"
        inserted = row.get("inserted_notion_sync_job_id") or row.get("inserted_occurrence_date_id") or ""
        lines.append(
            f"| {row['event_name']} | {row.get('action') or ''} | {before_value} | {after_value} | {inserted} |"
        )
    lines.extend(["", "## Skipped", ""])
    for row in result["skipped"][:40]:
        flags = row.get("flags") or ""
        suffix = f" {flags}" if flags else ""
        lines.append(f"- {row.get('event_name')}: {row.get('reason')}{suffix}")
    if result["issues"]:
        lines.extend(["", "## Issues", ""])
        for row in result["issues"]:
            lines.append(f"- {row['severity']} {row['issue_type']}: {row}")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-db", default=str(MASTER_DB))
    parser.add_argument("--plan", default=str(PLAN_JSON))
    parser.add_argument("--out-db", default=str(OUT_DB))
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    parser.add_argument("--event-name")
    parser.add_argument("--include-blocked", action="store_true")
    parser.add_argument("--mutation-type", choices=sorted(MUTATION_TYPES), default="current_official")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        result = run(args)
    except ValueError as exc:
        parser.error(str(exc))
    print(
        "ph2 dry-run apply: "
        f"applied={result['summary']['applied_count']} "
        f"skipped={result['summary']['skipped_count']} "
        f"issues={result['summary']['issues_count']} "
        f"dry_run_db={result['outputs']['dry_run_db']}"
    )
    return 1 if result["summary"]["issues_by_severity"].get("high") else 0


if __name__ == "__main__":
    raise SystemExit(main())
