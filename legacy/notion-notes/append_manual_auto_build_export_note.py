"""Append the build/export/report operations decision to the current work page."""

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
        heading("手動/自動の使い分け: build / export / report"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "remaining report/export/build scripts を深掘りし、生成系とDB更新系を分けた。"
        ),
        bullet(
            "export_public_events.py / audit_master_rdb.py / compare_* / review queue builders / "
            "local RDB snapshots は、生成物・検証レポートとして自動/手動利用可。"
        ),
        bullet(
            "build_historical_promotion_candidates.py と build_registered_event_investigation_queue.py は、"
            "Master RDB派生テーブルをDELETE/INSERTするため APPLY MASTER RDB ONE-OFF を必須化した。"
        ),
        bullet(
            "通常の公開deploy、Notion書き込み、S3更新とは別境界。生成物はrepo内・ローカルSQLite・レポートに限定して扱う。"
        ),
        bullet(
            "記録先: docs/build-export-report-operations.md、"
            "docs/manual-auto-operations-inventory.md、docs/master-rdb-public-json-one-off-operations.md。"
        ),
        bullet(
            "次の深掘り候補: Notion work-log / task-page maintenance scripts。"
            "append_*_note.py や update/close task 系の扱いを確認する。"
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
        print(f"Would append build/export/report note to current work page: {CURRENT_WORK_PAGE_ID}")
        return
    append_note()
    print("Notionの今やっていることページへbuild/export/reportの整理を追記しました")


if __name__ == "__main__":
    main()
