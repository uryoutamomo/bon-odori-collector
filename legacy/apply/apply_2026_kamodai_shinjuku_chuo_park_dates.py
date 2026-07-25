#!/usr/bin/env python3
"""Apply two reviewed 2026 date/venue fills that were blocking guard_public_events_sync.py.

Both events were flagged in a 2026-07-24 investigation
(memory: project_bon-odori-site-deploy-pipeline-path-bug) as RDB/site mismatches:
the public site already showed 2026 dates the RDB did not have. Web verification
against each event's own official page (Taisho University press release;
Shinjuku Central Park's own event listing) confirmed the site's dates were
correct all along -- the RDB was simply stale. This script brings the RDB up to
date rather than touching the site.

1. 鴨台盆踊り (Taisho University): the RDB only had a 2025 (第15回) occurrence.
   Adds a new 2026 (第16回) occurrence under the same series.
2. 新宿中央公園夏祭り 納涼盆踊り大会: a 2026 occurrence already existed but with
   date_status=unknown and no dates (its source_url pointed at a page describing
   the 2025 running of the event). Fills in the confirmed 2026 dates and source.

Default mode writes to a copied SQLite DB. Apply mode updates only the two
reviewed items in this file and does not write Notion or public JSON.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from master_rdb.master_db import MASTER_DB, normalize_text, refresh_manifest_database_state, stable_id, table_counts


DATA = Path("data")
OUT_DB = DATA / "kamodai_shinjuku_chuo_park_2026_dates_dry_run.sqlite"
OUT_JSON = DATA / "kamodai_shinjuku_chuo_park_2026_dates_apply_report.json"
OUT_MD = DATA / "kamodai_shinjuku_chuo_park_2026_dates_apply_report.md"
BACKUP_DIR = DATA / "backups"
CONFIRM = "APPLY 2026 KAMODAI SHINJUKU CHUO PARK DATES"


NEW_OCCURRENCE_FILLS = [
    {
        "kind": "insert",
        "series_id": "ser_a3a6304574b4feb5",
        "venue_id": "ven_d89cf9a462f6ab48",
        "event_year": 2026,
        "occurrence_sequence": 1,
        "display_name": "第16回 鴨台盆踊り",
        "date_start": "2026-07-10",
        "date_end": "2026-07-11",
        "date_status": "confirmed",
        "lifecycle_status": "published",
        "confidence": "confirmed",
        "source_kind": "official_current_year",
        "source_url": "https://www.tais.ac.jp/guide/latest_news/20260703/96605/",
        "detail_note": (
            "- 対象イベント: 第16回 鴨台盆踊り\n"
            "- 開催日: 2026-07-10〜2026-07-11\n"
            "- 会場: 大正大学\n"
            "- 根拠URL: https://www.tais.ac.jp/guide/latest_news/20260703/96605/\n"
            "- 判断: 大正大学公式プレスリリースで確認。創立100周年記念で「大正大学音頭」新曲披露予定。"
        ),
        "reason": (
            "guard_public_events_sync.pyがevent_key_mismatchでブロック中の1件。site側は既に"
            "2026-07-10確認済み表示だったが、RDBには2025年（第15回）分のoccurrenceしかなかった。"
            "大正大学公式プレスリリースで2026年開催日程を確認できたため、siteの表示に合わせてRDB側へ"
            "2026年occurrenceを追加する。"
        ),
    },
    {
        "kind": "update",
        "occurrence_id": "occ_99e2dd44bce470e3",
        "expected_event_year": 2026,
        "date_start": "2026-08-22",
        "date_end": "2026-08-23",
        "date_status": "confirmed",
        "lifecycle_status": "published",
        "confidence": "confirmed",
        "source_kind": "official_current_year",
        "source_url": "https://shinjukuchuo-park.jp/events/",
        "detail_note": (
            "- 開催日: 2026-08-22〜2026-08-23\n"
            "- 会場: 新宿中央公園 ファンモアタイム広場（旧水の広場）\n"
            "- 根拠URL: https://shinjukuchuo-park.jp/events/\n"
            "- 判断: 新宿中央公園公式サイトのイベント一覧ページで2026年日程を確認。"
            "旧source_urlは2025年開催を紹介する記事だったため差し替え。"
        ),
        "reason": (
            "guard_public_events_sync.pyがevent_key_mismatchでブロック中のもう1件。site側は既に"
            "2026-08-22確認済み表示だったが、RDBのoccurrenceはdate_status=unknown・日付未記入のままで、"
            "source_urlも2025年開催を紹介する記事を指していた。新宿中央公園公式サイトのイベント一覧で"
            "2026年日程を確認できたため、siteの表示に合わせてRDB側を確定させる。"
        ),
    },
]


def rows(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def scalar(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(query, params).fetchone()
    return row[0] if row else None


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
        SELECT o.occurrence_id, o.series_id, o.display_name, o.event_year, o.occurrence_sequence,
               o.venue_id, v.canonical_name AS venue_name, v.area AS venue_area,
               v.review_status AS venue_review_status, o.date_start, o.date_end,
               o.date_status, o.lifecycle_status, o.confidence, o.source_kind,
               o.source_url, o.detail, s.canonical_name AS series_name
        FROM event_occurrences o
        JOIN event_series s ON s.series_id = o.series_id
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE o.occurrence_id = ?
        """,
        (occurrence_id,),
    )
    return result[0] if result else None


