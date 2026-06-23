"""Apply reviewed historical reference dates to the master RDB.

Default mode writes to a copied SQLite DB. Apply mode only inserts
occurrence_dates rows with date_type='historical_reference'; it never changes
the event occurrence date cache, Notion, or public JSON.
"""

import argparse
import json
import shutil
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from master_db import MASTER_DB, connect_existing, refresh_manifest_database_state, stable_id, table_counts


DATA = Path("data")
REVIEW_JSON = DATA / "historical_promotion_candidate_review.json"
OUT_DB = DATA / "reviewed_historical_references_dry_run.sqlite"
DRY_RUN_JSON = DATA / "reviewed_historical_references_dry_run_report.json"
DRY_RUN_MD = DATA / "reviewed_historical_references_dry_run_report.md"
APPLY_JSON = DATA / "reviewed_historical_references_apply_report.json"
APPLY_MD = DATA / "reviewed_historical_references_apply_report.md"
BACKUP_DIR = DATA / "backups"
CONFIRM = "APPLY REVIEWED HISTORICAL REFERENCES"


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rows(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def scalar(conn, query, params=()):
    return conn.execute(query, params).fetchone()[0]


def copy_db(source, out_db):
    source = Path(source)
    out_db = Path(out_db)
    out_db.parent.mkdir(parents=True, exist_ok=True)
    if out_db.exists():
        out_db.unlink()
    shutil.copy2(source, out_db)


def backup_db(source, now):
    source = Path(source)
    stamp = now.replace("-", "").replace(":", "").replace("+00:00", "Z")
    backup = BACKUP_DIR / f"{source.stem}.{stamp}{source.suffix}.bak"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup)
    return backup


def occurrence(conn, occurrence_id):
    result = rows(
        conn,
        """
        SELECT o.occurrence_id, o.display_name, o.event_year, o.date_start,
               o.date_end, o.date_status, o.venue_id, v.canonical_name AS venue
        FROM event_occurrences o
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE o.occurrence_id = ?
        """,
        (occurrence_id,),
    )
    return result[0] if result else None


def reviewed_candidates(review):
    return [
        item
        for item in review.get("review") or []
        if item.get("review_action") == "ready_to_insert_historical_reference"
    ]


def date_range_for_year(exact_dates, year):
    values = sorted(exact_dates.get(str(year)) or [])
    if not values:
        return "", ""
    start = values[0]
    end = values[-1] if len(values) > 1 else ""
    return start, end


def build_insert_rows(conn, review):
    candidates = reviewed_candidates(review)
    planned = []
    skipped = []
    for candidate in candidates:
        target = occurrence(conn, candidate["target_occurrence_id"])
        if not target:
            skipped.append(
                {
                    "event_name": candidate["event_name"],
                    "target_occurrence_id": candidate["target_occurrence_id"],
                    "reason": "missing_target_occurrence",
                }
            )
            continue
        target_year = int(target["event_year"])
        for year in candidate.get("historical_years") or []:
            if int(year) >= target_year:
                skipped.append(
                    {
                        "event_name": candidate["event_name"],
                        "target_occurrence_id": candidate["target_occurrence_id"],
                        "year": year,
                        "reason": "not_before_target_occurrence_year",
                    }
                )
                continue
            date_start, date_end = date_range_for_year(candidate.get("exact_dates") or {}, year)
            if not date_start:
                skipped.append(
                    {
                        "event_name": candidate["event_name"],
                        "target_occurrence_id": candidate["target_occurrence_id"],
                        "year": year,
                        "reason": "no_exact_date_for_year",
                    }
                )
                continue
            occurrence_date_id = stable_id(
                "odate",
                "reviewed_historical_reference",
                candidate["target_occurrence_id"],
                str(year),
                date_start,
                date_end,
            )
            existing_count = scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM occurrence_dates
                WHERE occurrence_id = ?
                  AND date_start = ?
                  AND COALESCE(date_end, '') = ?
                  AND date_type = 'historical_reference'
                """,
                (candidate["target_occurrence_id"], date_start, date_end),
            )
            if existing_count:
                skipped.append(
                    {
                        "event_name": candidate["event_name"],
                        "target_occurrence_id": candidate["target_occurrence_id"],
                        "year": year,
                        "date_start": date_start,
                        "date_end": date_end,
                        "reason": "historical_reference_already_exists",
                    }
                )
                continue
            planned.append(
                {
                    "occurrence_date_id": occurrence_date_id,
                    "occurrence_id": candidate["target_occurrence_id"],
                    "event_name": candidate["event_name"],
                    "target_occurrence_year": target_year,
                    "historical_year": int(year),
                    "date_start": date_start,
                    "date_end": date_end,
                    "confidence": candidate.get("promotion_confidence") or "unknown",
                    "venue": candidate.get("venue") or target.get("venue") or "",
                    "evidence_url_count": candidate.get("evidence_url_count") or 0,
                    "basis": {
                        "source": "reviewed_historical_promotion_candidate",
                        "candidate_id": candidate.get("candidate_id") or "",
                        "event_name": candidate["event_name"],
                        "target_occurrence_id": candidate["target_occurrence_id"],
                        "target_occurrence_year": target_year,
                        "historical_year": int(year),
                        "historical_venue_name": candidate.get("venue") or "",
                        "historical_years": candidate.get("historical_years") or [],
                        "exact_dates": candidate.get("exact_dates") or {},
                        "evidence_url_count": candidate.get("evidence_url_count") or 0,
                        "does_not_confirm_target_year": True,
                    },
                }
            )
    return planned, skipped


def apply_rows(conn, planned, now):
    for item in planned:
        conn.execute(
            """
            INSERT INTO occurrence_dates(
              occurrence_date_id, occurrence_id, date_start, date_end, date_type,
              confidence, basis, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["occurrence_date_id"],
                item["occurrence_id"],
                item["date_start"],
                item["date_end"] or None,
                "historical_reference",
                item["confidence"],
                json.dumps(item["basis"], ensure_ascii=False, sort_keys=True),
                now,
            ),
        )


