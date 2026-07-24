"""Run a small daily YouTube backfill batch and leave a mail reminder."""

import argparse
import json
import re
import subprocess
import sys
import urllib.error
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from event_model.year_context import normalize_target_year
from youtube_channels.backfill_youtube_descriptions import load_env_value
from youtube_backfill import harvest_youtube_year_backfill as harvest_mod
from master_rdb.freeze_policy import is_group_frozen, load_policy


DATA = Path("data")
QUEUE = DATA / "youtube_year_backfill_queue.json"
CANDIDATES = DATA / "youtube_year_backfill_candidates.json"
SCHEDULE_RULES = DATA / "event_schedule_rules.json"
REPORT_JSON = DATA / "youtube_daily_backfill_report.json"
REPORT_MD = DATA / "youtube_daily_backfill_report.md"
PENDING_MAIL = DATA / "pending_mail.json"
MASTER_RDB_FREEZE = DATA / "master_rdb_migration_freeze.json"
OPS_METRICS_DASHBOARD = DATA / "ops_metrics_dashboard.html"
QUOTA_LIMIT_RE = re.compile(
    r"quotaExceeded|dailyLimitExceeded|rateLimitExceeded|userRateLimitExceeded|Too Many Requests",
    re.I,
)

def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def master_rdb_legacy_song_freeze():
    return is_group_frozen(load_policy(MASTER_RDB_FREEZE), "legacy_song_occurrence_generation")


