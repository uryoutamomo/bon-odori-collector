"""Apply current-year confirmations found from predicted date source rechecks.

Default mode writes to a copied SQLite DB. Apply mode updates only reviewed
current-year confirmations and does not write Notion or public JSON.
"""

import argparse
import json
import shutil
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import audit_master_rdb
from master_db import MASTER_DB, refresh_manifest_database_state, stable_id, table_counts


DATA = Path("data")
OUT_DB = DATA / "predicted_occurrence_source_rechecks_dry_run.sqlite"
OUT_JSON = DATA / "predicted_occurrence_source_rechecks_apply_report.json"
OUT_MD = DATA / "predicted_occurrence_source_rechecks_apply_report.md"
BACKUP_DIR = DATA / "backups"
CONFIRM = "APPLY PREDICTED SOURCE RECHECKS"
SCRIPT_NAME = "apply_predicted_occurrence_source_rechecks.py"


RECHECKS = [
    {
        "event_name": "第15回 鴨台盆踊り",
        "predicted_date_id": "preddate_131b2204d5f23eae",
        "review_result": "no_current_year_source_found",
        "checked_urls": [
            "https://www.tais.ac.jp/guide/latest_news/",
            "https://www.tais.ac.jp/guide/latest_news/20250627/92922/",
            "https://minato-bon-odori.blogspot.com/2021/05/coming-all-h.html",
        ],
        "notes": "大正大学最新ニュースと現行盆踊り一覧では2026年の鴨台盆踊りを確認できず、2025年公式記事は過去実績として保持。",
    },
    {
        "event_name": "自由が丘納涼盆踊り大会",
        "predicted_date_id": "preddate_4176bccdcae25ce9",
        "review_result": "no_current_year_source_found",
        "checked_urls": [
            "https://www.jiyugaoka-abc.com/",
            "https://www.jiyugaoka-abc.com/event/",
            "https://tokyofesta.com/23ku/23804/",
            "https://minato-bon-odori.blogspot.com/2021/05/coming-all-h.html",
        ],
        "notes": "自由が丘公式イベント一覧は2026年7月が未更新表示。2025年TokyoFestaは過去実績として保持。",
    },
    {
        "event_name": "第28回新橋こいち祭 盆踊り",
        "predicted_date_id": "preddate_6e157d3b898d1a01",
        "review_result": "confirmed_existing_occurrence",
        "target_occurrence_id": "occ_7a555fbc00d0c059",
        "target_display_name": "新橋こいち祭",
        "date_start": "2026-07-23",
        "date_end": "2026-07-24",
        "venue_name": "桜田公園",
        "source_url": "http://www.shinbashi.net/top/koichi/2026/greeting/",
        "source_excerpt": "第29回新橋こいち祭: 2026年7月23日（木）・24日（金）。桜田会場（盆踊り・ステージ・出店）15:00～20:30。",
        "prediction_resolution": "superseded_by_curated",
        "notes": "予測は旧系列名かつ7/23単日だったが、既存2026開催回は公式2026概要と一致する日付範囲を持つため公式確認済みに昇格。",
    },
    {
        "event_name": "謝恩納涼盆踊り大会（青山善光寺）",
        "predicted_date_id": "preddate_bd796ef03c38aa69",
        "review_result": "no_current_year_source_found",
        "checked_urls": [
            "https://omoharareal.com/navi/news/detail/5157",
            "https://minato-bon-odori.blogspot.com/2021/05/coming-all-h.html",
        ],
        "notes": "OMOHARAREALは令和7年/2025年記事。現行盆踊り一覧では2026年行を確認できず、予測のまま保持。",
    },
    {
        "event_name": "丸の内de盆踊り",
        "predicted_date_id": "preddate_369836a93ec48b81",
        "review_result": "no_current_year_source_found",
        "checked_urls": [
            "https://www.marunouchi.com/pickup/event/6763/",
            "https://minato-bon-odori.blogspot.com/2021/05/coming-all-h.html",
        ],
        "notes": "Marunouchi.comは2025年の丸の内夏祭り記事。現行盆踊り一覧では2026年行を確認できず、予測のまま保持。",
    },
]


