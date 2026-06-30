"""Generate a read-only post-batch maintenance report.

This command is intentionally independent from Notion. It reads the current
Master RDB plus local JSON outputs and writes a compact JSON/Markdown report.
"""

import argparse
import json
import os
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


DATA = Path("data")
DEFAULT_MASTER_DB = DATA / "bon_odori_master.sqlite"
DEFAULT_OUT_JSON = DATA / "post_batch_maintenance_report.json"
DEFAULT_OUT_MD = DATA / "post_batch_maintenance_report.md"

JSON_INPUTS = {
    "public_events": DATA / "public" / "events_public.json",
    "voices": DATA / "voices.json",
    "x_account_scores": DATA / "x_account_scores.json",
    "youtube_active_video_review": DATA / "youtube_active_video_review.json",
    "youtube_setlist_occurrences": DATA / "youtube_setlist_occurrences.json",
    "youtube_year_backfill_candidates": DATA / "youtube_year_backfill_candidates.json",
    "youtube_daily_backfill_report": DATA / "youtube_daily_backfill_report.json",
}

REQUIRED_INPUTS = {"master_rdb", "public_events"}


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def iso_mtime(path):
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def load_json(path):
    path = Path(path)
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def input_file_info(path):
    path = Path(path)
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "size_bytes": 0,
            "modified_at": None,
        }
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": path.stat().st_size,
        "modified_at": iso_mtime(path),
    }


def json_shape(name, path):
    info = input_file_info(path)
    if not info["exists"]:
        info.update({"kind": None, "generated_at": None, "counts": {}, "error": "missing"})
        return info
    try:
        payload = load_json(path)
    except json.JSONDecodeError as exc:
        info.update({"kind": None, "generated_at": None, "counts": {}, "error": str(exc)})
        return info

    counts = {}
    if isinstance(payload, list):
        kind = "list"
        counts["items"] = len(payload)
    elif isinstance(payload, dict):
        kind = "object"
        info["keys"] = sorted(payload.keys())
        counts.update(extract_known_counts(name, payload))
    else:
        kind = type(payload).__name__

    info.update(
        {
            "kind": kind,
            "generated_at": payload.get("generated_at") if isinstance(payload, dict) else None,
            "counts": counts,
            "error": None,
        }
    )
    return info


def nested_summary(payload):
    if not isinstance(payload, dict):
        return {}
    summary = payload.get("summary")
    if isinstance(summary, dict):
        return summary
    report = payload.get("report")
    if isinstance(report, dict):
        return report
    return {}


def extract_known_counts(name, payload):
    if not isinstance(payload, dict):
        return {}
    if name == "x_account_scores":
        return {"accounts": len(payload.get("accounts") or [])}
    if name == "youtube_active_video_review":
        return {
            "video_count": int_value(payload.get("video_count")),
            "counts": payload.get("counts") or {},
            "rows": len(payload.get("rows") or []),
        }
    if name == "youtube_setlist_occurrences":
        keys = [
            "occurrence_count",
            "setlist_song_count",
            "youtube_voice_count",
            "matched_public_event_count",
            "skipped_count",
        ]
        return {key: int_value(payload.get(key)) for key in keys}
    if name == "youtube_year_backfill_candidates":
        summary = nested_summary(payload)
        return {
            "candidate_count": int_value(summary.get("candidate_count"), len(payload.get("candidates") or [])),
            "strong_count": int_value(summary.get("strong_count")),
            "review_count": int_value(summary.get("review_count")),
            "status_counts": summary.get("status_counts") or {},
        }
    if name == "youtube_daily_backfill_report":
        return {
            "status": payload.get("status") or "",
            "selected_rows": int_value(payload.get("selected_rows")),
            "completed_batches": int_value(payload.get("completed_batches")),
            "remaining_rows_after": int_value(payload.get("remaining_rows_after")),
            "candidates_after": int_value(payload.get("candidates_after")),
            "strong_after": int_value(payload.get("strong_after")),
            "review_after": int_value(payload.get("review_after")),
        }
    return {}


def int_value(value, default=0):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def scalar(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()[0]


def count_rows(conn, table):
    return scalar(conn, f"SELECT COUNT(*) FROM {table}")


def count_by(conn, sql, params=()):
    rows = conn.execute(sql, params).fetchall()
    return {"|".join("" if value is None else str(value) for value in row[:-1]): row[-1] for row in rows}


def table_counts(conn):
    tables = [
        row[0]
        for row in conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        )
    ]
    return {table: count_rows(conn, table) for table in tables}