def consistency_checks(conn, planned):
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
    duplicate_rows = rows(
        conn,
        """
        SELECT occurrence_id, date_start, COALESCE(date_end, '') AS date_end,
               date_type, COUNT(*) AS c
        FROM occurrence_dates
        GROUP BY occurrence_id, date_start, COALESCE(date_end, ''), date_type
        HAVING c > 1
        """,
    )
    if duplicate_rows:
        issues.append(
            {
                "severity": "high",
                "issue_type": "duplicate_occurrence_dates",
                "rows": duplicate_rows[:20],
                "count": len(duplicate_rows),
            }
        )
    planned_ids = {item["occurrence_id"] for item in planned}
    for occurrence_id in planned_ids:
        target = occurrence(conn, occurrence_id)
        latest_cache = rows(
            conn,
            """
            SELECT date_start, COALESCE(date_end, '') AS date_end, date_type
            FROM occurrence_dates
            WHERE occurrence_id = ?
              AND date_type IN ('confirmed', 'ended', 'predicted')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (occurrence_id,),
        )
        if not target or not latest_cache:
            continue
        latest = latest_cache[0]
        if (
            target.get("date_start") != latest["date_start"]
            or (target.get("date_end") or "") != latest["date_end"]
            or target.get("date_status") != latest["date_type"]
        ):
            issues.append(
                {
                    "severity": "high",
                    "issue_type": "date_cache_changed_or_mismatched",
                    "occurrence_id": occurrence_id,
                    "target": target,
                    "latest_non_historical_date": latest,
                }
            )
    return issues


def render_markdown(result):
    lines = [
        "# Reviewed historical references apply report",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- target_db: `{result['outputs']['target_db']}`",
        f"- dry_run_db: `{result['outputs']['dry_run_db']}`",
        f"- backup_db: `{result['outputs']['backup_db']}`",
        f"- db_committed: {result['write_guard']['db_committed']}",
        f"- rolled_back: {result['write_guard']['rolled_back']}",
        f"- planned_count: {result['summary']['planned_count']}",
        f"- inserted_count: {result['summary']['inserted_count']}",
        f"- skipped_count: {result['summary']['skipped_count']}",
        f"- issues_by_severity: {result['summary']['issues_by_severity']}",
        f"- date_type_counts: {result['summary']['date_type_counts']}",
        "",
        "| event | target year | historical year | date | venue |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    for item in result["inserted"]:
        date_value = item["date_start"]
        if item.get("date_end") and item["date_end"] != item["date_start"]:
            date_value = f"{item['date_start']} to {item['date_end']}"
        lines.append(
            f"| {item['event_name']} | {item['target_occurrence_year']} | "
            f"{item['historical_year']} | {date_value} | {item['venue']} |"
        )
    if result["skipped"]:
        lines.extend(["", "## Skipped", ""])
        for item in result["skipped"]:
            lines.append(f"- {item.get('event_name')}: {item.get('year', '')} {item.get('reason')}")
    if result["issues"]:
        lines.extend(["", "## Issues", ""])
        for issue in result["issues"]:
            lines.append(f"- {issue['severity']} {issue['issue_type']}: {issue}")
    lines.append("")
    return "\n".join(lines)


def validate_apply(args):
    if not args.apply:
        return
    if args.confirm != CONFIRM:
        raise ValueError(f"--apply requires --confirm '{CONFIRM}'")
    if Path(args.out_db) == Path(args.master_db):
        raise ValueError("--out-db must not equal --master-db")


def run(args):
    validate_apply(args)
    now = datetime.now(timezone.utc).isoformat()
    review = load_json(args.review_json, {})
    target_db = Path(args.master_db if args.apply else args.out_db)
    backup = ""
    if args.apply:
        backup = str(backup_db(args.master_db, now))
    else:
        copy_db(args.master_db, args.out_db)

    with connect_existing(target_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        planned, skipped = build_insert_rows(conn, review)
        apply_rows(conn, planned, now)
        issues = consistency_checks(conn, planned)
        has_high_issue = any(issue.get("severity") == "high" for issue in issues)
        if args.apply and has_high_issue:
            conn.rollback()
            committed = False
            rolled_back = True
        else:
            conn.commit()
            committed = True
            rolled_back = False
        date_type_counts = {
            row["date_type"]: row["c"]
            for row in rows(conn, "SELECT date_type, COUNT(*) AS c FROM occurrence_dates GROUP BY date_type")
        }
        counts = table_counts(conn)
    if args.apply and committed:
        refresh_manifest_database_state(args.master_db, updated_at=now)

    result = {
        "generated_by": "apply_reviewed_historical_references.py",
        "generated_at": now,
        "mode": "apply" if args.apply else "dry_run",
        "scope": (
            "source_master_db_apply_no_notion_no_public_json"
            if args.apply
            else "copied_sqlite_only_no_notion_no_public_json"
        ),
        "sources": {
            "master_db": str(args.master_db),
            "review_json": str(args.review_json),
        },
        "outputs": {
            "target_db": str(target_db),
            "dry_run_db": "" if args.apply else str(args.out_db),
            "backup_db": backup,
        },
        "write_guard": {
            "db_committed": committed,
            "rolled_back": rolled_back,
            "rollback_reason": "high_severity_issue" if rolled_back else "",
        },
        "summary": {
            "planned_count": len(planned),
            "inserted_count": len(planned) if committed else 0,
            "skipped_count": len(skipped),
            "issues_count": len(issues),
            "issues_by_severity": dict(Counter(issue["severity"] for issue in issues)),
            "date_type_counts": date_type_counts,
            "table_counts": counts,
        },
        "inserted": planned if committed else [],
        "skipped": skipped,
        "issues": issues,
    }
    write_json(args.out_json, result)
    Path(args.out_md).write_text(render_markdown(result), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-db", type=Path, default=MASTER_DB)
    parser.add_argument("--review-json", type=Path, default=REVIEW_JSON)
    parser.add_argument("--out-db", type=Path, default=OUT_DB)
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--out-md", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    if args.out_json is None:
        args.out_json = APPLY_JSON if args.apply else DRY_RUN_JSON
    if args.out_md is None:
        args.out_md = APPLY_MD if args.apply else DRY_RUN_MD
    try:
        result = run(args)
    except ValueError as exc:
        parser.error(str(exc))
    print(
        "reviewed historical references: "
        f"mode={result['mode']} "
        f"inserted={result['summary']['inserted_count']} "
        f"skipped={result['summary']['skipped_count']} "
        f"issues={result['summary']['issues_by_severity']}"
    )
    return 1 if result["summary"]["issues_by_severity"].get("high") else 0


if __name__ == "__main__":
    raise SystemExit(main())
