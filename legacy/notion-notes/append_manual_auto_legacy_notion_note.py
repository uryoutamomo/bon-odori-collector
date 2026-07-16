"""Append the legacy Notion write-back decision to the current work page."""

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone

from notion_config import load_local_env


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
        heading("手動/自動の使い分け: legacy Notion write-back"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "Master RDB -> Notion sync scripts と代表的なlegacy Notion applyを深掘りし、手動維持に確定した。"
        ),
        bullet(
            "sync_master_to_notion.py は既にfrozen。Notion実更新には --apply、"
            "--allow-frozen-notion-write、--confirm 'APPLY RDB TO NOTION' が必要。"
        ),
        bullet(
            "固定日ルール、イベント日付昇格、Xメンバー分類、X表示名補完のlegacy Notion applyにも確認文字列を追加した。"
        ),
        bullet(
            "dry-run / proposal / review artifact 生成は維持。Notion実更新だけを明示確認の対象にした。"
        ),
        bullet(
            "記録先: docs/legacy-notion-writeback-operations.md、docs/notion-usage-policy.md、"
            "docs/manual-auto-operations-inventory.md。"
        ),
        bullet(
            "次の深掘り候補: YouTube / retrospective direct Notion apply scripts。"
            "YouTube証拠やretrospective候補をNotionへ直接反映する古い apply 系を同じ基準で確認する。"
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
        print(f"Would append legacy Notion write-back note to current work page: {CURRENT_WORK_PAGE_ID}")
        return
    append_note()
    print("Notionの今やっていることページへlegacy Notion write-backの整理を追記しました")


if __name__ == "__main__":
    main()