def master_rdb_report(db_path, target_year):
    db_path = Path(db_path)
    info = input_file_info(db_path)
    if not info["exists"]:
        info.update({"error": "missing", "table_counts": {}, "target_year": {}})
        return info

    uri = f"file:{db_path.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        counts = table_counts(conn)
        target = {
            "year": target_year,
            "occurrences": scalar(conn, "SELECT COUNT(*) FROM event_occurrences WHERE event_year = ?", (target_year,)),
            "published_occurrences": scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM event_occurrences
                WHERE event_year = ?
                  AND lifecycle_status = 'published'
                """,
                (target_year,),
            ),
            "unconfirmed_occurrences": scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM event_occurrences
                WHERE event_year = ?
                  AND lifecycle_status = '未確認'
                """,
                (target_year,),
            ),
            "missing_date_start": scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM event_occurrences
                WHERE event_year = ?
                  AND COALESCE(date_start, '') = ''
                """,
                (target_year,),
            ),
            "missing_venue": scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM event_occurrences
                WHERE event_year = ?
                  AND COALESCE(venue_id, '') = ''
                """,
                (target_year,),
            ),
            "missing_source_url": scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM event_occurrences
                WHERE event_year = ?
                  AND COALESCE(source_url, '') = ''
                """,
                (target_year,),
            ),
            "status_counts": count_by(
                conn,
                """
                SELECT lifecycle_status, date_status, confidence, COUNT(*)
                FROM event_occurrences
                WHERE event_year = ?
                GROUP BY lifecycle_status, date_status, confidence
                ORDER BY lifecycle_status, date_status, confidence
                """,
                (target_year,),
            ),
        }
        review = {
            "event_investigation_tasks": count_rows(conn, "event_investigation_tasks"),
            "event_investigation_task_counts": count_by(
                conn,
                """
                SELECT priority_label, status, recommended_action, COUNT(*)
                FROM event_investigation_tasks
                GROUP BY priority_label, status, recommended_action
                ORDER BY priority_label, status, recommended_action
                """,
            ),
            "open_p0_tasks": scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM event_investigation_tasks
                WHERE priority_label = 'P0'
                  AND status NOT IN ('確認済み', '終了')
                """,
            ),
            "historical_promotion_candidates": count_rows(conn, "historical_promotion_candidates"),
            "historical_auto_promote_eligible": scalar(
                conn,
                "SELECT COUNT(*) FROM historical_promotion_candidates WHERE auto_promote_eligible = 1",
            ),
            "predicted_occurrence_dates": count_rows(conn, "predicted_occurrence_dates"),
            "predicted_date_counts": count_by(
                conn,
                """
                SELECT application_status, confidence, basis_type, COUNT(*)
                FROM predicted_occurrence_dates
                GROUP BY application_status, confidence, basis_type
                ORDER BY application_status, confidence, basis_type
                """,
            ),
            "observed_occurrence_counts": count_by(
                conn,
                """
                SELECT match_status, quality_status, COUNT(*)
                FROM observed_occurrences
                GROUP BY match_status, quality_status
                ORDER BY match_status, quality_status
                """,
            ),
        }

    info.update(
        {
            "error": None,
            "table_counts": counts,
            "target_year": target,
            "review": review,
        }
    )
    return info


def summarize_public_events(path):
    info = json_shape("public_events", path)
    if not info["exists"] or info.get("error"):
        return info
    payload = load_json(path)
    if not isinstance(payload, list):
        info["error"] = "expected list"
        return info

    status_counts = Counter()
    date_confidence_counts = Counter()
    missing_source_urls = 0
    missing_date = 0
    with_songs = 0
    for row in payload:
        if not isinstance(row, dict):
            continue
        status_counts[row.get("public_status") or ""] += 1
        date_confidence = row.get("date_confidence") or {}
        date_confidence_counts[date_confidence.get("level") or ""] += 1
        if not row.get("date"):
            missing_date += 1
        if not row.get("source_urls"):
            missing_source_urls += 1
        if row.get("songs"):
            with_songs += 1

    info["counts"].update(
        {
            "events": len(payload),
            "missing_date": missing_date,
            "missing_source_urls": missing_source_urls,
            "with_songs": with_songs,
            "public_status_counts": dict(sorted(status_counts.items())),
            "date_confidence_counts": dict(sorted(date_confidence_counts.items())),
        }
    )
    return info


