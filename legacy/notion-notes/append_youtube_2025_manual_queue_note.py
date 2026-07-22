"""Append YouTube 2025 manual confirmation queue summary to Notion."""

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
QUEUE = Path("data/youtube_2025_manual_confirmation_queue.json")


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


def count_map(queue):
    return {row["bucket"]: row for row in queue.get("counts") or []}


def count_line(label, bucket, counts):
    row = counts.get(bucket, {"items": 0, "videos": 0})
    return f"{label}: {row['items']}項目 / {row['videos']}動画。"


def note_children(target_label):
    queue = load_json(QUEUE, {})
    counts = count_map(queue)
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return [
        heading("YouTube 2025 手動確認キュー"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。追記先: {target_label}。"
            "自動日付補正と安全applyで処理できなかった残件を、確認種別ごとにキュー化した。"
        ),
        bullet(f"合計: {queue.get('item_count', 0)}項目 / {queue.get('video_count', 0)}動画。"),
        bullet(count_line("公式URL候補", "needs_official_confirmation:official_url_candidate", counts)),
        bullet(count_line("地図/SNS/Linktreeのみ", "needs_official_confirmation:social_or_map_only", counts)),
        bullet(count_line("残り単日日付候補", "remaining_backfill:date_backfill_candidate_single_date", counts)),
        bullet(count_line("残り複数日/混入確認", "remaining_backfill:date_backfill_candidate_multi_date", counts)),
        bullet(count_line("過去年動画公開", "remaining_backfill:prior_year_video_uploaded_in_2025", counts)),
        bullet(count_line("年ズレ/継続イベント", "remaining_backfill:year_mismatch_or_recurring_event_review", counts)),
        bullet("扱い: highの公式URL候補と残り単日日付候補だけを次の確認対象にする。地図/SNSのみ、過去年、年ズレは自動反映しない。"),
        bullet("成果物: data/youtube_2025_manual_confirmation_queue.json / .md。"),
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
    print("NotionへYouTube 2025手動確認キューを追記しました")


if __name__ == "__main__":
    main()