def guard_master_rdb_freeze(args):
    if not master_rdb_legacy_song_freeze() or args.ignore_migration_freeze:
        return
    if args.commit or args.push:
        raise SystemExit(
            "master RDB migration freeze is active; "
            "run_daily_youtube_backfill.py must not commit/push during Ph1. "
            "Use --dry-run or omit --commit/--push, or pass "
            "--ignore-migration-freeze after an explicit migration decision."
        )


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def run_command(args):
    result = subprocess.run(args, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(
            f"{' '.join(args)} failed with {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result.stdout.strip()


def http_error_body(exc):
    try:
        return exc.read().decode("utf-8", "replace")
    except Exception:
        return ""


def is_quota_limited_http_error(exc, body=""):
    if exc.code == 429:
        return True
    if exc.code != 403:
        return False
    return bool(QUOTA_LIMIT_RE.search(body or str(exc)))


def quota_error_message(exc, body=""):
    reason = ""
    match = QUOTA_LIMIT_RE.search(body or "")
    if match:
        reason = f" ({match.group(0)})"
    return f"HTTP Error {exc.code}: {exc.reason}{reason}"


def event_dates(row):
    dates = []
    for key in ["public_date", "public_date_end"]:
        if row.get(key):
            dates.append(row[key])
    dates.extend(row.get("last_seen_dates") or [])
    return list(dict.fromkeys([date for date in dates if date]))


def has_month(row, month):
    pattern = re.compile(rf"^\d{{4}}-{month:02d}-\d{{2}}$")
    return any(isinstance(date, str) and pattern.match(date) for date in event_dates(row))


def min_month_day(row, month):
    days = []
    for value in event_dates(row):
        match = re.match(rf"^\d{{4}}-{month:02d}-(\d{{2}})$", value)
        if match:
            days.append(int(match.group(1)))
    return min(days) if days else 99


def selected_queue_ids(candidates):
    return {
        row.get("queue_id")
        for row in candidates.get("selected_queue_rows") or []
        if row.get("queue_id")
    }


def candidate_stats_by_queue(candidates):
    stats = {}
    for row in candidates.get("candidates") or []:
        queue_id = row.get("queue_id")
        if not queue_id:
            continue
        current = stats.setdefault(queue_id, {"candidate_count": 0, "strong_count": 0, "review_count": 0})
        current["candidate_count"] += 1
        if row.get("status") == "strong":
            current["strong_count"] += 1
        elif row.get("status") == "review":
            current["review_count"] += 1
    return stats


def sort_key(month):
    def key(row):
        priority_order = {"high": 0, "medium": 1, "low": 2}
        return (
            priority_order.get(row.get("priority"), 9),
            -row.get("priority_score", 0),
            min_month_day(row, month),
            -row.get("target_year", 0),
            row.get("event_name") or "",
            row.get("venue") or "",
        )
    return key


def retry_sort_key(month, stats):
    def key(row):
        row_stats = stats.get(row.get("queue_id")) or {}
        priority_order = {"high": 0, "medium": 1, "low": 2}
        return (
            row_stats.get("strong_count", 0),
            row_stats.get("review_count", 0),
            row_stats.get("candidate_count", 0),
            priority_order.get(row.get("priority"), 9),
            -row.get("priority_score", 0),
            min_month_day(row, month),
            -row.get("target_year", 0),
            row.get("event_name") or "",
            row.get("venue") or "",
        )
    return key


def retryable_rows(queue, candidates, month, attempted_queue_ids, min_candidates):
    seen = selected_queue_ids(candidates)
    stats = candidate_stats_by_queue(candidates)
    rows = []
    for row in queue.get("rows") or []:
        queue_id = row.get("queue_id")
        if queue_id not in seen or queue_id in attempted_queue_ids or not has_month(row, month):
            continue
        row_stats = stats.get(queue_id) or {}
        if row_stats.get("strong_count", 0) > 0:
            continue
        if row_stats.get("candidate_count", 0) >= min_candidates:
            continue
        rows.append(row)
    rows.sort(key=retry_sort_key(month, stats))
    return rows


def next_rows(queue, candidates, month, limit, retry_selected=False, retry_min_candidates=10, attempted_queue_ids=None):
    attempted_queue_ids = set(attempted_queue_ids or [])
    seen = selected_queue_ids(candidates)
    rows = [
        row for row in queue.get("rows") or []
        if row.get("queue_id") not in seen
        and row.get("queue_id") not in attempted_queue_ids
        and has_month(row, month)
    ]
    rows.sort(key=sort_key(month))
    if rows or not retry_selected:
        return rows[:limit], rows
    retry_rows = retryable_rows(queue, candidates, month, attempted_queue_ids, retry_min_candidates)
    return retry_rows[:limit], retry_rows


def month_sequence(start_month, focus_months=None):
    if focus_months:
        months = []
        for month in focus_months:
            if month not in months:
                months.append(month)
        return months
    return list(range(start_month, 13)) + list(range(1, start_month))


def first_month_with_rows(queue, candidates, start_month, limit, focus_months=None, retry_selected=False, retry_min_candidates=10):
    months = month_sequence(start_month, focus_months)
    for month in months:
        selected, _remaining = next_rows(
            queue,
            candidates,
            month,
            limit,
            retry_selected=retry_selected,
            retry_min_candidates=retry_min_candidates,
        )
        if selected:
            return month
    return start_month


def estimated_search_calls(rows):
    return sum(min(len(row.get("search_queries") or []), 2) for row in rows)


def remaining_rows_count(queue, candidates, args, attempted_queue_ids=None):
    total = 0
    for month in month_sequence(args.month, args.focus_months):
        _selected, remaining = next_rows(
            queue,
            candidates,
            month,
            args.limit,
            retry_selected=args.retry_selected,
            retry_min_candidates=args.retry_min_candidates,
            attempted_queue_ids=attempted_queue_ids,
        )
        total += len(remaining)
    return total


def next_rows_for_args(queue, candidates, args, attempted_queue_ids=None):
    for month in month_sequence(args.month, args.focus_months):
        selected, remaining = next_rows(
            queue,
            candidates,
            month,
            args.limit,
            retry_selected=args.retry_selected,
            retry_min_candidates=args.retry_min_candidates,
            attempted_queue_ids=attempted_queue_ids,
        )
        if selected:
            return month, selected, remaining
    return args.month, [], []


def regenerate_outputs(month, target_year):
    commands = [
        ["python3", "-m", "youtube_backfill.build_event_occurrence_backfill_plan"],
        ["python3", "-m", "youtube_backfill.build_low_confidence_backfill_review"],
        ["python3", "-m", "youtube_backfill.apply_event_occurrence_backfill_plan"],
        ["python3", "-m", "youtube_backfill.build_event_schedule_rules", "--target-year", str(target_year)],
        ["python3", "-m", "youtube_backfill.build_event_date_predictions", "--target-year", str(target_year)],
        ["python3", "build_song_occurrences.py"],
        ["python3", "export_public_events.py"],
        [
            "python3",
            "-m",
            "youtube_backfill.build_month_youtube_backfill_queue",
            "--month",
            str(month),
            "--out-json",
            f"data/month_{month:02d}_youtube_backfill_queue.json",
            "--out-md",
            f"data/month_{month:02d}_youtube_backfill_queue.md",
        ],
    ]
    return [run_command(command) for command in commands]


def collect_ops_metrics():
    return run_command(["python3", "-m", "review_console_ops.collect_ops_metrics"])


def open_ops_metrics_dashboard():
    if OPS_METRICS_DASHBOARD.exists():
        target = str(OPS_METRICS_DASHBOARD.resolve())
        for command in [
            ["open", "-a", "Google Chrome", target],
            ["open", "-a", "Safari", target],
            ["open", target],
        ]:
            result = subprocess.run(command, text=True, capture_output=True)
            if result.returncode == 0:
                return "opened:" + " ".join(command[1:-1] or ["default"])
        return "open_failed"
    return "dashboard_not_found"


def render_report(report):
    lines = [
        "# YouTube日次バックフィル",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- status: {report['status']}",
        f"- month: {report['month']}",
        f"- selected_rows: {report['selected_rows']}",
        f"- completed_batches: {report.get('completed_batches', 0)}",
        f"- remaining_rows_before: {report['remaining_rows_before']}",
        f"- remaining_rows_after: {report.get('remaining_rows_after', report['remaining_rows_before'])}",
        f"- estimated_search_calls: {report['estimated_search_calls']}",
        f"- candidates_before: {report.get('candidates_before', 0)}",
        f"- candidates_after: {report.get('candidates_after', 0)}",
        f"- strong_after: {report.get('strong_after', 0)}",
        f"- review_after: {report.get('review_after', 0)}",
        f"- schedule_rule_count: {report.get('schedule_rule_count', 0)}",
        f"- schedule_rule_confidence_counts: {report.get('schedule_rule_confidence_counts', {})}",
        f"- schedule_rule_axis_counts: {report.get('schedule_rule_axis_counts', {})}",
        "",
    ]
    if report.get("error"):
        lines.extend(["## error", "", report["error"], ""])
    if report.get("selected"):
        lines.extend([
            "## selected",
            "",
            "| priority | score | year | event | venue | dates |",
            "| --- | ---: | ---: | --- | --- | --- |",
        ])
        for row in report["selected"]:
            lines.append(
                f"| {row.get('priority')} | {row.get('priority_score')} | {row.get('target_year')} | "
                f"{row.get('event_name')} | {row.get('venue')} | {', '.join(event_dates(row))} |"
            )
        lines.append("")
    if report.get("batches"):
        lines.extend([
            "## batches",
            "",
            "| batch | selected | candidates | strong | review |",
            "| ---: | ---: | ---: | ---: | ---: |",
        ])
        for row in report["batches"]:
            lines.append(
                f"| {row.get('batch')} | {row.get('selected_rows')} | "
                f"{row.get('candidate_count')} | {row.get('strong_count')} | {row.get('review_count')} |"
            )
        lines.append("")
    return "\n".join(lines)


def mail_text(report):
    if report["status"] in {"quota_limited", "harvested_until_quota_limited"}:
        lead = "YouTube APIのquota制限で止まりました。今日は追加収集せず、明日以降に再試行します。"
    elif report["status"] == "no_rows":
        lead = f"{report['month']}月の未処理YouTube候補はありません。"
    elif report["status"] == "dry_run":
        lead = "YouTube日次バックフィルのdry-runです。APIは使っていません。"
    else:
        lead = "YouTube日次バックフィルを実行しました。"
    return "\n".join([
        lead,
        "",
        f"対象月: {report['month']}月",
        f"選択件数: {report['selected_rows']}",
        f"実行前の残り: {report['remaining_rows_before']}",
        f"実行後の残り: {report.get('remaining_rows_after', report['remaining_rows_before'])}",
        f"完了バッチ: {report.get('completed_batches', 0)}",
        f"推定検索数: {report['estimated_search_calls']}",
        f"候補数: {report.get('candidates_before', 0)} -> {report.get('candidates_after', 0)}",
        f"strong: {report.get('strong_after', 0)} / review: {report.get('review_after', 0)}",
        f"開催パターン分類: {report.get('schedule_rule_count', 0)}件",
        "",
        "詳細: data/youtube_daily_backfill_report.md",
    ])


def write_pending_mail(report):
    plain = mail_text(report)
    write_json(PENDING_MAIL, {
        "subject": f"盆助 YouTube日次チェック: {report['status']}",
        "plain": plain,
        "html": "<pre>" + plain.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") + "</pre>",
    })


def attach_schedule_rule_summary(report):
    rules = load_json(SCHEDULE_RULES, {})
    summary = rules.get("summary") or {}
    report["schedule_rule_count"] = summary.get("rule_count", 0)
    report["schedule_rule_confidence_counts"] = summary.get("confidence_counts", {})
    report["schedule_rule_axis_counts"] = summary.get("axis_counts", {})
    report["schedule_rule_warning_counts"] = summary.get("warning_counts", {})


def git_commit_and_push(report, push):
    paths = [
        "data/youtube_daily_backfill_report.json",
        "data/youtube_daily_backfill_report.md",
        "data/pending_mail.json",
        "data/youtube_year_backfill_candidates.json",
        "data/youtube_year_backfill_candidates.md",
        "data/event_occurrence_backfill_plan.json",
        "data/event_occurrence_backfill_plan.md",
        "data/event_occurrence_observations.json",
        "data/event_occurrence_observations.md",
        "data/low_confidence_backfill_review.md",
        "data/event_schedule_rules.json",
        "data/event_schedule_rules.md",
        "data/event_date_predictions.json",
        "data/event_date_predictions.md",
        "data/public/events_public.json",
        "data/public/events_public.js",
        "data/public_date_prediction_apply_result.json",
        "data/public_historical_reference_dry_run.json",
        "data/public_season_hint_dry_run.json",
        "data/song_occurrences.json",
        "data/song_prediction_snapshots.json",
        "data/public/event_song_occurrences_public.json",
        "data/public/event_songs_public.json",
        "data/ops_metrics_history.jsonl",
        "data/ops_metrics_latest.md",
        "data/ops_metrics_dashboard.html",
        f"data/month_{report['month']:02d}_youtube_backfill_queue.json",
        f"data/month_{report['month']:02d}_youtube_backfill_queue.md",
    ]
    existing_paths = [path for path in paths if Path(path).exists()]
    run_command(["git", "add", *existing_paths])
    status = run_command(["git", "status", "--short"])
    if not status:
        return "no_changes"
    run_command(["git", "commit", "-m", f"Run daily YouTube backfill ({report['status']})"])
    if push:
        run_command(["git", "pull", "--rebase"])
        run_command(["git", "push"])
    return "committed"


def run_harvest_batches(queue, existing, args, api_key):
    current = existing
    selected_rows = []
    batches = []
    completed_batches = 0
    estimated_calls = 0
    first_remaining_count = None
    status = "no_rows"
    error = ""
    attempted_queue_ids = set()

    while True:
        selected_month, selected, remaining = next_rows_for_args(queue, current, args, attempted_queue_ids)
        if first_remaining_count is None:
            first_remaining_count = remaining_rows_count(queue, current, args, attempted_queue_ids)
        if not selected:
            status = "no_rows" if completed_batches == 0 else "harvested_all_available"
            break

        selected_rows.extend(selected)
        estimated_calls += estimated_search_calls(selected)
        if args.dry_run:
            status = "dry_run"
            break

        try:
            fresh = harvest_mod.harvest(
                {**queue, "rows": selected},
                api_key=api_key,
                limit=len(selected),
                max_results=args.max_results,
                priorities=["high", "medium", "low"],
            )
        except urllib.error.HTTPError as exc:
            body = http_error_body(exc)
            if not is_quota_limited_http_error(exc, body):
                raise
            status = "quota_limited" if completed_batches == 0 else "harvested_until_quota_limited"
            error = quota_error_message(exc, body)
            break

        current = harvest_mod.merge_harvests(current, fresh)
        attempted_queue_ids.update(row.get("queue_id") for row in selected if row.get("queue_id"))
        harvest_mod.atomic_write_json(harvest_mod.OUT, current)
        harvest_mod.atomic_write_text(harvest_mod.MD_OUT, harvest_mod.render_markdown(current))
        completed_batches += 1
        summary = current.get("summary") or {}
        batches.append({
            "batch": completed_batches,
            "month": selected_month,
            "selected_rows": len(selected),
            "queue_ids": [row.get("queue_id") for row in selected if row.get("queue_id")],
            "fresh_summary": fresh.get("summary") or {},
            "candidate_count": summary.get("candidate_count", 0),
            "strong_count": summary.get("strong_count", 0),
            "review_count": summary.get("review_count", 0),
        })

        if not args.until_quota_limited:
            status = "harvested"
            break
        if args.max_batches and completed_batches >= args.max_batches:
            status = "harvested_max_batches"
            break

    remaining_after = remaining_rows_count(queue, current, args, attempted_queue_ids)
    return {
        "status": status,
        "error": error,
        "current": current,
        "selected": selected_rows,
        "selected_rows": len(selected_rows),
        "remaining_rows_before": first_remaining_count or 0,
        "remaining_rows_after": remaining_after,
        "estimated_search_calls": estimated_calls,
        "completed_batches": completed_batches,
        "batches": batches,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", type=int, default=7)
    parser.add_argument("--target-year", type=int, required=True)
    parser.add_argument("--auto-next-month", action="store_true", help="Use the next month with unprocessed rows, starting at --month.")
    parser.add_argument("--focus-month", action="append", type=int, dest="focus_months", help="Limit automatic selection to this month. Repeatable.")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--retry-selected", action="store_true", help="Retry already selected rows when they still have thin evidence.")
    parser.add_argument("--retry-min-candidates", type=int, default=10)
    parser.add_argument("--until-quota-limited", action="store_true")
    parser.add_argument("--max-batches", type=int, default=0, help="Safety cap for --until-quota-limited. 0 means no cap.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--mail-reminder", action="store_true")
    parser.add_argument("--open-dashboard", action="store_true")
    parser.add_argument("--ignore-migration-freeze", action="store_true")
    args = parser.parse_args()
    args.target_year = normalize_target_year(args.target_year)
    guard_master_rdb_freeze(args)

    queue = load_json(QUEUE, {})
    existing = load_json(CANDIDATES, {})
    if args.auto_next_month:
        args.month = first_month_with_rows(
            queue,
            existing,
            args.month,
            args.limit,
            focus_months=args.focus_months,
            retry_selected=args.retry_selected,
            retry_min_candidates=args.retry_min_candidates,
        )
    before_count = len(existing.get("candidates") or [])
    report = {
        "generated_by": "run_daily_youtube_backfill.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "started",
        "month": args.month,
        "target_year": args.target_year,
        "selected_rows": 0,
        "remaining_rows_before": 0,
        "remaining_rows_after": 0,
        "estimated_search_calls": 0,
        "candidates_before": before_count,
        "selected": [],
        "completed_batches": 0,
        "batches": [],
    }

    if args.dry_run:
        api_key = ""
    else:
        api_key = load_env_value("YOUTUBE_DATA_API_KEY", ".env")
        if not api_key:
            raise SystemExit("YOUTUBE_DATA_API_KEY is not set")

    result = run_harvest_batches(queue, existing, args, api_key)
    report.update({
        "status": result["status"],
        "selected_rows": result["selected_rows"],
        "remaining_rows_before": result["remaining_rows_before"],
        "remaining_rows_after": result["remaining_rows_after"],
        "estimated_search_calls": result["estimated_search_calls"],
        "selected": result["selected"],
        "completed_batches": result["completed_batches"],
        "batches": result["batches"],
    })
    if result["error"]:
        report["error"] = result["error"]
    if report["status"] not in {"no_rows", "dry_run"}:
        report["regenerated"] = regenerate_outputs(args.month, args.target_year)

    if "candidates_after" not in report:
        current = load_json(CANDIDATES, {})
        summary = current.get("summary") or {}
        report["candidates_after"] = summary.get("candidate_count", before_count)
        report["strong_after"] = summary.get("strong_count", 0)
        report["review_after"] = summary.get("review_count", 0)
    attach_schedule_rule_summary(report)

    write_json(REPORT_JSON, report)
    REPORT_MD.write_text(render_report(report), encoding="utf-8")
    if args.mail_reminder:
        write_pending_mail(report)
    report["ops_metrics"] = collect_ops_metrics()
    if args.open_dashboard:
        report["ops_metrics_dashboard"] = open_ops_metrics_dashboard()
    write_json(REPORT_JSON, report)
    REPORT_MD.write_text(render_report(report), encoding="utf-8")
    if args.commit:
        report["git"] = "commit_requested"
        write_json(REPORT_JSON, report)
        REPORT_MD.write_text(render_report(report), encoding="utf-8")
        git_result = git_commit_and_push(report, args.push)
        print(f"daily youtube backfill git: {git_result}")

    print(
        "daily youtube backfill: "
        f"status={report['status']} month={report['month']} "
        f"selected={report['selected_rows']} remaining={report['remaining_rows_before']} "
        f"candidates={report['candidates_before']}->{report['candidates_after']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
