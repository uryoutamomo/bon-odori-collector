"""Append the Notion work-log maintenance decision to the current work page."""

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone

from notion_support.notion_config import load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")
CURRENT_WORK_PAGE_ID = "37f8be04-e762-815c-9f62-d76866ca9e83"


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


def note_blocks():
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return [
        heading("手動/自動の使い分け: Notion work-log maintenance"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "Notion work-log / task-page maintenance scripts を深掘りし、手動維持に確定した。"
        ),
        bullet(
            "append_*_note.py は、既知の作業ページへ時刻付きメモを追記する軽い手動ログとして維持。"
            "イベント/会場/曲DB更新やtodo完了には使わない。"
        ),
        bullet(
            "todo完了、既存block更新、ページ作成、現在地/まず見るリンク編集は "
            "APPLY NOTION WORKLOG MAINTENANCE の確認文字列を必須化した。"
        ),
        bullet(
            "これらはスケジュール化しない。自動ハンドオフが必要になった場合は、専用ログページ/queueを設計して台帳へ先に追加する。"
        ),
        bullet(
            "記録先: docs/notion-worklog-maintenance-operations.md、"
            "docs/notion-usage-policy.md、docs/manual-auto-operations-inventory.md。"
        ),
        bullet(
            "現時点の主要候補は一巡。次は、新しい自動化案が出た時点で台帳へ先に分類する。"
        ),
    ]


def append_note():
    return notion_request(
        "PATCH",
        f"/blocks/{CURRENT_WORK_PAGE_ID}/children",
        {"children": note_blocks()},
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    if args.dry_run:
        print(f"Would append Notion work-log maintenance note to current work page: {CURRENT_WORK_PAGE_ID}")
        return
    append_note()
    print("Notionの今やっていることページへNotion work-log maintenanceの整理を追記しました")


if __name__ == "__main__":
    main()
