"""Append remaining YouTube 2025 hold items to Notion."""

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from notion_support.notion_config import load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")
YOUTUBE_TASK_PAGE_ID = "37f8be04-e762-814c-a63f-dff18fe6cf35"
CURRENT_WORK_PAGE_ID = "37f8be04-e762-815c-9f62-d76866ca9e83"
VALIDATION = Path("data/youtube_2025_official_candidate_validation.json")
QUEUE = Path("data/youtube_2025_manual_confirmation_queue.json")
CURATED = Path("data/youtube_2025_curated_official_apply_result.json")


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


def hold_rows(validation):
    curated = load_json(CURATED, {})
    handled_urls = {
        row.get("primary_url")
        for row in curated.get("rows") or []
        if row.get("event_name")
    }
    return [
        row
        for row in validation.get("rows") or []
        if row.get("status") in {"source_date_hold", "source_fetch_hold", "new_event_review"}
        and row.get("primary_url") not in handled_urls
    ]


def queue_count(queue, key):
    for row in queue.get("counts") or []:
        if row.get("bucket") == key:
            return row.get("items", 0), row.get("videos", 0)
    return 0, 0


def note_children(target_label):
    validation = load_json(VALIDATION, {})
    queue = load_json(QUEUE, {})
    rows = hold_rows(validation)
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    new_event_count = sum(1 for row in rows if row.get("status") == "new_event_review")
    source_date_count = sum(1 for row in rows if row.get("status") == "source_date_hold")
    source_fetch_count = sum(1 for row in rows if row.get("status") == "source_fetch_hold")
    new_event_videos = sum(row.get("video_count") or 0 for row in rows if row.get("status") == "new_event_review")
    source_date_videos = sum(row.get("video_count") or 0 for row in rows if row.get("status") == "source_date_hold")
    source_fetch_videos = sum(row.get("video_count") or 0 for row in rows if row.get("status") == "source_fetch_hold")
    hold_lines = []
    for row in rows:
        hold_lines.append(
            f"{row.get('status')}: {row.get('primary_url')} / {row.get('video_count')}動画 / {row.get('reason')}"
        )
    official_items, official_videos = queue_count(queue, "needs_official_confirmation:official_url_candidate")
    date_items, date_videos = queue_count(queue, "remaining_backfill:date_backfill_candidate_single_date")
    return [
        heading("YouTube 2025 保留一覧"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。追記先: {target_label}。"
            "自動反映できなかった残件を、日付未抽出・取得失敗・新規候補に分けて固定化した。"
        ),
        bullet(f"新規候補: {new_event_count}件 / {new_event_videos}動画。"),
        bullet(f"日付保留: {source_date_count}件 / {source_date_videos}動画。"),
        bullet(f"取得失敗: {source_fetch_count}件 / {source_fetch_videos}動画。"),
        bullet(f"手動確認キュー: 公式URL候補 {official_items}項目 / {official_videos}動画、残り単日日付候補 {date_items}項目 / {date_videos}動画。"),
        bullet("判断: ここから先は、2025総浚いの自動反映ではなく、追加出典の取得か手動確認が必要。"),
        bullet("保留明細: " + " / ".join(hold_lines)),
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
    print("NotionへYouTube 2025保留一覧を追記しました")


if __name__ == "__main__":
    main()
