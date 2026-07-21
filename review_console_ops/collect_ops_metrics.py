"""Collect daily operations metrics and render a static dashboard."""

import argparse
import html
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DATA = Path("data")
DEFAULT_HISTORY = DATA / "ops_metrics_history.jsonl"
DEFAULT_LATEST_MD = DATA / "ops_metrics_latest.md"
DEFAULT_DASHBOARD = DATA / "ops_metrics_dashboard.html"

try:
    JST = ZoneInfo("Asia/Tokyo")
except ZoneInfoNotFoundError:
    JST = timezone(timedelta(hours=9))


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError:
        return default


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def int_value(value, default=0):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def nested_counts(payload):
    if not isinstance(payload, dict):
        return {}
    report = payload.get("report")
    if isinstance(report, dict):
        return report
    summary = payload.get("summary")
    if isinstance(summary, dict):
        return summary
    return payload


def list_len(payload, key):
    if isinstance(payload, dict) and isinstance(payload.get(key), list):
        return len(payload[key])
    return 0


def parse_low_confidence_review(path):
    text = Path(path).read_text(encoding="utf-8") if Path(path).exists() else ""
    rows = decided = decisions_total = 0
    for key, attr in [
        ("rows", "rows"),
        ("decided_in_rows", "decided"),
        ("decisions_total", "decisions_total"),
    ]:
        match = re.search(rf"- {re.escape(key)}:\s*(\d+)", text)
        if match:
            if attr == "rows":
                rows = int(match.group(1))
            elif attr == "decided":
                decided = int(match.group(1))
            else:
                decisions_total = int(match.group(1))
    return {
        "low_confidence_review_rows": rows,
        "low_confidence_review_decided_rows": decided,
        "low_confidence_review_unreviewed_rows": max(0, rows - decided),
        "low_confidence_review_decisions_total": decisions_total,
    }


def month_queue_counts(data_dir):
    counts = {}
    for path in sorted(Path(data_dir).glob("month_??_youtube_backfill_queue.json")):
        match = re.search(r"month_(\d{2})_youtube_backfill_queue\.json$", path.name)
        if not match:
            continue
        payload = load_json(path, {})
        summary = nested_counts(payload)
        counts[match.group(1)] = int_value(summary.get("items"))
    return counts


def file_inventory_counts(data_dir):
    data_dir = Path(data_dir)
    files = [
        path for path in data_dir.rglob("*")
        if path.is_file() and path.suffix in {".json", ".jsonl", ".md", ".sqlite", ".html"}
    ]
    by_suffix = {}
    for path in files:
        by_suffix[path.suffix.lstrip(".") or "none"] = by_suffix.get(path.suffix.lstrip(".") or "none", 0) + 1
    return {
        "data_file_count": len(files),
        "data_file_counts_by_suffix": dict(sorted(by_suffix.items())),
    }


