"""Append YouTube 2025 date backfill/apply progress to Notion."""

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from notion_config import load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")
YOUTUBE_TASK_PAGE_ID = "37f8be04-e762-814c-a63f-dff18fe6cf35"
CURRENT_WORK_PAGE_ID = "37f8be04-e762-815c-9f62-d76866ca9e83"
DATE_APPLY = Path("data/youtube_2025_date_backfill_apply_result.json")
SAFE_APPLY = Path("data/youtube_2025_safe_existing_event_apply_result.json")
SECOND_PASS = Path("data/youtube_2025_second_pass_event_groups.json")
APPLY_SUMMARY = Path("data/rdb_apply_plan_summary.json")


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def rich_text(text):
    return [{"type": "text", "text": {"content": str(text or "")[:2000]}}]


def notion_request(method, path, payload=None):
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        NOTION_API + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def heading(text):
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": rich_text(text)}}


def paragraph(text):
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(text)}}


def bullet(text):
    return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": rich_text(text)}}


def count_by_category(report):
    return {
        row["category"]: {
            "events": row.get("event_count", 0),
            "videos": row.get("video_count", 0),
        }
        for row in report.get("category_counts") or []
    }


def note_children(target_label):
    date_apply = load_json(DATE_APPLY, {})
    safe_apply = load_json(SAFE_APPLY, {})
    second_pass = load_json(SECOND_PASS, {})
    summary = load_json(APPLY_SUMMARY, {})
    counts = count_by_category(second_pass)
    changed_updates = [row for row in safe_apply.get("updates") or [] if row.get("changed")]
    safe_video_count = sum(row.get("video_count") or 0 for row in changed_updates)
    event_names = "、".join(row.get("target_event_name") or "" for row in changed_updates)
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    event_plan_counts = summary.get("event_plan_counts") or {}
    return [
        heading("YouTube 2025 日付補正と安全反映"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。追記先: {target_label}。"
            "二次分類の単日候補から、source_url本文で日付確認できたものだけNotion日付補正し、その後YouTube証拠を安全applyした。"
        ),
        bullet(f"日付補正: {date_apply.get('applied_count', 0)}イベントをNotionへ適用。開催日・状態・根拠メモを更新。"),
        bullet(f"YouTube証拠反映: {safe_apply.get('applied_count', 0)}イベント / {safe_video_count}動画を既存イベント詳細欄[youtube_evidence]へ追記。"),
        bullet(f"反映イベント: {event_names}。"),
        bullet(f"RDB再生成後の残り review_batch_2025_backfill: {event_plan_counts.get('review_batch_2025_backfill', 0)}動画。"),
        bullet(f"残り二次分類: {second_pass.get('remaining_review_batch_rows', 0)}動画 / {second_pass.get('event_group_count', 0)}イベントグループ。"),
        bullet(f"残り日付候補: 単日 {counts.get('date_backfill_candidate_single_date', {}).get('events', 0)}イベント/{counts.get('date_backfill_candidate_single_date', {}).get('videos', 0)}動画、複数日 {counts.get('date_backfill_candidate_multi_date', {}).get('events', 0)}イベント/{counts.get('date_backfill_candidate_multi_date', {}).get('videos', 0)}動画。"),
        bullet(f"保留: 過去年公開 {counts.get('prior_year_video_uploaded_in_2025', {}).get('events', 0)}イベント/{counts.get('prior_year_video_uploaded_in_2025', {}).get('videos', 0)}動画、年ズレ {counts.get('year_mismatch_or_recurring_event_review', {}).get('events', 0)}イベント/{counts.get('year_mismatch_or_recurring_event_review', {}).get('videos', 0)}動画。"),
        bullet("成果物: data/youtube_2025_date_backfill_plan.md、data/youtube_2025_date_backfill_apply_result.md、data/youtube_2025_safe_existing_event_apply_result.md。"),
        bullet(f"次: 残り{second_pass.get('remaining_review_batch_rows', 0)}動画は、source_urlだけでは自動確認できない。公式確認候補194件と合わせて、追加検索または手動確認キューとして扱う。"),
    ]


def append_note(page_id, target_label):
    return notion_request("PATCH", f"/blocks/{page_id}/children", {"children": note_children(target_label)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    if args.dry_run:
        for child in note_children("dry-run"):
            print(json.dumps(child, ensure_ascii=False))
        return
    append_note(YOUTUBE_TASK_PAGE_ID, "YouTube課題ページ")
    append_note(CURRENT_WORK_PAGE_ID, "今やっていること")
    print("NotionへYouTube 2025日付補正と安全反映の進捗を追記しました")


if __name__ == "__main__":
    main()
