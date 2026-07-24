#!/usr/bin/env python3
"""Reconcile two event_occurrences.detail/source_url fields that had drifted from
site's already-published (2026-07-21 ad-hoc review) text.

Both surfaced as individual_review diffs in guard_public_events_sync.py while
deploying today's (2026-07-24) song-evidence sync. Investigation showed the RDB
was the stale side for these two: site's 2026-07-21 review had already upgraded
each to a more specific/authoritative source_url than what the RDB still had,
but that upgrade was never written back to the RDB (see
project_bon-odori-site-deploy-pipeline-path-bug memory's recurring "site ad-hoc
patch never fed back" pattern -- this is a second instance of it, this time for
detail/source_url rather than dates).

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

from master_rdb.master_db import MASTER_DB, refresh_manifest_database_state, table_counts


DATA = Path("data")
OUT_DB = DATA / "detail_source_reconciliation_20260724_dry_run.sqlite"
OUT_JSON = DATA / "detail_source_reconciliation_20260724_apply_report.json"
OUT_MD = DATA / "detail_source_reconciliation_20260724_apply_report.md"
BACKUP_DIR = DATA / "backups"
CONFIRM = "APPLY DETAIL SOURCE RECONCILIATION 20260724"


RECONCILIATIONS = [
    {
        "occurrence_id": "occ_99e2dd44bce470e3",
        "expected_event_year": 2026,
        "new_detail": (
            "2025年は8/23-24。主催：盆踊り＝角筈地区青少年育成委員会／夏まつり＝パークアップ共同体。"
            "[p0_review_20260721] 新宿中央公園公式ページで2026年開催日・会場・盆踊り主催者を確認。"
        ),
        "new_source_url": (
            "https://shinjukuchuo-park.jp/events/event/2026/07/03/"
            "%E6%96%B0%E5%AE%BF%E4%B8%AD%E5%A4%AE%E5%85%AC%E5%9C%92%E3%80%80"
            "%E5%A4%8F%E3%81%BE%E3%81%A4%E3%82%8A%EF%BD%9E%E7%9B%86%E8%B8%8A%E3%82%8A"
            "%E3%81%A8%E5%90%8C%E6%99%82%E9%96%8B%E5%82%AC%EF%BD%9E-2/"
        ),
        "reason": (
            "RDBのsource_urlは汎用イベント一覧ページ(/events/)、detailには古い"
            "「2026年日程は未発表」が残ったままだった(今日の2026-08-22/23確定適用より前の文言)。"
            "siteは2026-07-21レビューで個別イベントページの具体URLへ既に更新済み。"
            "siteの方を正としてRDBへ反映する。"
        ),
    },
    {
        "occurrence_id": "occ_0240108c92fd793b",
        "expected_event_year": 2026,
        "new_detail": (
            "2026年イベント掲載で、2026年7月18日(土)〜20日(月祝)18:00〜21:00、"
            "会場: 自由が丘駅前ロータリー 特設会場、主催: 自由が丘商店街振興組合、"
            "共催: 自由が丘住区青少年委員会を確認。関連URL: "
            "[p0_review_20260721] 公開データは確認済みだが第三者URLだったため、主催者公式の当年根拠を追加する。"
        ),
        "new_source_url": "https://www.jiyugaoka-abc.com/special/bonodori/",
        "reason": (
            "RDBのsource_urlはtokyofesta.com(第三者まとめサイト)のままだった。"
            "siteは2026-07-21レビューで主催者(自由が丘商店街振興組合)公式ページの"
            "当年特設ページへ既に更新済み。siteの方を正としてRDBへ反映する。"
        ),
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
        "SELECT occurrence_id, event_year, display_name, detail, source_url FROM event_occurrences WHERE occurrence_id = ?",
        (occurrence_id,),
    )
    return result[0] if result else None


def build_plan(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    planned: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in RECONCILIATIONS:
        before = occurrence(conn, item["occurrence_id"])
        if not before:
            skipped.append({**item, "skip_reason": "missing_occurrence"})
            continue
        if before["event_year"] != item["expected_event_year"]:
            skipped.append({**item, "skip_reason": "unexpected_event_year", "before": before})
            continue
        if before.get("detail") == item["new_detail"] and before.get("source_url") == item["new_source_url"]:
            skipped.append({**item, "skip_reason": "already_applied", "before": before})
            continue
        planned.append({**item, "before": before})
    return planned, skipped


def apply_plan(conn: sqlite3.Connection, planned: list[dict[str, Any]], now: str) -> list[dict[str, Any]]:
    applied: list[dict[str, Any]] = []
    for item in planned:
        conn.execute(
            "UPDATE event_occurrences SET detail = ?, source_url = ?, updated_at = ? WHERE occurrence_id = ?",
            (item["new_detail"], item["new_source_url"], now, item["occurrence_id"]),
        )
        after = occurrence(conn, item["occurrence_id"])
        applied.append({**item, "after": after})
    return applied


def rollback_checks(conn: sqlite3.Connection, applied: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_rows:
        issues.append({"severity": "high", "issue_type": "foreign_key_check_failed", "count": len(fk_rows)})
    for item in applied:
        after = item.get("after") or {}
        if after.get("detail") != item["new_detail"] or after.get("source_url") != item["new_source_url"]:
            issues.append(
                {
                    "severity": "high",
                    "issue_type": "reconciliation_not_applied",
                    "occurrence_id": item["occurrence_id"],
                    "after": after,
                }
            )
    return issues


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--master-db", type=Path, default=MASTER_DB)
    parser.add_argument("--dry-run-db", type=Path, default=OUT_DB)
    args = parser.parse_args()

    now = datetime.now(timezone.utc).isoformat()
    mode = "apply" if args.apply else "dry_run"
    backup = ""

    if args.apply:
        if args.confirm != CONFIRM:
            raise SystemExit(f"--apply requires --confirm {CONFIRM!r}")
        backup = str(backup_db(args.master_db, now))
        working_db = args.master_db
    else:
        copy_db(args.master_db, args.dry_run_db)
        working_db = args.dry_run_db

    with closing(sqlite3.connect(working_db)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        before_counts = table_counts(conn)
        planned, skipped = build_plan(conn)
        applied = apply_plan(conn, planned, now)
        issues = rollback_checks(conn, applied)
        if issues:
            conn.rollback()
            rolled_back, db_committed = True, False
        else:
            conn.commit()
            rolled_back, db_committed = False, True
            if args.apply:
                refresh_manifest_database_state(working_db, updated_at=now)
        after_counts = table_counts(conn)

    result = {
        "generated_at": now,
        "generated_by": "apply_reviewed_detail_source_reconciliation_20260724.py",
        "mode": mode,
        "outputs": {"target_db": str(args.master_db if args.apply else args.dry_run_db), "backup_db": backup},
        "write_guard": {"db_committed": db_committed, "rolled_back": rolled_back},
        "summary": {
            "planned_count": len(planned),
            "applied_count": len(applied),
            "skipped_count": len(skipped),
            "issues_by_severity": dict(Counter(i.get("severity", "unknown") for i in issues)),
            "before_counts": before_counts,
            "after_counts": after_counts,
        },
        "applied": applied,
        "skipped": skipped,
        "issues": issues,
    }
    write_json(OUT_JSON, result)
    print(
        "detail/source reconciliation: "
        f"mode={mode} applied={len(applied)} skipped={len(skipped)} committed={db_committed} report={OUT_JSON}"
    )


if __name__ == "__main__":
    main()