def collect_metrics(data_dir=DATA, now=None):
    data_dir = Path(data_dir)
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(JST).date().isoformat()

    youtube_report = load_json(data_dir / "youtube_daily_backfill_report.json", {})
    youtube_candidates = load_json(data_dir / "youtube_year_backfill_candidates.json", {})
    candidate_summary = nested_counts(youtube_candidates)
    candidate_status_counts = candidate_summary.get("status_counts") or {}
    youtube_queue = load_json(data_dir / "youtube_year_backfill_queue.json", {})
    queue_summary = nested_counts(youtube_queue)
    backfill_plan = load_json(data_dir / "event_occurrence_backfill_plan.json", {})
    backfill_summary = nested_counts(backfill_plan)
    observations = load_json(data_dir / "event_occurrence_observations.json", {})
    observation_summary = nested_counts(observations)
    predictions = load_json(data_dir / "event_date_predictions.json", {})
    prediction_summary = nested_counts(predictions)
    public_predictions = load_json(data_dir / "public_date_prediction_apply_result.json", {})
    historical_refs = load_json(data_dir / "public_historical_reference_dry_run.json", {})
    season_hints = load_json(data_dir / "public_season_hint_dry_run.json", {})
    review_queue = load_json(data_dir / "youtube_year_backfill_review_queue.json", {})
    review_summary = nested_counts(review_queue)
    registered_queue = load_json(data_dir / "registered_event_investigation_queue.json", {})
    registered_summary = nested_counts(registered_queue)
    missing_venue = load_json(data_dir / "missing_occurrence_venue_review_post_venue_fixes.json", {})
    missing_venue_summary = nested_counts(missing_venue)
    missing_source = load_json(data_dir / "missing_source_url_review_post_apply.json", {})
    missing_source_summary = nested_counts(missing_source)
    date_fill = load_json(data_dir / "reviewed_shinagawa_date_fills_apply_report.json", {})
    date_fill_summary = nested_counts(date_fill)

    metrics = {
        "snapshot_date": today,
        "collected_at": now.isoformat(),
        "youtube_run_generated_at": youtube_report.get("generated_at") or "",
        "youtube_run_status": youtube_report.get("status") or "",
        "youtube_run_selected_rows": int_value(youtube_report.get("selected_rows")),
        "youtube_run_completed_batches": int_value(youtube_report.get("completed_batches")),
        "youtube_run_remaining_before": int_value(youtube_report.get("remaining_rows_before")),
        "youtube_run_remaining_after": int_value(youtube_report.get("remaining_rows_after")),
        "youtube_run_estimated_search_calls": int_value(youtube_report.get("estimated_search_calls")),
        "youtube_candidates_total": int_value(candidate_summary.get("candidate_count"), list_len(youtube_candidates, "candidates")),
        "youtube_candidates_strong": int_value(candidate_summary.get("strong_count"), int_value(candidate_status_counts.get("strong"))),
        "youtube_candidates_review": int_value(candidate_summary.get("review_count"), int_value(candidate_status_counts.get("review"))),
        "youtube_candidates_weak": int_value(candidate_status_counts.get("weak")),
        "youtube_selected_queue_rows": list_len(youtube_candidates, "selected_queue_rows"),
        "youtube_year_queue_total": int_value(queue_summary.get("items")),
        "youtube_month_queue_counts": month_queue_counts(data_dir),
        "youtube_review_queue_groups": int_value(review_summary.get("group_count")),
        "youtube_review_queue_undecided_groups": int_value(review_summary.get("undecided_group_count")),
        "youtube_review_queue_videos": int_value(review_summary.get("video_count")),
        "youtube_review_queue_undecided_videos": int_value(review_summary.get("undecided_video_count")),
        "backfill_plan_observations": int_value(backfill_summary.get("observation_count")),
        "backfill_plan_source_videos": int_value(backfill_summary.get("source_video_count")),
        "backfill_plan_excluded_low": int_value(backfill_summary.get("excluded_low_observation_count")),
        "backfill_plan_manual_accepted_low": int_value(backfill_summary.get("manual_accepted_low_observation_count")),
        "event_observations_total": int_value(observation_summary.get("observation_count")),
        "event_observation_series": int_value(observation_summary.get("series_count")),
        "event_observation_source_videos": int_value(observation_summary.get("source_video_count")),
        "event_observation_with_songs": int_value(observation_summary.get("observations_with_songs")),
        "date_predictions_total": int_value(prediction_summary.get("prediction_count")),
        "date_predictions_medium": int_value((prediction_summary.get("confidence_counts") or {}).get("medium")),
        "date_predictions_low": int_value((prediction_summary.get("confidence_counts") or {}).get("low")),
        "public_date_prediction_applied": int_value(public_predictions.get("applied_count")),
        "public_date_prediction_skipped": int_value(public_predictions.get("skipped_count")),
        "public_date_prediction_unmatched": int_value(public_predictions.get("unmatched_count")),
        "public_historical_reference_target": int_value(historical_refs.get("target_count")),
        "public_historical_reference_applied": int_value(historical_refs.get("applied_count")),
        "public_historical_reference_slide": int_value(historical_refs.get("slide_count")),
        "public_historical_reference_reference_only": int_value(historical_refs.get("reference_only_count")),
        "public_season_hint_target": int_value(season_hints.get("target_count")),
        "public_season_hint_applied": int_value(season_hints.get("applied_count")),
        "public_season_hint_skipped": int_value(season_hints.get("skipped_count")),
        "registered_events_total": int_value(registered_summary.get("registered_event_count")),
        "registered_events_incomplete": int_value(registered_summary.get("incomplete_event_count")),
        "registered_events_primary_unconfirmed_incomplete": int_value(registered_summary.get("primary_unconfirmed_incomplete_count")),
        "missing_venue_occurrences": int_value(missing_venue_summary.get("missing_venue_occurrence_count")),
        "missing_source_url_occurrences": int_value(missing_source_summary.get("missing_source_url_occurrence_count")),
        "missing_date_start_count": int_value(date_fill_summary.get("missing_date_start_count")),
    }
    metrics.update(parse_low_confidence_review(data_dir / "low_confidence_backfill_review.md"))
    metrics.update(file_inventory_counts(data_dir))
    return metrics