def summarize_month_queues(data_dir):
    queues = {}
    for path in sorted(Path(data_dir).glob("month_??_youtube_backfill_queue.json")):
        info = json_shape(path.stem, path)
        try:
            month = path.stem.split("_")[1]
        except IndexError:
            month = path.stem
        payload = load_json(path) if path.exists() and not info.get("error") else {}
        summary = nested_summary(payload)
        queues[month] = {
            "path": str(path),
            "items": int_value(summary.get("items"), len(payload.get("rows") or []) if isinstance(payload, dict) else 0),
            "generated_at": payload.get("generated_at") if isinstance(payload, dict) else None,
            "modified_at": info.get("modified_at"),
        }
    return queues


def collect_inputs(data_dir):
    data_dir = Path(data_dir)
    inputs = {
        "public_events": summarize_public_events(data_dir / "public" / "events_public.json"),
        "voices": json_shape("voices", data_dir / "voices.json"),
        "x_account_scores": json_shape("x_account_scores", data_dir / "x_account_scores.json"),
        "youtube_active_video_review": json_shape(
            "youtube_active_video_review", data_dir / "youtube_active_video_review.json"
        ),
        "youtube_setlist_occurrences": json_shape(
            "youtube_setlist_occurrences", data_dir / "youtube_setlist_occurrences.json"
        ),
        "youtube_year_backfill_candidates": json_shape(
            "youtube_year_backfill_candidates", data_dir / "youtube_year_backfill_candidates.json"
        ),
        "youtube_daily_backfill_report": json_shape(
            "youtube_daily_backfill_report", data_dir / "youtube_daily_backfill_report.json"
        ),
        "month_youtube_backfill_queues": summarize_month_queues(data_dir),
    }
    return inputs


def collect_checks(report):
    checks = []
    missing_required = []
    master = report["master_rdb"]
    if not master.get("exists"):
        missing_required.append("master_rdb")
        checks.append({"level": "high", "name": "master_rdb_missing", "message": "Master RDB is missing."})
    public_events = report["inputs"]["public_events"]
    if not public_events.get("exists"):
        missing_required.append("public_events")
        checks.append({"level": "high", "name": "public_events_missing", "message": "Public events JSON is missing."})
    elif public_events.get("error"):
        missing_required.append("public_events")
        checks.append(
            {"level": "high", "name": "public_events_invalid", "message": f"Public events JSON error: {public_events['error']}"}
        )

    if master.get("exists") and not master.get("error"):
        target = master["target_year"]
        review = master["review"]
        if target["missing_date_start"]:
            checks.append(
                {
                    "level": "info",
                    "name": "target_year_missing_dates",
                    "message": f"{target['missing_date_start']} target-year occurrences have no date_start.",
                }
            )
        if target["missing_venue"]:
            checks.append(
                {
                    "level": "info",
                    "name": "target_year_missing_venues",
                    "message": f"{target['missing_venue']} target-year occurrences have no venue_id.",
                }
            )
        if review["open_p0_tasks"]:
            checks.append(
                {
                    "level": "medium",
                    "name": "open_p0_tasks",
                    "message": f"{review['open_p0_tasks']} P0 investigation tasks remain open.",
                }
            )
        if review["historical_auto_promote_eligible"]:
            checks.append(
                {
                    "level": "info",
                    "name": "historical_auto_promote_eligible",
                    "message": (
                        f"{review['historical_auto_promote_eligible']} historical candidates are auto-promote eligible, "
                        "but this report does not apply them."
                    ),
                }
            )

    candidates = report["inputs"]["youtube_year_backfill_candidates"]
    candidate_counts = candidates.get("counts") or {}
    if candidate_counts.get("review_count"):
        checks.append(
            {
                "level": "info",
                "name": "youtube_review_candidates",
                "message": f"{candidate_counts['review_count']} YouTube candidates are in review status.",
            }
        )

    report["input_errors"] = missing_required
    checks.append(
        {
            "level": "info",
            "name": "notion_dependency",
            "message": "Notion API is not required by this post-batch maintenance path.",
        }
    )
    return checks


