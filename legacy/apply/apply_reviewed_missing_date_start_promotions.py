#!/usr/bin/env python3
"""Apply tightly reviewed date promotions for missing_date_start blockers.

Default mode writes to a copied SQLite DB. Apply mode updates only the reviewed
items in this file and does not write Notion or deploy public data.
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

from operation_safety.manual_apply_guards import MASTER_RDB_ONE_OFF_CONFIRMATION, require_confirmation
from master_db import MASTER_DB, MASTER_MANIFEST, connect_existing, refresh_manifest_database_state, stable_id


DATA = Path("data")
OUT_DB = DATA / "reviewed_missing_date_start_promotions_dry_run.sqlite"
OUT_JSON = DATA / "reviewed_missing_date_start_promotions_apply_report.json"
OUT_MD = DATA / "reviewed_missing_date_start_promotions_apply_report.md"
BACKUP_DIR = DATA / "backups"


PROMOTIONS = [
    {
        "occurrence_id": "occ_bf608105456f35f4",
        "event_name": "SHIBUYA MIYASHITA PARK BON DANCE",
        "date_start": "2026-09-26",
        "date_end": "2026-09-27",
        "date_status": "confirmed",
        "lifecycle_status": "published",
        "confidence": "high",
        "source_kind": "official_current_year",
        "source_url": "https://miyashita-bondance.jp/",
        "detail_note": "公式HPで2026年9月26日・27日、MIYASHITA PARK4階 渋谷区立宮下公園 芝生ひろば、13:00-21:00開催を確認。",
        "evidence_summary": "公式HPに2026年開催日・会場・時間・主催リンクあり。",
    },
    {
        "occurrence_id": "occ_ebe2be50bfd7b761",
        "event_name": "盆踊 〜BONDO〜",
        "date_start": "2026-05-23",
        "date_end": "",
        "date_status": "ended",
        "lifecycle_status": "published",
        "confidence": "high",
        "source_kind": "official_current_year",
        "source_url": "https://shinagawa-kanko.or.jp/event/bondo2026/",
        "detail_note": "しながわ観光協会で2026年5月23日、しながわ中央公園ヘリポート広場、10:20-18:30開催を確認。",
        "evidence_summary": "しながわ観光協会ページに2026年開催日・会場・時間・主催情報あり。",
    },
    {
        "occurrence_id": "occ_19b921bc4203d6e7",
        "event_name": "増上寺 地蔵尊盆踊り大会",
        "date_start": "2026-07-24",
        "date_end": "2026-07-25",
        "date_status": "confirmed",
        "lifecycle_status": "published",
        "confidence": "high",
        "source_kind": "official_current_year",
        "source_url": "https://www.zojoji.or.jp/event/ev_bonodori.html",
        "detail_note": "増上寺公式ページで2026年画像（ev_bonodori2026.jpg）と、7月24日（金）・25日（土）18:00-21:00、増上寺大殿前広場、主催 大本山増上寺・講中連合会・増上寺護持会を確認。",
        "evidence_summary": "増上寺公式ページに2026年開催日・会場・時間・主催情報あり。",
    },
]


def rows(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


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
               s.source_url AS series_source_url
        FROM event_occurrences o
        JOIN event_series s ON s.series_id = o.series_id
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE o.occurrence_id = ?
        """,
        (occurrence_id,),
    )
    return result[0] if result else None


def build_plan(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    planned: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in PROMOTIONS:
        before = occurrence(conn, item["occurrence_id"])
        if not before:
            skipped.append({**item, "skip_reason": "missing_occurrence"})
            continue
        if before["event_year"] != 2026:
            skipped.append({**item, "skip_reason": "unexpected_event_year", "before": before})
            continue
        if not before["venue_id"]:
            skipped.append({**item, "skip_reason": "missing_venue_id", "before": before})
            continue
        if before["venue_review_status"] != "active":
            skipped.append({**item, "skip_reason": "venue_not_active", "before": before})
            continue
        if (
            before["date_start"] == item["date_start"]
            and before["date_end"] == item["date_end"]
            and before["date_status"] == item["date_status"]
            and before["lifecycle_status"] == item["lifecycle_status"]
            and before["source_url"] == item["source_url"]
        ):
            skipped.append({**item, "skip_reason": "already_applied", "before": before})
            continue
        planned.append({**item, "before": before})
    return planned, skipped


def upsert_occurrence_date(conn: sqlite3.Connection, item: dict[str, Any], now: str) -> str:
    occurrence_date_id = stable_id(
        "odate",
        item["occurrence_id"],
        item["date_start"],
        item.get("date_end") or "",
        item["source_url"],
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
            item["occurrence_id"],
            item["date_start"],
            item.get("date_end") or "",
            item["date_status"],
            item.get("confidence") or "high",
            None,
            item.get("source_kind") or "official_current_year",
            now,
        ),
    )
    return occurrence_date_id