def merge_history(existing, current, replace_same_date=True):
    if not replace_same_date:
        return existing + [current]
    rows = [row for row in existing if row.get("snapshot_date") != current.get("snapshot_date")]
    rows.append(current)
    rows.sort(key=lambda row: (row.get("snapshot_date") or "", row.get("collected_at") or ""))
    return rows


def previous_row(rows, current):
    current_date = current.get("snapshot_date")
    earlier = [row for row in rows if (row.get("snapshot_date") or "") < current_date]
    if not earlier:
        return None
    return sorted(earlier, key=lambda row: (row.get("snapshot_date") or "", row.get("collected_at") or ""))[-1]


def delta(current, previous, key):
    if not previous:
        return ""
    value = int_value(current.get(key)) - int_value(previous.get(key))
    if value > 0:
        return f"+{value}"
    return str(value)


LATEST_ROWS = [
    ("今回選択", "youtube_run_selected_rows"),
    ("完了バッチ", "youtube_run_completed_batches"),
    ("実行前の残り", "youtube_run_remaining_before"),
    ("今回対象の残り", "youtube_run_remaining_after"),
    ("推定検索数", "youtube_run_estimated_search_calls"),
    ("YouTube候補", "youtube_candidates_total"),
    ("strong", "youtube_candidates_strong"),
    ("review", "youtube_candidates_review"),
    ("weak", "youtube_candidates_weak"),
    ("低信頼未判断", "low_confidence_review_unreviewed_rows"),
    ("日付予測適用", "public_date_prediction_applied"),
    ("過去実績表示", "public_historical_reference_applied"),
    ("季節ヒント", "public_season_hint_applied"),
    ("登録済み不完全", "registered_events_incomplete"),
    ("missing venue", "missing_venue_occurrences"),
    ("missing source URL", "missing_source_url_occurrences"),
    ("missing date_start", "missing_date_start_count"),
]


def render_latest_markdown(current, rows):
    previous = previous_row(rows, current)
    lines = [
        "# 運用メトリクス最新",
        "",
        f"- snapshot_date: {current.get('snapshot_date')}",
        f"- collected_at: {current.get('collected_at')}",
        f"- youtube_run_status: {current.get('youtube_run_status')}",
        f"- youtube_run_generated_at: {current.get('youtube_run_generated_at')}",
        "",
        "| 指標 | 現在 | 前回差分 |",
        "| --- | ---: | ---: |",
    ]
    for label, key in LATEST_ROWS:
        lines.append(f"| {label} | {int_value(current.get(key))} | {delta(current, previous, key)} |")
    month_counts = current.get("youtube_month_queue_counts") or {}
    if month_counts:
        lines.extend(["", "## 月別YouTubeキュー", ""])
        for month, count in sorted(month_counts.items()):
            lines.append(f"- {int(month)}月: {count}")
    lines.append("")
    return "\n".join(lines)


def series(rows, key):
    values = []
    for row in rows:
        value = row.get(key)
        if isinstance(value, (int, float)):
            values.append((row.get("snapshot_date") or "", float(value)))
    return values