def recommended_next_actions(report):
    actions = []
    master = report["master_rdb"]
    if master.get("exists") and not master.get("error"):
        review = master["review"]
        if review["open_p0_tasks"]:
            actions.append("P0調査タスクは人手確認を残し、自動反映はしない。")
        if review["historical_auto_promote_eligible"]:
            actions.append("historical auto-promote候補は別のapply判断までレポート止まりにする。")
    public_counts = (report["inputs"]["public_events"].get("counts") or {})
    if public_counts.get("missing_source_urls"):
        actions.append("公開JSONの source_urls 欠落は public sync/deploy guard 深掘りで扱う。")
    youtube_counts = (report["inputs"]["youtube_year_backfill_candidates"].get("counts") or {})
    if youtube_counts.get("review_count"):
        actions.append("YouTube review候補はPR上の確認対象として残し、自動採用しない。")
    if not actions:
        actions.append("読み取り専用レポートとして日次後段に組み込める状態。")
    return actions


def build_report(data_dir=DATA, master_db=DEFAULT_MASTER_DB, mode="current-light", target_year=2026):
    inputs = collect_inputs(data_dir)
    report = {
        "generated_by": "run_post_batch_maintenance.py",
        "generated_at": now_utc(),
        "mode": mode,
        "target_year": target_year,
        "read_only": True,
        "notion_api_required": False,
        "writes": [
            "data/post_batch_maintenance_report.json",
            "data/post_batch_maintenance_report.md",
        ],
        "forbidden_side_effects": [
            "notion_production_sync",
            "master_rdb_apply",
            "s3_cloudfront_deploy",
            "prediction_public_promotion",
            "review_decision_apply",
        ],
        "master_rdb": master_rdb_report(master_db, target_year),
        "inputs": inputs,
    }
    report["checks"] = collect_checks(report)
    report["recommended_next_actions"] = recommended_next_actions(report)
    report["status"] = "blocked_missing_inputs" if report["input_errors"] else "report_generated"
    return report


def render_dict_counts(counts):
    if not counts:
        return "- なし"
    return "\n".join(f"- {key or '(blank)'}: {value}" for key, value in counts.items())


def render_table(rows):
    if not rows:
        return ""
    lines = ["| 項目 | 値 |", "| --- | ---: |"]
    for label, value in rows:
        lines.append(f"| {label} | {value} |")
    return "\n".join(lines)


