"""Append the Notion queue migration decision to the current work page."""

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
        heading("手動/自動の使い分け: Notion queue migration"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "migrate_notion_queue_to_dynamodb.yml を深掘りし、legacy one-offとして手動維持に確定した。"
        ),
        bullet(
            "通常運用では実行しない。daily collect は既にDynamoDBキューへ書くため、"
            "Notionキューを継続同期面として扱わない。"
        ),
        bullet(
            "dry-runは apply=false 既定のまま。Notionを読んで対象候補を表示するが、DynamoDBへは書かない。"
        ),
        bullet(
            "DynamoDBへ書く apply=true は、workflowとローカルスクリプトの両方で "
            "MIGRATE NOTION QUEUE TO DYNAMODB の確認文字列を必須化した。"
        ),
        bullet(
            "安全性: cutoff以前、未解決、会場系のlegacy行だけを対象にし、既存DynamoDB itemは重複作成せず "
            "notion_synced=true で印を付ける。"
        ),
        bullet(
            "記録先: docs/notion-queue-migration-operations.md、docs/aws-dynamodb-setup.md、"
            "docs/notion-usage-policy.md、docs/manual-auto-operations-inventory.md。"
        ),
        bullet(
            "次の深掘り候補: Master RDB -> Notion sync scripts。"
            "sync_master_to_notion.py などの --apply / --confirm / dry-run default を確認する。"
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
        print(f"Would append Notion queue migration note to current work page: {CURRENT_WORK_PAGE_ID}")
        return
    append_note()
    print("Notionの今やっていることページへNotion queue migrationの整理を追記しました")


if __name__ == "__main__":
    main()
