"""Update Notion progress after YouTube new-event follow-up."""

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
YOUTUBE_OKU_ASAKUSA_TODO_BLOCK_ID = "37f8be04-e762-81a2-95c1-dac5da78b7f4"
CURRENT_WORK_NEW_EVENTS_BLOCK_ID = "37f8be04-e762-819c-863b-e464e9591824"
CURRENT_WORK_OKU_ASAKUSA_BLOCK_ID = "37f8be04-e762-81ef-bae7-ed8486ed08cc"


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
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": rich_text(text)},
    }


def update_bullet(block_id, text):
    return notion_request("PATCH", f"/blocks/{block_id}", {"bulleted_list_item": {"rich_text": rich_text(text)}})


def check_todo(block_id):
    return notion_request("PATCH", f"/blocks/{block_id}", {"to_do": {"checked": True}})


def append_progress_note():
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    children = [
        heading("進捗更新"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "YouTube新規候補と奥浅草要調査を確認。丸の内は公式確認済みとして登録、奥浅草は既存イベントへ証拠追記。"
        ),
        bullet("丸の内de盆踊り: Marunouchi.com公式ページで2025-07-25〜2025-07-26・行幸通りを確認し、会場とイベントをNotionへ登録済み。"),
        bullet("奥浅草盆踊り: Tokyo Hz動画を2025-06-28の過去年実績として既存イベントへ追記済み。"),
        bullet("渋谷盆踊り2025: YouTube複数本では日付・場所が見えるが、公式確認ソース未確保のため本登録は保留。"),
    ]
    return notion_request("PATCH", f"/blocks/{YOUTUBE_TASK_PAGE_ID}/children", {"children": children})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    current_new_events = "新規イベント候補の本登録: 丸の内de盆踊りは公式確認済みで登録済み。渋谷盆踊り2025は公式確認待ち。"
    current_oku = "奥浅草系YouTube動画の照合: 2025-06-28の過去年実績として既存の奥浅草盆踊りへ追記済み。"

    if args.dry_run:
        print(f"Would check todo: {YOUTUBE_OKU_ASAKUSA_TODO_BLOCK_ID}")
        print(f"Would update current work block: {CURRENT_WORK_NEW_EVENTS_BLOCK_ID} -> {current_new_events}")
        print(f"Would update current work block: {CURRENT_WORK_OKU_ASAKUSA_BLOCK_ID} -> {current_oku}")
        print(f"Would append progress note to: {YOUTUBE_TASK_PAGE_ID}")
        return
    try:
        require_confirmation(
            True,
            args.confirm,
            NOTION_WORKLOG_MAINTENANCE_CONFIRMATION,
            "YouTube Notion follow-up progress update",
        )
    except ValueError as exc:
        parser.error(str(exc))

    check_todo(YOUTUBE_OKU_ASAKUSA_TODO_BLOCK_ID)
    update_bullet(CURRENT_WORK_NEW_EVENTS_BLOCK_ID, current_new_events)
    update_bullet(CURRENT_WORK_OKU_ASAKUSA_BLOCK_ID, current_oku)
    append_progress_note()
    print("NotionのYouTubeフォローアップ進捗を更新しました")


if __name__ == "__main__":
    main()