def render_markdown(report):
    master = report["master_rdb"]
    public_counts = report["inputs"]["public_events"].get("counts") or {}
    candidate_counts = report["inputs"]["youtube_year_backfill_candidates"].get("counts") or {}
    daily_counts = report["inputs"]["youtube_daily_backfill_report"].get("counts") or {}
    active_video_counts = report["inputs"]["youtube_active_video_review"].get("counts") or {}
    setlist_counts = report["inputs"]["youtube_setlist_occurrences"].get("counts") or {}
    voices_counts = report["inputs"]["voices"].get("counts") or {}
    x_counts = report["inputs"]["x_account_scores"].get("counts") or {}
    month_queues = report["inputs"].get("month_youtube_backfill_queues") or {}

    lines = [
        "# post-batch maintenance report",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- mode: {report['mode']}",
        f"- target_year: {report['target_year']}",
        f"- status: {report['status']}",
        f"- read_only: {str(report['read_only']).lower()}",
        f"- Notion API required: {str(report['notion_api_required']).lower()}",
        "",
        "## 境界",
        "",
        "- 読む: Master RDB、voices/X/YouTube/public JSON",
        "- 書く: このレポートJSON/Markdownのみ",
        "- やらない: Notion本番同期、Master RDB反映、S3/CloudFront deploy、予測の公開昇格、レビュー判断の反映",
        "",
        "## チェック",
        "",
    ]
    for check in report["checks"]:
        lines.append(f"- {check['level']}: {check['name']} - {check['message']}")
    lines.extend(["", "## 推奨次アクション", ""])
    lines.extend(f"- {action}" for action in report["recommended_next_actions"])

    if master.get("exists") and not master.get("error"):
        target = master["target_year"]
        review = master["review"]
        lines.extend(
            [
                "",
                "## Master RDB",
                "",
                render_table(
                    [
                        ("event_occurrences", master["table_counts"].get("event_occurrences", 0)),
                        ("event_series", master["table_counts"].get("event_series", 0)),
                        ("venues", master["table_counts"].get("venues", 0)),
                        ("songs", master["table_counts"].get("songs", 0)),
                        ("evidence_items", master["table_counts"].get("evidence_items", 0)),
                        ("observed_occurrences", master["table_counts"].get("observed_occurrences", 0)),
                    ]
                ),
                "",
                f"### {target['year']}年 occurrence",
                "",
                render_table(
                    [
                        ("occurrences", target["occurrences"]),
                        ("published", target["published_occurrences"]),
                        ("unconfirmed", target["unconfirmed_occurrences"]),
                        ("missing_date_start", target["missing_date_start"]),
                        ("missing_venue", target["missing_venue"]),
                        ("missing_source_url", target["missing_source_url"]),
                    ]
                ),
                "",
                "### review queues",
                "",
                render_table(
                    [
                        ("event_investigation_tasks", review["event_investigation_tasks"]),
                        ("open_p0_tasks", review["open_p0_tasks"]),
                        ("historical_promotion_candidates", review["historical_promotion_candidates"]),
                        ("historical_auto_promote_eligible", review["historical_auto_promote_eligible"]),
                        ("predicted_occurrence_dates", review["predicted_occurrence_dates"]),
                    ]
                ),
            ]
        )
    else:
        lines.extend(["", "## Master RDB", "", f"- error: {master.get('error') or 'unavailable'}"])

    lines.extend(
        [
            "",
            "## public JSON",
            "",
            render_table(
                [
                    ("events", public_counts.get("events", 0)),
                    ("missing_date", public_counts.get("missing_date", 0)),
                    ("missing_source_urls", public_counts.get("missing_source_urls", 0)),
                    ("with_songs", public_counts.get("with_songs", 0)),
                ]
            ),
            "",
            "### public_status",
            "",
            render_dict_counts(public_counts.get("public_status_counts") or {}),
            "",
            "## YouTube/X inputs",
            "",
            render_table(
                [
                    ("voices", voices_counts.get("items", 0)),
                    ("x_account_scores.accounts", x_counts.get("accounts", 0)),
                    ("active_video_review.video_count", active_video_counts.get("video_count", 0)),
                    ("setlist_occurrences", setlist_counts.get("occurrence_count", 0)),
                    ("setlist_songs", setlist_counts.get("setlist_song_count", 0)),
                    ("youtube_candidates", candidate_counts.get("candidate_count", 0)),
                    ("youtube_candidates.strong", candidate_counts.get("strong_count", 0)),
                    ("youtube_candidates.review", candidate_counts.get("review_count", 0)),
                    ("daily_backfill.selected_rows", daily_counts.get("selected_rows", 0)),
                    ("daily_backfill.remaining_rows_after", daily_counts.get("remaining_rows_after", 0)),
                ]
            ),
            "",
            "### active_video_review counts",
            "",
            render_dict_counts(active_video_counts.get("counts") or {}),
            "",
            "### month queues",
            "",
        ]
    )
    if month_queues:
        for month, payload in sorted(month_queues.items()):
            lines.append(f"- {int(month)}月: {payload.get('items', 0)}")
    else:
        lines.append("- なし")

    lines.extend(["", "## 入力ファイル", ""])
    for name, payload in report["inputs"].items():
        if name == "month_youtube_backfill_queues":
            continue
        lines.append(
            f"- {name}: exists={payload.get('exists')} size={payload.get('size_bytes')} "
            f"modified_at={payload.get('modified_at')} generated_at={payload.get('generated_at')}"
        )
    lines.append(f"- master_rdb: exists={master.get('exists')} size={master.get('size_bytes')} modified_at={master.get('modified_at')}")
    lines.append("")
    return "\n".join(line for line in lines if line is not None)


def append_github_summary(markdown, explicit_path=None):
    target = explicit_path or os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return None
    path = Path(target)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n\n")
        handle.write(markdown)
        handle.write("\n")
    return str(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["current-light", "current-report"], default="current-light")
    parser.add_argument("--target-year", type=int, default=2026)
    parser.add_argument("--data-dir", type=Path, default=DATA)
    parser.add_argument("--master-db", type=Path, default=DEFAULT_MASTER_DB)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    parser.add_argument("--allow-missing-inputs", action="store_true")
    parser.add_argument("--append-github-summary", action="store_true")
    parser.add_argument("--github-summary", type=Path)
    args = parser.parse_args()

    report = build_report(
        data_dir=args.data_dir,
        master_db=args.master_db,
        mode=args.mode,
        target_year=args.target_year,
    )
    markdown = render_markdown(report)
    write_json(args.out_json, report)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(markdown, encoding="utf-8")
    summary_path = None
    if args.append_github_summary or args.github_summary:
        summary_path = append_github_summary(markdown, args.github_summary)

    print(
        "post-batch maintenance: "
        f"status={report['status']} "
        f"mode={report['mode']} "
        f"out_json={args.out_json} "
        f"out_md={args.out_md}"
    )
    if summary_path:
        print(f"github_summary={summary_path}")
    if report["input_errors"] and not args.allow_missing_inputs:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
