"""Update Notion progress for the YouTube data handling task list."""

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone

from operation_safety.manual_apply_guards import NOTION_WORKLOG_MAINTENANCE_CONFIRMATION, require_confirmation
from notion_config import load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")

YOUTUBE_TASK_PAGE_ID = "37f8be04-e762-814c-a63f-dff18fe6cf35"

COMPLETED_TODO_BLOCK_IDS = [
    "37f8be04-e762-817f-b178-d044c7badd79",
    "37f8be04-e762-8189-815f-fa7979950c25",
    "37f8be04-e762-81a7-a81d-ebebcf6fa1f2",
]

CURRENT_WORK_PLAN_BLOCK_ID = "37f8be04-e762-814a-9463-dabca26c86e0"


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
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": rich_text(text)},
    }


def paragraph(text):
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": rich_text(text)},
    }


def bullet(text):
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": rich_text(text)},
    }


def check_todo(block_id):
    return notion_request("PATCH", f"/blocks/{block_id}", {"to_do": {"checked": True}})


def update_current_work_plan_text():
    text = (
        "YouTubeイベント更新プラン: 既存追記2件は適用済み。"
        "残りは新規候補2件、対象外1件、要調査1件の確認。"
        "ローカル: data/youtube_event_update_plan.md"
    )
    return notion_request(
        "PATCH",
        f"/blocks/{CURRENT_WORK_PLAN_BLOCK_ID}",
        {"bulleted_list_item": {"rich_text": rich_text(text)}},
    )


def append_progress_note():
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    children = [
        heading("進捗更新"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "自由が丘納涼盆踊り大会と歌舞伎町BON ODORIの既存イベント追記はdry-runから本適用まで完了。"
        ),
        bullet("自由が丘納涼盆踊り大会: date_endを2025-07-21まで補正し、YouTube証拠を既存イベントへ追記済み。"),
        bullet("歌舞伎町BON ODORI: 2025-08-16のYouTube証拠と曲目ヒントを既存イベントへ追記済み。"),
        bullet("dry-runの残件は ready/review/blocked が0件。重複URLや既存曲目カバー分はdone扱い。"),
        bullet("次に見る候補: 渋谷盆踊り2025、東京丸の内盆踊り2025、Tokyo Hzの奥浅草系動画、YouTube表示場所の設計。"),
    ]
    return notion_request("PATCH", f"/blocks/{YOUTUBE_TASK_PAGE_ID}/children", {"children": children})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    if args.dry_run:
        print("Would check completed todo blocks:")
        for block_id in COMPLETED_TODO_BLOCK_IDS:
            print(f"- {block_id}")
        print(f"Would update current work block: {CURRENT_WORK_PLAN_BLOCK_ID}")
        print(f"Would append progress note to: {YOUTUBE_TASK_PAGE_ID}")
        return
    try:
        require_confirmation(
            True,
            args.confirm,
            NOTION_WORKLOG_MAINTENANCE_CONFIRMATION,
            "YouTube Notion progress update",
        )
    except ValueError as exc:
        parser.error(str(exc))

    for block_id in COMPLETED_TODO_BLOCK_IDS:
        check_todo(block_id)
    update_current_work_plan_text()
    append_progress_note()
    print("NotionのYouTube活用ページを進捗更新しました")


if __name__ == "__main__":
    main()
