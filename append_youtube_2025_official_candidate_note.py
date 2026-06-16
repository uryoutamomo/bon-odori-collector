"""Append YouTube 2025 official candidate validation progress to Notion."""

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
VALIDATION = Path("data/youtube_2025_official_candidate_validation.json")
APPLY_RESULT = Path("data/youtube_2025_official_candidate_existing_apply_result.json")
APPLY_SUMMARY = Path("data/rdb_apply_plan_summary.json")
RDB_SUMMARY = Path("data/bon_odori_rdb_summary.json")


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


def video_count_for_status(validation, status):
    return sum(row.get("video_count") or 0 for row in validation.get("rows") or [] if row.get("status") == status)


def names_for_updates(apply_result):
    return "、".join(
        f"{row.get('target_event_name')}（{row.get('video_count')}動画）"
        for row in apply_result.get("updates") or []
        if row.get("changed")
    )


def note_children(target_label):
    validation = load_json(VALIDATION, {})
    apply_result = load_json(APPLY_RESULT, {})
    apply_summary = load_json(APPLY_SUMMARY, {})
    rdb_summary = load_json(RDB_SUMMARY, {})
    counts = validation.get("status_counts") or {}
    event_counts = apply_summary.get("event_plan_counts") or {}
    table_counts = rdb_summary.get("table_counts") or {}
    applied_videos = sum(row.get("video_count") or 0 for row in apply_result.get("updates") or [] if row.get("changed"))
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return [
        heading("YouTube 2025 公式URL候補検証"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。追記先: {target_label}。"
            "手動確認キューのhigh公式URL候補を、公式URL本文の日付確認とRDB既存イベント照合で検証した。"
        ),
        bullet(f"検証対象: {validation.get('candidate_count', 0)}候補 / {validation.get('candidate_video_count', 0)}動画。"),
        bullet(f"Notion反映: {apply_result.get('applied_count', 0)}既存イベント / {applied_videos}動画。対象: {names_for_updates(apply_result)}。"),
        bullet(
            "残り新規/追加確認: "
            f"new_event_review {counts.get('new_event_review', 0)}候補/{video_count_for_status(validation, 'new_event_review')}動画。"
        ),
        bullet(
            "保留: "
            f"source_date_hold {counts.get('source_date_hold', 0)}候補/{video_count_for_status(validation, 'source_date_hold')}動画、"
            f"source_fetch_hold {counts.get('source_fetch_hold', 0)}候補/{video_count_for_status(validation, 'source_fetch_hold')}動画。"
        ),
        bullet(
            "RDB再生成後: "
            f"event_evidence_links {table_counts.get('event_evidence_links', 0)}、"
            f"review_batch_2025_backfill {event_counts.get('review_batch_2025_backfill', 0)}、"
            f"no_action_summary_present {event_counts.get('no_action_summary_present', 0)}、ready {event_counts.get('ready', 0)}。"
        ),
        bullet("小問題: build_youtube_active_video_review.py はRDB総浚い時に --max-per-channel 10000 で再生成する。デフォルト15件は通常レビュー用。"),
        bullet("成果物: data/youtube_2025_official_candidate_validation.json / .md、data/youtube_2025_official_candidate_existing_apply_result.json / .md。"),
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
    print("NotionへYouTube 2025公式URL候補検証の進捗を追記しました")


if __name__ == "__main__":
    main()
