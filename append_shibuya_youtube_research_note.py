"""Append the Shibuya YouTube research hold note to Notion."""

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone

from notion_config import load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")

YOUTUBE_TASK_PAGE_ID = "37f8be04-e762-814c-a63f-dff18fe6cf35"
CURRENT_WORK_NEW_EVENTS_BLOCK_ID = "37f8be04-e762-819c-863b-e464e9591824"


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


def append_progress_note():
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    children = [
        heading("渋谷盆踊り2025 追加確認"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "YouTube候補の公式確認を継続したが、一次情報は未確保。動画説明内の日付にも曜日矛盾があるため、本登録は保留。"
        ),
        bullet("YouTube主候補: Tokyo Lonely Walker yqg-YEHbV4A。説明文はSHIBUYA109前・第6回渋谷盆踊り・2025.8.3 Satを示す。"),
        bullet("2025-08-03は日曜日で、説明文のSatと一致しない。別動画では2025-08-02表記もあるため、公式日付確認が必要。"),
        bullet("抽出処理を更新し、曜日つき日付が暦と一致しない候補はreview_new_event_candidateではなくneeds_researchに落とすようにした。"),
    ]
    return notion_request("PATCH", f"/blocks/{YOUTUBE_TASK_PAGE_ID}/children", {"children": children})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    current_text = (
        "新規イベント候補の本登録: 丸の内de盆踊りは公式確認済みで登録済み。"
        "渋谷盆踊り2025は公式未確認かつYouTube日付に曜日矛盾があるため保留。"
    )

    if args.dry_run:
        print(f"Would update current work block: {CURRENT_WORK_NEW_EVENTS_BLOCK_ID} -> {current_text}")
        print(f"Would append progress note to: {YOUTUBE_TASK_PAGE_ID}")
        return

    update_bullet(CURRENT_WORK_NEW_EVENTS_BLOCK_ID, current_text)
    append_progress_note()
    print("Notionへ渋谷盆踊り2025の保留理由を追記しました")


if __name__ == "__main__":
    main()