def rows(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def scalar(conn, query, params=()):
    return conn.execute(query, params).fetchone()[0]


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_db(source, out_db):
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
        SELECT o.occurrence_id, o.display_name, o.event_year, o.venue_id,
               v.canonical_name AS venue_name, o.date_start, o.date_end,
               o.date_status, o.lifecycle_status, o.confidence,
               o.source_kind, o.source_url
        FROM event_occurrences o
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE o.occurrence_id = ?
        """,
        (occurrence_id,),
    )
    return result[0] if result else None


def prediction(conn, predicted_date_id):
    result = rows(
        conn,
        """
        SELECT predicted_date_id, target_event_name, target_occurrence_id,
               date_start, date_end, application_status
        FROM predicted_occurrence_dates
        WHERE predicted_date_id = ?
        """,
        (predicted_date_id,),
    )
    return result[0] if result else None


def build_plan(conn):
    planned = []
    skipped = []
    reviewed_only = []
    for item in RECHECKS:
        pred = prediction(conn, item["predicted_date_id"])
        if item["review_result"] != "confirmed_existing_occurrence":
            reviewed_only.append({**item, "prediction": pred})
            continue
        before = occurrence(conn, item["target_occurrence_id"])
        if not pred:
            skipped.append({**item, "skip_reason": "missing_prediction"})
            continue
        if not before:
            skipped.append({**item, "skip_reason": "missing_target_occurrence"})
            continue
        if before.get("event_year") != 2026:
            skipped.append({**item, "skip_reason": "unexpected_event_year", "before": before})
            continue
        if item["venue_name"] != before.get("venue_name"):
            skipped.append({**item, "skip_reason": "venue_mismatch", "before": before})
            continue
        if (
            before.get("date_status") == "confirmed"
            and before.get("date_start") == item["date_start"]
            and (before.get("date_end") or "") == item["date_end"]
            and before.get("source_url") == item["source_url"]
            and pred.get("application_status") == item["prediction_resolution"]
        ):
            skipped.append({**item, "skip_reason": "already_applied", "before": before, "prediction": pred})
            continue
        planned.append({**item, "before": before, "prediction": pred})
    return planned, skipped, reviewed_only


def upsert_occurrence_date(conn, item, now):
    occurrence_date_id = stable_id(
        "odate",
        item["target_occurrence_id"],
        item["date_start"],
        item["date_end"],
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
            item["target_occurrence_id"],
            item["date_start"],
            item["date_end"],
            "confirmed",
            "high",
            None,
            "official_current_year",
            now,
        ),
    )
    return occurrence_date_id


def apply_plan(conn, planned, now):
    applied = []
    for item in planned:
        conn.execute(
            """
            UPDATE event_occurrences
            SET date_start = ?,
                date_end = ?,
                date_status = 'confirmed',
                lifecycle_status = 'published',
                confidence = 'high',
                source_kind = 'official_current_year',
                source_url = ?,
                updated_at = ?
            WHERE occurrence_id = ?
            """,
            (
                item["date_start"],
                item["date_end"],
                item["source_url"],
                now,
                item["target_occurrence_id"],
            ),
        )
        occurrence_date_id = upsert_occurrence_date(conn, item, now)
        conn.execute(
            """
            UPDATE predicted_occurrence_dates
            SET application_status = ?,
                target_occurrence_id = ?,
                updated_at = ?
            WHERE predicted_date_id = ?
            """,
            (
                item["prediction_resolution"],
                item["target_occurrence_id"],
                now,
                item["predicted_date_id"],
            ),
        )
        conn.execute(
            """
            UPDATE notion_sync_jobs
            SET status = ?,
                result_json = ?
            WHERE target_table = 'predicted_occurrence_dates'
              AND target_id = ?
              AND status = 'pending'
            """,
            (
                item["prediction_resolution"],
                json.dumps(
                    {
                        "reviewed_by": SCRIPT_NAME,
                        "reviewed_at": now,
                        "reason": "current_year_official_occurrence_confirmed",
                        "target_occurrence_id": item["target_occurrence_id"],
                        "source_url": item["source_url"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                item["predicted_date_id"],
            ),
        )
        applied.append(
            {
                **item,
                "after": occurrence(conn, item["target_occurrence_id"]),
                "prediction_after": prediction(conn, item["predicted_date_id"]),
                "occurrence_date_id": occurrence_date_id,
            }
        )
    return applied


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
        after = item.get("after") or {}
        if after.get("date_status") != "confirmed":
            issues.append(
                {
                    "severity": "high",
                    "issue_type": "occurrence_not_confirmed",
                    "occurrence_id": item["target_occurrence_id"],
                }
            )
        if after.get("date_start") != item["date_start"] or (after.get("date_end") or "") != item["date_end"]:
            issues.append(
                {
                    "severity": "high",
                    "issue_type": "occurrence_dates_not_applied",
                    "occurrence_id": item["target_occurrence_id"],
                }
            )
    return issues


def render_markdown(result):
    lines = [
        "# Predicted occurrence source rechecks apply report",
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
        f"- reviewed_only_count: {result['summary']['reviewed_only_count']}",
        f"- issues_by_severity: {result['summary']['issues_by_severity']}",
        f"- confirmed_2026_occurrences: {result['summary']['confirmed_2026_occurrences']}",
        f"- predicted_occurrence_dates_by_status: {result['summary']['predicted_occurrence_dates_by_status']}",
        "",
        "## Applied",
        "",
        "| event | occurrence | date | source | prediction |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in result["applied"]:
        date_text = item["date_start"] if not item["date_end"] else f"{item['date_start']} to {item['date_end']}"
        lines.append(
            f"| {item['event_name']} | {item['target_display_name']} | {date_text} | "
            f"{item['source_url']} | {item['prediction_resolution']} |"
        )
    lines.extend(["", "## Reviewed Without Apply", ""])
    for item in result["reviewed_only"]:
        lines.append(f"- {item['event_name']}: {item['review_result']} / {item['notes']}")
    if result["skipped"]:
        lines.extend(["", "## Skipped", ""])
        for item in result["skipped"]:
            lines.append(f"- {item.get('event_name')}: {item.get('skip_reason')}")
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
    target_db = Path(args.master_db if args.apply else args.out_db)
    backup = ""
    if args.apply:
        backup = str(backup_db(args.master_db, now))
    else:
        copy_db(args.master_db, args.out_db)

    with sqlite3.connect(target_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        planned, skipped, reviewed_only = build_plan(conn)
        applied = apply_plan(conn, planned, now)
        issues = consistency_checks(conn, applied)
        has_high_issue = any(issue.get("severity") == "high" for issue in issues)
        rolled_back = False
        if args.apply and has_high_issue:
            conn.rollback()
            rolled_back = True
            committed = False
        else:
            conn.commit()
            committed = True
        summary = {
            "applied_count": len(applied),
            "skipped_count": len(skipped),
            "reviewed_only_count": len(reviewed_only),
            "issues_by_severity": dict(Counter(issue["severity"] for issue in issues)),
            "table_counts": table_counts(conn),
            "confirmed_2026_occurrences": scalar(
                conn,
                "SELECT COUNT(*) FROM event_occurrences WHERE event_year = 2026 AND date_status = 'confirmed'",
            ),
            "predicted_occurrence_dates_by_status": dict(
                Counter(
                    row["application_status"]
                    for row in rows(conn, "SELECT application_status FROM predicted_occurrence_dates")
                )
            ),
        }

    audit = audit_master_rdb.audit(
        SimpleNamespace(
            db=target_db,
            notion_db=audit_master_rdb.NOTION_DB,
            song_occurrences=audit_master_rdb.SONG_OCCURRENCES,
            manifest=audit_master_rdb.MASTER_MANIFEST,
        )
    )
    result = {
        "generated_by": SCRIPT_NAME,
        "generated_at": now,
        "mode": "apply" if args.apply else "dry_run",
        "scope": "rdb_only_no_notion_no_public_json",
        "sources": {"master_db": str(args.master_db)},
        "outputs": {
            "target_db": str(target_db),
            "dry_run_db": "" if args.apply else str(args.out_db),
            "backup_db": backup,
        },
        "write_guard": {
            "db_committed": committed,
            "rolled_back": rolled_back,
        },
        "summary": summary,
        "audit": {
            "issue_count": audit["issue_count"],
            "issues_by_severity": audit["issues_by_severity"],
        },
        "applied": applied,
        "skipped": skipped,
        "reviewed_only": reviewed_only,
        "issues": issues,
    }
    write_json(args.out_json, result)
    Path(args.out_md).write_text(render_markdown(result), encoding="utf-8")
    if args.apply and not rolled_back:
        refresh_manifest_database_state(args.master_db)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-db", default=str(MASTER_DB))
    parser.add_argument("--out-db", default=str(OUT_DB))
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        result = run(args)
    except ValueError as exc:
        parser.error(str(exc))
    print(
        "predicted occurrence source rechecks: "
        f"mode={result['mode']} applied={result['summary']['applied_count']} "
        f"reviewed_only={result['summary']['reviewed_only_count']} "
        f"issues={result['summary']['issues_by_severity']}"
    )
    return 1 if result["summary"]["issues_by_severity"].get("high") else 0


if __name__ == "__main__":
    raise SystemExit(main())
