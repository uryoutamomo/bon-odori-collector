#!/usr/bin/env python3
"""Apply tightly reviewed official-wait event fills.

Default mode writes to a copied SQLite DB. Apply mode updates only the reviewed
items in this file and does not write Notion or public JSON.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from master_db import MASTER_DB, normalize_text, refresh_manifest_database_state, stable_id, table_counts


DATA = Path("data")
OUT_DB = DATA / "reviewed_official_wait_events_dry_run.sqlite"
OUT_JSON = DATA / "reviewed_official_wait_events_apply_report.json"
OUT_MD = DATA / "reviewed_official_wait_events_apply_report.md"
BACKUP_DIR = DATA / "backups"
CONFIRM = "APPLY REVIEWED OFFICIAL WAIT EVENTS"


OFFICIAL_WAIT_EVENT_FILLS = [
    {
        "occurrence_id": "occ_69eb62d9b1773ad9",
        "old_event_name": "鉄砲洲児童公園 盆踊り",
        "event_name": "鉄砲洲納涼盆踊り",
        "venue": {
            "canonical_name": "鉄砲洲公園",
            "area": "中央区",
            "address": "",
            "access": "",
            "source_url": "https://x.com/iri2choukai/status/2069959259895496872",
            "aliases": ["鉄砲洲児童公園"],
        },
        "occurrence_update": {
            "date_start": "2026-08-03",
            "date_end": "2026-08-05",
            "date_status": "confirmed",
            "lifecycle_status": "published",
            "confidence": "high",
            "source_kind": "official_current_year",
            "source_url": "https://x.com/iri2choukai/status/2069959259895496872",
            "detail_note": "入船二丁目町会の公式/町会広報X投稿で、2026年8月3日から8月5日、鉄砲洲公園、18:45-21:00の開催を確認。",
        },
        "evidence": {
            "review_file": "data/rare_signal_backcheck_reviews.json",
            "official_account_file": "data/x_official_source_accounts.json",
            "confirmed_source_url": "https://x.com/iri2choukai/status/2069959259895496872",
            "confirmed_source_type": "official_or_organizer_social",
            "reviewed_by": "おと（Codex）",
        },
        "reason": "レビュー済みの町会公式/広報X根拠で、名称・日付・会場が揃っているため、候補へ戻らないようRDBの必須公開条件をまとめて反映する。",
    },
]


def rows(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def scalar(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(query, params).fetchone()
    return row[0] if row else None


def read_json(path: Path, default: Any) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_db(source: Path, out_db: Path) -> None:
    out_db.parent.mkdir(parents=True, exist_ok=True)
    if out_db.exists():
        out_db.unlink()
    shutil.copy2(source, out_db)


def backup_db(source: Path, now: str) -> Path:
    stamp = now.replace("-", "").replace(":", "").replace("+00:00", "Z")
    backup = BACKUP_DIR / f"{source.stem}.{stamp}{source.suffix}.bak"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup)
    return backup


def occurrence(conn: sqlite3.Connection, occurrence_id: str) -> dict[str, Any] | None:
    result = rows(
        conn,
        """
        SELECT o.occurrence_id, o.series_id, o.display_name, o.event_year,
               o.venue_id, v.canonical_name AS venue_name, v.area AS venue_area,
               v.review_status AS venue_review_status, o.date_start, o.date_end,
               o.date_status, o.lifecycle_status, o.confidence, o.source_kind,
               o.source_url, o.detail, s.canonical_name AS series_name,
               s.normalized_name AS series_normalized_name, s.usual_venue_id,
               s.area AS series_area, s.source_url AS series_source_url
        FROM event_occurrences o
        JOIN event_series s ON s.series_id = o.series_id
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE o.occurrence_id = ?
        """,
        (occurrence_id,),
    )
    return result[0] if result else None


def find_venue(conn: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any] | None:
    result = rows(
        conn,
        """
        SELECT venue_id, canonical_name, area, address, access, source_url, review_status
        FROM venues
        WHERE normalized_name = ?
          AND COALESCE(address, '') = ?
        """,
        (normalize_text(data["canonical_name"]), data.get("address") or ""),
    )
    return result[0] if result else None


def validate_evidence(item: dict[str, Any]) -> list[dict[str, str]]:
    evidence = item["evidence"]
    source_url = evidence["confirmed_source_url"]
    issues: list[dict[str, str]] = []

    review_payload = read_json(Path(evidence["review_file"]), {})
    reviews = review_payload.get("reviews") if isinstance(review_payload, dict) else review_payload
    if not isinstance(reviews, list):
        reviews = []
    matching_reviews = [
        row
        for row in reviews
        if isinstance(row, dict)
        and row.get("decision") == "confirm"
        and source_url in (row.get("confirmed_source_urls") or [])
        and row.get("confirmed_source_type") == evidence["confirmed_source_type"]
    ]
    if not matching_reviews:
        issues.append(
            {
                "severity": "high",
                "issue_type": "reviewed_evidence_not_found",
                "source_url": source_url,
            }
        )

    account_payload = read_json(Path(evidence["official_account_file"]), {})
    accounts = account_payload.get("accounts") if isinstance(account_payload, dict) else account_payload
    if not isinstance(accounts, list):
        accounts = []
    matching_accounts = [
        row
        for row in accounts
        if isinstance(row, dict)
        and row.get("trust_level") == "organizer_official"
        and "iri2choukai"
        in " ".join(
            [
                str(row.get("handle") or ""),
                str(row.get("evidence_url") or ""),
                str(row.get("account") or ""),
                str(row.get("url") or ""),
            ]
        )
    ]
    if not matching_accounts:
        issues.append(
            {
                "severity": "high",
                "issue_type": "official_social_account_not_registered",
                "source_url": source_url,
            }
        )

    return issues


def build_plan(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    planned: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []

    for item in OFFICIAL_WAIT_EVENT_FILLS:
        before = occurrence(conn, item["occurrence_id"])
        if not before:
            skipped.append({**item, "skip_reason": "missing_occurrence"})
            continue
        if before["event_year"] != 2026:
            skipped.append({**item, "skip_reason": "unexpected_event_year", "before": before})
            continue
        issues.extend(validate_evidence(item))
        expected = item["occurrence_update"]
        if (
            before.get("display_name") == item["event_name"]
            and before.get("venue_name") == item["venue"]["canonical_name"]
            and before.get("date_start") == expected["date_start"]
            and before.get("date_status") == expected["date_status"]
            and before.get("lifecycle_status") == expected["lifecycle_status"]
        ):
            skipped.append({**item, "skip_reason": "already_applied", "before": before})
            continue
        planned.append({**item, "before": before})

    if any(issue["severity"] == "high" for issue in issues):
        skipped.extend({**item, "skip_reason": "evidence_validation_failed"} for item in planned)
        planned = []

    return planned, skipped, issues


def ensure_venue(conn: sqlite3.Connection, data: dict[str, Any], now: str) -> tuple[str, bool]:
    existing = find_venue(conn, data)
    if existing:
        venue_id = existing["venue_id"]
        conn.execute(
            """
            UPDATE venues
            SET area = ?,
                access = COALESCE(NULLIF(?, ''), access),
                source_url = COALESCE(NULLIF(?, ''), source_url),
                review_status = 'active',
                updated_at = ?
            WHERE venue_id = ?
            """,
            (
                data.get("area") or "",
                data.get("access") or "",
                data.get("source_url") or "",
                now,
                venue_id,
            ),
        )
        created = False
    else:
        venue_id = stable_id("ven", data["canonical_name"], data.get("address") or "", data.get("source_url") or "")
        conn.execute(
            """
            INSERT INTO venues(
              venue_id, origin, canonical_name, normalized_name, area, address,
              access, scale, public_intro, past_memo, source_url,
              latitude, longitude, review_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                venue_id,
                "curated",
                data["canonical_name"],
                normalize_text(data["canonical_name"]),
                data.get("area") or "",
                data.get("address") or "",
                data.get("access") or "",
                "",
                "",
                "",
                data.get("source_url") or "",
                None,
                None,
                "active",
                now,
                now,
            ),
        )
        created = True

    aliases = [data["canonical_name"], *data.get("aliases", [])]
    for alias in aliases:
        conn.execute(
            """
            INSERT OR IGNORE INTO venue_aliases(
              venue_id, alias, normalized_alias, source, confidence
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (venue_id, alias, normalize_text(alias), "reviewed_official_wait_event", "manual"),
        )
    return venue_id, created


def upsert_occurrence_date(conn: sqlite3.Connection, occurrence_id: str, update: dict[str, str], now: str) -> str:
    occurrence_date_id = stable_id(
        "odate",
        occurrence_id,
        update["date_start"],
        update.get("date_end") or "",
        update["source_url"],
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO occurrence_dates(
          occurrence_date_id, occurrence_id, date_start, date_end, date_type,
          confidence, source_evidence_id, basis, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            occurrence_date_id,
            occurrence_id,
            update["date_start"],
            update.get("date_end") or "",
            update["date_status"],
            update.get("confidence") or "high",
            None,
            update.get("source_kind") or "official_current_year",
            now,
        ),
    )
    return occurrence_date_id


def apply_plan(conn: sqlite3.Connection, planned: list[dict[str, Any]], now: str) -> list[dict[str, Any]]:
    applied: list[dict[str, Any]] = []
    for item in planned:
        venue_id, venue_created = ensure_venue(conn, item["venue"], now)
        update = item["occurrence_update"]
        detail = item["before"].get("detail") or ""
        note = update.get("detail_note") or ""
        if note and note not in detail:
            detail = f"{detail}\n{note}".strip()

        conn.execute(
            """
            UPDATE event_occurrences
            SET display_name = ?,
                venue_id = ?,
                date_start = ?,
                date_end = ?,
                date_status = ?,
                lifecycle_status = ?,
                confidence = ?,
                source_kind = ?,
                source_url = ?,
                detail = ?,
                updated_at = ?
            WHERE occurrence_id = ?
            """,
            (
                item["event_name"],
                venue_id,
                update["date_start"],
                update.get("date_end") or "",
                update["date_status"],
                update["lifecycle_status"],
                update.get("confidence") or "high",
                update.get("source_kind") or "official_current_year",
                update["source_url"],
                detail,
                now,
                item["occurrence_id"],
            ),
        )

        conn.execute(
            """
            UPDATE event_series
            SET canonical_name = ?,
                normalized_name = ?,
                usual_venue_id = ?,
                area = ?,
                source_url = ?,
                updated_at = ?
            WHERE series_id = ?
            """,
            (
                item["event_name"],
                normalize_text(item["event_name"]),
                venue_id,
                item["venue"].get("area") or "",
                update["source_url"],
                now,
                item["before"]["series_id"],
            ),
        )

        occurrence_date_id = upsert_occurrence_date(conn, item["occurrence_id"], update, now)
        after = occurrence(conn, item["occurrence_id"])
        applied.append(
            {
                **item,
                "new_venue_id": venue_id,
                "venue_created": venue_created,
                "occurrence_date_id": occurrence_date_id,
                "after": after,
            }
        )
    return applied


def rollback_checks(conn: sqlite3.Connection, applied: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
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
        after = item.get("after") or {}
        expected = item["occurrence_update"]
        checks = {
            "display_name": after.get("display_name") == item["event_name"],
            "venue_id": bool(after.get("venue_id")),
            "venue_active": after.get("venue_review_status") == "active",
            "venue_area": after.get("venue_area") == item["venue"].get("area"),
            "date_start": after.get("date_start") == expected["date_start"],
            "date_end": (after.get("date_end") or "") == (expected.get("date_end") or ""),
            "date_status": after.get("date_status") == "confirmed",
            "lifecycle_status": after.get("lifecycle_status") == "published",
            "source_url": after.get("source_url") == expected["source_url"],
            "series_name": after.get("series_name") == item["event_name"],
            "series_usual_venue": after.get("usual_venue_id") == after.get("venue_id"),
        }
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            issues.append(
                {
                    "severity": "high",
                    "issue_type": "rollback_risk_publication_fields_incomplete",
                    "occurrence_id": item["occurrence_id"],
                    "failed_checks": failed,
                    "after": after,
                }
            )
    return issues


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Reviewed official-wait events apply report",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- target_db: `{result['outputs']['target_db']}`",
        f"- dry_run_db: `{result['outputs']['dry_run_db']}`",
        f"- backup_db: `{result['outputs']['backup_db']}`",
        f"- db_committed: {result['write_guard']['db_committed']}",
        f"- rolled_back: {result['write_guard']['rolled_back']}",
        f"- applied_count: {result['summary']['applied_count']}",
        f"- skipped_count: {result['summary']['skipped_count']}",
        f"- issues_by_severity: {result['summary']['issues_by_severity']}",
        "",
        "| event | before | after | venue | date | source |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in result["applied"]:
        before = item.get("before") or {}
        after = item.get("after") or {}
        lines.append(
            "| {event} | {before_name} / {before_date} / {before_venue} | {after_name} / {after_status} | {venue} | {date_start} to {date_end} | {source} |".format(
                event=item["event_name"],
                before_name=before.get("display_name") or "",
                before_date=before.get("date_start") or "missing_date",
                before_venue=before.get("venue_name") or "missing_venue",
                after_name=after.get("display_name") or "",
                after_status=f"{after.get('date_status')}/{after.get('lifecycle_status')}",
                venue=after.get("venue_name") or "",
                date_start=after.get("date_start") or "",
                date_end=after.get("date_end") or "",
                source=after.get("source_url") or "",
            )
        )
    if result["skipped"]:
        lines.extend(["", "## Skipped", "", "| event | reason |", "| --- | --- |"])
        for item in result["skipped"]:
            lines.append(f"| {item.get('event_name') or item.get('old_event_name') or ''} | {item.get('skip_reason') or ''} |")
    if result["issues"]:
        lines.extend(["", "## Issues", "", "```json", json.dumps(result["issues"], ensure_ascii=False, indent=2), "```"])
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write to the master DB instead of a copied dry-run DB")
    parser.add_argument("--confirm", default="", help=f"required with --apply: {CONFIRM}")
    parser.add_argument("--master-db", type=Path, default=MASTER_DB)
    parser.add_argument("--dry-run-db", type=Path, default=OUT_DB)
    args = parser.parse_args()

    now = datetime.now(timezone.utc).isoformat()
    mode = "apply" if args.apply else "dry_run"
    target_db = args.master_db
    dry_run_db = args.dry_run_db
    backup = ""

    if args.apply:
        if args.confirm != CONFIRM:
            raise SystemExit(f"--apply requires --confirm {CONFIRM!r}")
        backup = str(backup_db(target_db, now))
        working_db = target_db
    else:
        copy_db(target_db, dry_run_db)
        working_db = dry_run_db

    with sqlite3.connect(working_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        before_counts = table_counts(conn)
        planned, skipped, plan_issues = build_plan(conn)
        applied: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = list(plan_issues)
        if not any(issue["severity"] == "high" for issue in issues):
            applied = apply_plan(conn, planned, now)
            issues.extend(rollback_checks(conn, applied))
        if issues:
            conn.rollback()
            rolled_back = True
            db_committed = False
        else:
            conn.commit()
            rolled_back = False
            db_committed = True
            if args.apply:
                refresh_manifest_database_state(working_db, updated_at=now)
        after_counts = table_counts(conn)

    issue_counts = Counter(issue.get("severity", "unknown") for issue in issues)
    result = {
        "generated_at": now,
        "generated_by": "apply_reviewed_official_wait_events.py",
        "mode": mode,
        "outputs": {
            "target_db": str(target_db),
            "dry_run_db": str(dry_run_db),
            "backup_db": backup,
            "json": str(OUT_JSON),
            "markdown": str(OUT_MD),
        },
        "write_guard": {
            "db_committed": db_committed,
            "rolled_back": rolled_back,
            "apply_requires_confirm": CONFIRM,
        },
        "summary": {
            "planned_count": len(planned),
            "applied_count": len(applied),
            "skipped_count": len(skipped),
            "issues_by_severity": dict(issue_counts),
            "before_counts": before_counts,
            "after_counts": after_counts,
        },
        "applied": applied,
        "skipped": skipped,
        "issues": issues,
    }
    write_json(OUT_JSON, result)
    OUT_MD.write_text(render_markdown(result), encoding="utf-8")
    print(
        "reviewed official-wait events: "
        f"mode={mode} applied={len(applied)} skipped={len(skipped)} "
        f"issues={dict(issue_counts)} committed={db_committed} report={OUT_JSON}"
    )


if __name__ == "__main__":
    main()