def apply_plan(conn: sqlite3.Connection, planned: list[dict[str, Any]], now: str) -> list[dict[str, Any]]:
    applied: list[dict[str, Any]] = []
    for item in planned:
        detail = item["before"].get("detail") or ""
        note = item.get("detail_note") or ""
        if note and note not in detail:
            detail = f"{detail}\n{note}".strip()

        conn.execute(
            """
            UPDATE event_occurrences
            SET date_start = ?,
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
                item["date_start"],
                item.get("date_end") or "",
                item["date_status"],
                item["lifecycle_status"],
                item.get("confidence") or "high",
                item.get("source_kind") or "official_current_year",
                item["source_url"],
                detail,
                now,
                item["occurrence_id"],
            ),
        )
        conn.execute(
            """
            UPDATE event_series
            SET source_url = ?,
                updated_at = ?
            WHERE series_id = ?
            """,
            (item["source_url"], now, item["before"]["series_id"]),
        )
        occurrence_date_id = upsert_occurrence_date(conn, item, now)
        applied.append({**item, "after": occurrence(conn, item["occurrence_id"]), "occurrence_date_id": occurrence_date_id})
    return applied


def rollback_checks(conn: sqlite3.Connection, applied: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_rows:
        issues.append(
            {
                "severity": "high",
                "issue_type": "foreign_key_check_failed",
                "sample": [tuple(row) for row in fk_rows[:10]],
            }
        )
    for item in applied:
        after = item["after"] or {}
        for field in ("date_start", "date_end", "date_status", "lifecycle_status", "source_kind", "source_url"):
            expected = item.get(field) or ""
            actual = after.get(field) or ""
            if actual != expected:
                issues.append(
                    {
                        "severity": "high",
                        "issue_type": "applied_value_mismatch",
                        "occurrence_id": item["occurrence_id"],
                        "field": field,
                        "expected": expected,
                        "actual": actual,
                    }
                )
    return issues


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Reviewed missing_date_start promotions",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- target_db: `{result['target_db']}`",
        f"- dry_run_db: `{result['dry_run_db']}`",
        f"- backup_db: `{result.get('backup_db') or ''}`",
        f"- db_committed: {result['db_committed']}",
        f"- applied_count: {result['summary']['applied_count']}",
        f"- skipped_count: {result['summary']['skipped_count']}",
        f"- high_issue_count: {result['summary']['high_issue_count']}",
        "",
        "| event | date | venue | source | status |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in result["applied"]:
        after = item.get("after") or {}
        date_text = item["date_start"] if not item.get("date_end") else f"{item['date_start']} to {item['date_end']}"
        lines.append(
            f"| {item['event_name']} | {date_text} | {after.get('venue_name') or ''} | {item['source_url']} | {item['date_status']} |"
        )
    if result["skipped"]:
        lines.extend(["", "## Skipped", "", "| event | reason |", "| --- | --- |"])
        for item in result["skipped"]:
            lines.append(f"| {item['event_name']} | {item.get('skip_reason') or ''} |")
    if result["issues"]:
        lines.extend(["", "## Issues", ""])
        for issue in result["issues"]:
            lines.append(f"- {issue}")
    lines.append("")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    target_db = args.master_db if args.apply else args.dry_run_db
    if not args.apply:
        copy_db(args.master_db, args.dry_run_db)
    backup_path = ""
    with connect_existing(target_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        planned, skipped = build_plan(conn)
        if args.apply and planned:
            backup_path = str(backup_db(args.master_db, now))
        applied = apply_plan(conn, planned, now)
        issues = rollback_checks(conn, applied)
        high_issue_count = sum(1 for issue in issues if issue.get("severity") == "high")
        db_committed = False
        if args.apply and applied and not high_issue_count:
            conn.commit()
            refresh_manifest_database_state(args.master_db, args.manifest, updated_at=now)
            db_committed = True
        elif args.apply:
            conn.rollback()
        else:
            conn.rollback()

    result = {
        "generated_by": "apply_reviewed_missing_date_start_promotions.py",
        "generated_at": now,
        "mode": "apply" if args.apply else "dry_run",
        "target_db": str(target_db),
        "dry_run_db": str(args.dry_run_db),
        "backup_db": backup_path,
        "db_committed": db_committed,
        "summary": {
            "planned_count": len(planned),
            "applied_count": len(applied) if (not args.apply or db_committed) else 0,
            "skipped_count": len(skipped),
            "high_issue_count": high_issue_count,
            "issues_by_type": dict(Counter(issue["issue_type"] for issue in issues)),
        },
        "applied": applied if (not args.apply or db_committed) else [],
        "skipped": skipped,
        "issues": issues,
    }
    write_json(args.out_json, result)
    args.out_md.write_text(render_markdown(result), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-db", type=Path, default=MASTER_DB)
    parser.add_argument("--manifest", type=Path, default=MASTER_MANIFEST)
    parser.add_argument("--dry-run-db", type=Path, default=OUT_DB)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        require_confirmation(
            args.apply,
            args.confirm,
            MASTER_RDB_ONE_OFF_CONFIRMATION,
            "Reviewed missing_date_start Master RDB update",
        )
    except ValueError as exc:
        parser.error(str(exc))
    result = run(args)
    print(
        "reviewed missing_date_start promotions: "
        f"mode={result['mode']} committed={result['db_committed']} "
        f"planned={result['summary']['planned_count']} applied={result['summary']['applied_count']} "
        f"skipped={result['summary']['skipped_count']} high_issues={result['summary']['high_issue_count']} "
        f"out={args.out_json}"
    )
    return 1 if result["summary"]["high_issue_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