def svg_line_chart(rows, keys, labels, colors, width=760, height=250):
    padding_left = 48
    padding_right = 18
    padding_top = 20
    padding_bottom = 34
    all_points = []
    for key in keys:
        all_points.extend(series(rows, key))
    if not all_points:
        return "<svg></svg>"
    dates = [row.get("snapshot_date") or "" for row in rows]
    dates = [date for index, date in enumerate(dates) if date and date not in dates[:index]]
    values = [value for _date, value in all_points]
    max_value = max(values) if values else 1
    min_value = min(0, min(values) if values else 0)
    if math.isclose(max_value, min_value):
        max_value += 1
    plot_w = width - padding_left - padding_right
    plot_h = height - padding_top - padding_bottom

    def x_for(date):
        if len(dates) <= 1:
            return padding_left + plot_w
        return padding_left + (dates.index(date) / (len(dates) - 1)) * plot_w

    def y_for(value):
        return padding_top + (max_value - value) / (max_value - min_value) * plot_h

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img">',
        f'<line x1="{padding_left}" y1="{padding_top}" x2="{padding_left}" y2="{height-padding_bottom}" class="axis"/>',
        f'<line x1="{padding_left}" y1="{height-padding_bottom}" x2="{width-padding_right}" y2="{height-padding_bottom}" class="axis"/>',
    ]
    for frac in [0, 0.25, 0.5, 0.75, 1]:
        value = min_value + (max_value - min_value) * frac
        y = y_for(value)
        parts.append(f'<line x1="{padding_left}" y1="{y:.1f}" x2="{width-padding_right}" y2="{y:.1f}" class="grid"/>')
        parts.append(f'<text x="8" y="{y+4:.1f}" class="tick">{int(round(value))}</text>')
    for key, label, color in zip(keys, labels, colors):
        pts = series(rows, key)
        if not pts:
            continue
        path = " ".join(
            f'{"M" if index == 0 else "L"} {x_for(date):.1f} {y_for(value):.1f}'
            for index, (date, value) in enumerate(pts)
        )
        parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.5"/>')
        for date, value in pts:
            parts.append(f'<circle cx="{x_for(date):.1f}" cy="{y_for(value):.1f}" r="3" fill="{color}"/>')
        parts.append(f'<text x="{width-padding_right-130}" y="{padding_top + 16 * keys.index(key):.1f}" fill="{color}" class="legend">{html.escape(label)}</text>')
    if dates:
        parts.append(f'<text x="{padding_left}" y="{height-10}" class="tick">{html.escape(dates[0])}</text>')
        parts.append(f'<text x="{width-padding_right-76}" y="{height-10}" class="tick">{html.escape(dates[-1])}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def svg_month_bars(current, width=760, height=230):
    counts = current.get("youtube_month_queue_counts") or {}
    if not counts:
        return "<svg></svg>"
    items = sorted((int(month), int_value(count)) for month, count in counts.items())
    max_value = max([count for _month, count in items] + [1])
    padding_left = 42
    padding_bottom = 32
    padding_top = 18
    plot_w = width - padding_left - 20
    plot_h = height - padding_top - padding_bottom
    bar_w = plot_w / max(1, len(items)) * 0.62
    gap = plot_w / max(1, len(items))
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img">',
        f'<line x1="{padding_left}" y1="{height-padding_bottom}" x2="{width-20}" y2="{height-padding_bottom}" class="axis"/>',
    ]
    for index, (month, count) in enumerate(items):
        x = padding_left + index * gap + (gap - bar_w) / 2
        bar_h = (count / max_value) * plot_h if max_value else 0
        y = height - padding_bottom - bar_h
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" rx="2" fill="#4f8f8b"/>')
        parts.append(f'<text x="{x + bar_w/2:.1f}" y="{y - 6:.1f}" text-anchor="middle" class="tick">{count}</text>')
        parts.append(f'<text x="{x + bar_w/2:.1f}" y="{height-10}" text-anchor="middle" class="tick">{month}月</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def status_explanation(status):
    labels = {
        "harvested_until_quota_limited": "YouTube APIの上限まで取得しました。",
        "quota_limited": "取得開始時点でYouTube APIの上限に当たりました。",
        "harvested": "予定分のYouTube取得が完了しました。",
        "harvested_max_batches": "安全上限までYouTube取得しました。",
        "harvested_all_available": "対象キューを取得しきりました。",
        "no_rows": "今日の条件では取得対象がありません。",
        "dry_run": "dry-runなのでAPI取得はしていません。",
    }
    return labels.get(status, "日次処理の状態を記録しています。")


def render_dashboard(rows):
    rows = sorted(rows, key=lambda row: (row.get("snapshot_date") or "", row.get("collected_at") or ""))
    current = rows[-1] if rows else {}
    previous = previous_row(rows, current) if current else None
    generated = html.escape(datetime.now(timezone.utc).isoformat())
    cards = [
        ("今回選択", "youtube_run_selected_rows", "この実行で検索対象にした行数"),
        ("完了バッチ", "youtube_run_completed_batches", "quota停止前に完了した検索単位"),
        ("YouTube候補", "youtube_candidates_total", "取得済み候補の総数"),
        ("review", "youtube_candidates_review", "自動採用には弱い候補"),
        ("今回対象の残り", "youtube_run_remaining_after", "日次実行で残った検索対象"),
        ("推定検索数", "youtube_run_estimated_search_calls", "今回試みたYouTube検索数の見積もり"),
        ("低信頼未判断", "low_confidence_review_unreviewed_rows", "手動判断待ち"),
        ("日付予測適用", "public_date_prediction_applied", "公開データに出た予測"),
        ("登録済み不完全", "registered_events_incomplete", "正本側の未整備"),
    ]
    card_html = []
    for label, key, help_text in cards:
        value = int_value(current.get(key))
        card_html.append(
            '<div class="metric">'
            f'<div class="metric-label">{html.escape(label)}</div>'
            f'<div class="metric-value">{value}</div>'
            f'<div class="metric-help">{html.escape(help_text)}</div>'
            "</div>"
        )
    candidate_delta = delta(current, previous, "youtube_candidates_total") if current else ""
    queue_delta = delta(current, previous, "youtube_run_remaining_after") if current else ""
    review_delta = delta(current, previous, "low_confidence_review_unreviewed_rows") if current else ""
    status_label = status_explanation(current.get("youtube_run_status", ""))
    run_selected = int_value(current.get("youtube_run_selected_rows"))
    run_batches = int_value(current.get("youtube_run_completed_batches"))
    run_before = int_value(current.get("youtube_run_remaining_before"))
    run_after = int_value(current.get("youtube_run_remaining_after"))
    run_searches = int_value(current.get("youtube_run_estimated_search_calls"))
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>盆踊り運用メトリクス</title>
<style>
:root {{
  color-scheme: light;
  --ink: #1f2933;
  --muted: #667085;
  --line: #d6dde5;
  --bg: #f5f7f9;
  --panel: #ffffff;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  letter-spacing: 0;
}}
main {{ max-width: 1120px; margin: 0 auto; padding: 28px 20px 48px; }}
h1 {{ margin: 0 0 6px; font-size: 28px; font-weight: 700; }}
h2 {{ margin: 0 0 14px; font-size: 18px; }}
.meta {{ color: var(--muted); font-size: 13px; margin-bottom: 20px; }}
.intro {{ background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 16px 18px; margin: 16px 0; }}
.intro p {{ margin: 0 0 10px; line-height: 1.7; }}
.intro p:last-child {{ margin-bottom: 0; }}
.guide-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 12px; }}
.guide-card {{ background: #f8fafc; border: 1px solid #e3e8ef; border-radius: 6px; padding: 12px; }}
.guide-card strong {{ display: block; margin-bottom: 4px; font-size: 14px; }}
.guide-card span {{ color: var(--muted); font-size: 13px; line-height: 1.55; }}
.grid {{ stroke: #e6ebf0; stroke-width: 1; }}
.axis {{ stroke: #9aa6b2; stroke-width: 1.2; }}
.tick {{ fill: #667085; font-size: 11px; }}
.legend {{ font-size: 12px; font-weight: 600; }}
.metrics {{ display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; margin: 18px 0; }}
.metric {{ background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 12px; min-height: 76px; }}
.metric-label {{ color: var(--muted); font-size: 12px; }}
.metric-value {{ font-size: 26px; font-weight: 700; margin-top: 8px; }}
.metric-help {{ color: var(--muted); font-size: 11px; line-height: 1.4; margin-top: 4px; }}
.panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 18px; margin-top: 14px; overflow-x: auto; }}
.panel-note {{ color: var(--muted); font-size: 13px; line-height: 1.65; margin: -4px 0 12px; max-width: 900px; }}
.reading-list {{ margin: 10px 0 0; padding-left: 18px; color: var(--muted); font-size: 13px; line-height: 1.7; }}
.reading-list strong {{ color: var(--ink); }}
svg {{ width: 100%; height: auto; display: block; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; background: var(--panel); }}
th, td {{ border-bottom: 1px solid var(--line); padding: 8px 10px; text-align: right; white-space: nowrap; }}
th:first-child, td:first-child {{ text-align: left; }}
th {{ color: var(--muted); font-weight: 600; }}
@media (max-width: 860px) {{
  .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  .guide-grid {{ grid-template-columns: 1fr; }}
  main {{ padding: 20px 12px 36px; }}
}}
</style>
</head>
<body>
<main>
  <h1>盆踊り運用メトリクス</h1>
  <div class="meta">生成: {generated} / 最新日: {html.escape(str(current.get("snapshot_date", "")))} / YouTube: {html.escape(str(current.get("youtube_run_status", "")))}</div>
  <section class="intro">
    <p>このページは、毎朝の収集と反映準備が進んでいるかを見るための運用メモです。検索順位やアクセス数ではなく、盆助のデータ作業が詰まっていないかを確認します。</p>
    <div class="guide-grid">
      <div class="guide-card"><strong>まず見る</strong><span>YouTube候補が増え、今回対象の残りが減っていれば収集は進んでいます。今日の候補差分は {html.escape(candidate_delta or "初回")}、残り差分は {html.escape(queue_delta or "初回")} です。</span></div>
      <div class="guide-card"><strong>詰まりを見る</strong><span>低信頼未判断や登録済み不完全が増えると、人手レビューや正本整備が必要です。低信頼未判断の差分は {html.escape(review_delta or "初回")} です。</span></div>
      <div class="guide-card"><strong>今日の状態</strong><span>{html.escape(status_label)} 選択 {run_selected} 件、完了 {run_batches} batches、残り {run_before} → {run_after}、推定検索 {run_searches} 件です。quota制限で止まるのは通常の停止条件で、途中までの取得結果は保存されています。</span></div>
    </div>
  </section>
  <section class="metrics">
    {''.join(card_html)}
  </section>
  <section class="panel">
    <h2>YouTube候補</h2>
    <p class="panel-note">過去年YouTubeから見つかった候補の質を見ます。strongは自動反映に近い候補、reviewは保留候補、weakは弱い候補です。totalだけ増えてweakだけ増える日は、量は増えたが質は伸びていない日です。</p>
    {svg_line_chart(rows, ["youtube_candidates_total", "youtube_candidates_strong", "youtube_candidates_review", "youtube_candidates_weak"], ["total", "strong", "review", "weak"], ["#2f6fed", "#177245", "#b26a00", "#7a6f87"])}
  </section>
  <section class="panel">
    <h2>レビュー・未解決</h2>
    <p class="panel-note">人手や正本整備が必要な残作業です。低信頼未判断が0ならYouTube由来の手動判断は詰まっていません。登録済み不完全、missing venue、missing sourceはMaster RDB側の整備残です。</p>
    {svg_line_chart(rows, ["low_confidence_review_unreviewed_rows", "registered_events_incomplete", "missing_venue_occurrences", "missing_source_url_occurrences"], ["低信頼未判断", "登録済み不完全", "missing venue", "missing source"], ["#b42318", "#6941c6", "#0e7490", "#b54708"])}
  </section>
  <section class="panel">
    <h2>公開反映</h2>
    <p class="panel-note">公開データに出ている補助情報の量です。日付予測、過去実績、季節ヒントは「今年確定」ではなく、未確認イベントを探しやすくするための表示です。急増した日は公開表示の見え方を確認します。</p>
    {svg_line_chart(rows, ["public_date_prediction_applied", "public_historical_reference_applied", "public_season_hint_applied"], ["日付予測", "過去実績", "季節ヒント"], ["#2f6fed", "#4f8f8b", "#946200"])}
  </section>
  <section class="panel">
    <h2>月別YouTubeキュー</h2>
    <p class="panel-note">月ごとの未取得キューです。今回対象の残りとは別で、月別にどのシーズンの過去年実績収集が残っているかを見ます。棒が低い月ほど、その月のYouTube探索が進んでいます。</p>
    {svg_month_bars(current)}
  </section>
  <section class="panel">
    <h2>履歴</h2>
    <p class="panel-note">直近30回分のスナップショットです。毎朝1行ずつ増えます。同じ日の手動再実行は、その日の行を置き換えます。</p>
    {render_history_table(rows)}
  </section>
  <section class="panel">
    <h2>用語</h2>
    <ul class="reading-list">
      <li><strong>strong</strong>: イベント名・会場・日付などの一致が強く、過去実績として使いやすいYouTube候補。</li>
      <li><strong>review</strong>: 可能性はあるが、自動で採用するには弱い候補。</li>
      <li><strong>weak</strong>: 関連が薄い候補。増えすぎると検索条件の見直し対象。</li>
      <li><strong>低信頼未判断</strong>: 人間の accept / hold / reject 判断がまだない候補。</li>
      <li><strong>今回対象の残り</strong>: その日の実行条件で、まだ検索対象として残っている行数。</li>
    </ul>
  </section>
</main>
</body>
</html>
"""


def render_history_table(rows):
    headers = [
        ("日付", "snapshot_date"),
        ("選択", "youtube_run_selected_rows"),
        ("完了", "youtube_run_completed_batches"),
        ("残り", "youtube_run_remaining_after"),
        ("候補", "youtube_candidates_total"),
        ("strong", "youtube_candidates_strong"),
        ("review", "youtube_candidates_review"),
        ("weak", "youtube_candidates_weak"),
        ("低信頼未判断", "low_confidence_review_unreviewed_rows"),
        ("日付予測", "public_date_prediction_applied"),
        ("過去実績", "public_historical_reference_applied"),
        ("季節ヒント", "public_season_hint_applied"),
    ]
    lines = ["<table><thead><tr>"]
    for label, _key in headers:
        lines.append(f"<th>{html.escape(label)}</th>")
    lines.append("</tr></thead><tbody>")
    for row in rows[-30:]:
        lines.append("<tr>")
        for _label, key in headers:
            value = row.get(key, "")
            lines.append(f"<td>{html.escape(str(value))}</td>")
        lines.append("</tr>")
    lines.append("</tbody></table>")
    return "".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=str(DATA))
    parser.add_argument("--history", default=str(DEFAULT_HISTORY))
    parser.add_argument("--latest-md", default=str(DEFAULT_LATEST_MD))
    parser.add_argument("--dashboard", default=str(DEFAULT_DASHBOARD))
    parser.add_argument("--no-replace-same-date", action="store_true")
    args = parser.parse_args()

    current = collect_metrics(args.data_dir)
    history = read_jsonl(args.history)
    rows = merge_history(history, current, replace_same_date=not args.no_replace_same_date)
    write_jsonl(args.history, rows)
    Path(args.latest_md).write_text(render_latest_markdown(current, rows), encoding="utf-8")
    Path(args.dashboard).write_text(render_dashboard(rows), encoding="utf-8")
    print(
        "ops metrics: "
        f"date={current['snapshot_date']} "
        f"youtube_candidates={current['youtube_candidates_total']} "
        f"review={current['youtube_candidates_review']} "
        f"history_rows={len(rows)}"
    )


if __name__ == "__main__":
    main()