def build_plan(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    planned: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []

    for item in NEW_OCCURRENCE_FILLS:
        if item["kind"] == "insert":
            existing = rows(
                conn,
                "SELECT occurrence_id FROM event_occurrences WHERE series_id = ? AND event_year = ? AND occurrence_sequence = ?",
                (item["series_id"], item["event_year"], item["occurrence_sequence"]),
            )
            venue = rows(conn, "SELECT venue_id, review_status FROM venues WHERE venue_id = ?", (item["venue_id"],))
            series = rows(conn, "SELECT series_id FROM event_series WHERE series_id = ?", (item["series_id"],))
            if not series:
                issues.append({"severity": "high", "issue_type": "missing_series", "series_id": item["series_id"]})
                skipped.append({**item, "skip_reason": "missing_series"})
                continue
            if not venue:
                issues.append({"severity": "high", "issue_type": "missing_venue", "venue_id": item["venue_id"]})
                skipped.append({**item, "skip_reason": "missing_venue"})
                continue
            if venue[0]["review_status"] != "active":
                issues.append({"severity": "high", "issue_type": "venue_not_active", "venue_id": item["venue_id"]})
                skipped.append({**item, "skip_reason": "venue_not_active"})
                continue
            if existing:
                skipped.append({**item, "skip_reason": "already_exists", "before": occurrence(conn, existing[0]["occurrence_id"])})
                continue
            planned.append({**item, "before": None})
        else:
            before = occurrence(conn, item["occurrence_id"])
            if not before:
                skipped.append({**item, "skip_reason": "missing_occurrence"})
                continue
            if before["event_year"] != item["expected_event_year"]:
                skipped.append({**item, "skip_reason": "unexpected_event_year", "before": before})
                continue
            if (
                before.get("date_start") == item["date_start"]
                and before.get("date_end") == item["date_end"]
                and before.get("date_status") == item["date_status"]
                and before.get("lifecycle_status") == item["lifecycle_status"]
                and before.get("source_url") == item["source_url"]
            ):
                skipped.append({**item, "skip_reason": "already_applied", "before": before})
                continue
            planned.append({**item, "before": before})

    return planned, skipped, issues


def apply_plan(conn: sqlite3.Connection, planned: list[dict[str, Any]], now: str) -> list[dict[str, Any]]:
    applied: list[dict[str, Any]] = []
    for item in planned:
        if item["kind"] == "insert":
            occurrence_id = stable_id("occ", item["series_id"], str(item["event_year"]), str(item["occurrence_sequence"]))
            conn.execute(
                """
                INSERT INTO event_occurrences(
                  occurrence_id, origin, series_id, event_year, occurrence_sequence, display_name,
                  venue_id, date_start, date_end, date_status, lifecycle_status, confidence,
                  source_kind, source_url, inherited_from_occurrence_id, public_intro_override,
                  detail, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    occurrence_id,
                    "curated",
                    item["series_id"],
                    item["event_year"],
                    item["occurrence_sequence"],
                    item["display_name"],
                    item["venue_id"],
                    item["date_start"],
                    item["date_end"],
                    item["date_status"],
                    item["lifecycle_status"],
                    item["confidence"],
                    item["source_kind"],
                    item["source_url"],
                    None,
                    None,
                    item["detail_note"],
                    now,
                    now,
                ),
            )
            occurrence_date_id = stable_id(
                "odate", occurrence_id, item["date_start"], item["date_end"], item["source_url"]
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
                    item["date_start"],
                    item["date_end"],
                    item["date_status"],
                    item["confidence"],
                    None,
                    item["source_kind"],
                    now,
                ),
            )
            after = occurrence(conn, occurrence_id)
            applied.append({**item, "occurrence_id": occurrence_id, "occurrence_date_id": occurrence_date_id, "after": after})
        else:
            detail = item["before"].get("detail") or ""
            note = item["detail_note"]
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
                    item["date_end"],
                    item["date_status"],
                    item["lifecycle_status"],
                    item["confidence"],
                    item["source_kind"],
                    item["source_url"],
                    detail,
                    now,
                    item["occurrence_id"],
                ),
            )
            occurrence_date_id = stable_id(
                "odate", item["occurrence_id"], item["date_start"], item["date_end"], item["source_url"]
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
                    item["date_end"],
                    item["date_status"],
                    item["confidence"],
                    None,
                    item["source_kind"],
                    now,
                ),
            )
            after = occurrence(conn, item["occurrence_id"])
            applied.append({**item, "occurrence_date_id": occurrence_date_id, "after": after})
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

    dup_rows = conn.execute(
        """
        SELECT series_id, event_year, occurrence_sequence, COUNT(*) c
        FROM event_occurrences GROUP BY series_id, event_year, occurrence_sequence HAVING c > 1
        """
    ).fetchall()
    if dup_rows:
        issues.append({"severity": "high", "issue_type": "duplicate_occurrence_key", "count": len(dup_rows)})

    for item in applied:
        after = item.get("after") or {}
        checks = {
            "venue_id": bool(after.get("venue_id")),
            "venue_active": after.get("venue_review_status") == "active",
            "date_start": after.get("date_start") == item["date_start"],
            "date_end": (after.get("date_end") or "") == (item.get("date_end") or ""),
            "date_status": after.get("date_status") == "confirmed",
            "lifecycle_status": after.get("lifecycle_status") == "published",
            "source_url": after.get("source_url") == item["source_url"],
        }
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            issues.append(
                {
                    "severity": "high",
                    "issue_type": "rollback_risk_publication_fields_incomplete",
                    "item": item.get("occurrence_id") or item.get("display_name"),
                    "failed_checks": failed,
                    "after": after,
                }
            )
    return issues


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# 2026 Kamodai / Shinjuku Chuo Park date fills apply report",
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
        "| event | kind | after | date | source |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in result["applied"]:
        after = item.get("after") or {}
        lines.append(
            "| {event} | {kind} | {status} | {date_start} to {date_end} | {source} |".format(
                event=item.get("display_name") or item.get("occurrence_id") or "",
                kind=item["kind"],
                status=f"{after.get('date_status')}/{after.get('lifecycle_status')}",
                date_start=after.get("date_start") or "",
                date_end=after.get("date_end") or "",
                source=after.get("source_url") or "",
            )
        )
    if result["skipped"]:
        lines.extend(["", "## Skipped", "", "| event | reason |", "| --- | --- |"])
        for item in result["skipped"]:
            lines.append(f"| {item.get('display_name') or item.get('occurrence_id') or ''} | {item.get('skip_reason') or ''} |")
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

    with closing(sqlite3.connect(working_db)) as conn:
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
        "generated_by": "apply_2026_kamodai_shinjuku_chuo_park_dates.py",
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
        "2026 kamodai/shinjuku chuo park date fills: "
        f"mode={mode} applied={len(applied)} skipped={len(skipped)} "
        f"issues={dict(issue_counts)} committed={db_committed} report={OUT_JSON}"
    )


if __name__ == "__main__":
    main()
