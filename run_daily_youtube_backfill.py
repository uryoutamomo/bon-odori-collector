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

from backfill_youtube_descriptions import load_env_value
import harvest_youtube_year_backfill as harvest_mod


DATA = Path("data")
QUEUE = DATA / "youtube_year_backfill_queue.json"
CANDIDATES = DATA / "youtube_year_backfill_candidates.json"
REPORT_JSON = DATA / "youtube_daily_backfill_report.json"
REPORT_MD = DATA / "youtube_daily_backfill_report.md"
PENDING_MAIL = DATA / "pending_mail.json"


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


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


def sort_key(month):
    def key(row):
        priority_order = {"high": 0, "medium": 1, "low": 2}
        return (
            priority_order.get(row.get("priority"), 9),
            -row.get("priority_score", 0),
            min_month_day(row, month),
            row.get("target_year", 9999),
            row.get("event_name") or "",
            row.get("venue") or "",
        )
    return key


def next_rows(queue, candidates, month, limit):
    seen = selected_queue_ids(candidates)
    rows = [
        row for row in queue.get("rows") or []
        if row.get("queue_id") not in seen and has_month(row, month)
    ]
    rows.sort(key=sort_key(month))
    return rows[:limit], rows


def estimated_search_calls(rows):
    return sum(min(len(row.get("search_queries") or []), 2) for row in rows)


def regenerate_outputs(month):
    commands = [
        ["python3", "build_event_occurrence_backfill_plan.py"],
        ["python3", "build_low_confidence_backfill_review.py"],
        ["python3", "apply_event_occurrence_backfill_plan.py"],
        ["python3", "build_event_date_predictions.py", "--target-year", "2026"],
        ["python3", "apply_public_date_predictions.py"],
        [
            "python3",
            "build_month_youtube_backfill_queue.py",
            "--month",
            str(month),
            "--out-json",
            f"data/month_{month:02d}_youtube_backfill_queue.json",
            "--out-md",
            f"data/month_{month:02d}_youtube_backfill_queue.md",
        ],
    ]
    return [run_command(command) for command in commands]


def render_report(report):
    lines = [
        "# YouTube日次バックフィル",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- status: {report['status']}",
        f"- month: {report['month']}",
        f"- selected_rows: {report['selected_rows']}",
        f"- remaining_rows_before: {report['remaining_rows_before']}",
        f"- estimated_search_calls: {report['estimated_search_calls']}",
        f"- candidates_before: {report.get('candidates_before', 0)}",
        f"- candidates_after: {report.get('candidates_after', 0)}",
        f"- strong_after: {report.get('strong_after', 0)}",
        f"- review_after: {report.get('review_after', 0)}",
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
    return "\n".join(lines)


def mail_text(report):
    if report["status"] == "quota_limited":
        lead = "YouTube APIは429で止まりました。今日は追加収集せず、明日以降に再試行します。"
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
        f"推定検索数: {report['estimated_search_calls']}",
        f"候補数: {report.get('candidates_before', 0)} -> {report.get('candidates_after', 0)}",
        f"strong: {report.get('strong_after', 0)} / review: {report.get('review_after', 0)}",
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
        "data/event_date_predictions.json",
        "data/event_date_predictions.md",
        "data/public/events_public.json",
        "data/public/events_public.js",
        "data/public_date_prediction_apply_result.json",
        f"data/month_{report['month']:02d}_youtube_backfill_queue.json",
        f"data/month_{report['month']:02d}_youtube_backfill_queue.md",
    ]
    run_command(["git", "add", *paths])
    status = run_command(["git", "status", "--short"])
    if not status:
        return "no_changes"
    run_command(["git", "commit", "-m", f"Run daily YouTube backfill ({report['status']})"])
    if push:
        run_command(["git", "pull", "--rebase"])
        run_command(["git", "push"])
    return "committed"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", type=int, default=7)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--mail-reminder", action="store_true")
    args = parser.parse_args()

    queue = load_json(QUEUE, {})
    existing = load_json(CANDIDATES, {})
    selected, remaining = next_rows(queue, existing, args.month, args.limit)
    before_count = len(existing.get("candidates") or [])
    report = {
        "generated_by": "run_daily_youtube_backfill.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "started",
        "month": args.month,
        "selected_rows": len(selected),
        "remaining_rows_before": len(remaining),
        "estimated_search_calls": estimated_search_calls(selected),
        "candidates_before": before_count,
        "selected": selected,
    }

    if not selected:
        report["status"] = "no_rows"
    elif args.dry_run:
        report["status"] = "dry_run"
    else:
        api_key = load_env_value("YOUTUBE_DATA_API_KEY", ".env")
        if not api_key:
            raise SystemExit("YOUTUBE_DATA_API_KEY is not set")
        try:
            fresh = harvest_mod.harvest(
                {**queue, "rows": selected},
                api_key=api_key,
                limit=len(selected),
                max_results=args.max_results,
                priorities=["high", "medium", "low"],
            )
            merged = harvest_mod.merge_harvests(existing, fresh)
            harvest_mod.atomic_write_json(harvest_mod.OUT, merged)
            harvest_mod.atomic_write_text(harvest_mod.MD_OUT, harvest_mod.render_markdown(merged))
            report["status"] = "harvested"
            report["fresh_summary"] = fresh["summary"]
            report["candidates_after"] = merged["summary"]["candidate_count"]
            report["strong_after"] = merged["summary"]["strong_count"]
            report["review_after"] = merged["summary"]["review_count"]
            report["regenerated"] = regenerate_outputs(args.month)
        except urllib.error.HTTPError as exc:
            if exc.code != 429:
                raise
            report["status"] = "quota_limited"
            report["error"] = "HTTP Error 429: Too Many Requests"

    if "candidates_after" not in report:
        current = load_json(CANDIDATES, {})
        summary = current.get("summary") or {}
        report["candidates_after"] = summary.get("candidate_count", before_count)
        report["strong_after"] = summary.get("strong_count", 0)
        report["review_after"] = summary.get("review_count", 0)

    write_json(REPORT_JSON, report)
    REPORT_MD.write_text(render_report(report), encoding="utf-8")
    if args.mail_reminder:
        write_pending_mail(report)
    if args.commit:
        report["git"] = git_commit_and_push(report, args.push)
        write_json(REPORT_JSON, report)
        REPORT_MD.write_text(render_report(report), encoding="utf-8")

    print(
        "daily youtube backfill: "
        f"status={report['status']} month={report['month']} "
        f"selected={report['selected_rows']} remaining={report['remaining_rows_before']} "
        f"candidates={report['candidates_before']}->{report['candidates_after']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
