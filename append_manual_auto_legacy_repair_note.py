"""Append the legacy Notion repair decision to the current work page."""

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
        heading("手動/自動の使い分け: legacy Notion repair"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "legacy Notion repair / registration scripts を深掘りし、手動維持に確定した。"
        ),
        bullet(
            "対象は venue/event/glossary/song/X member の古い fill_* / register_* / merge_* / "
            "fix_* / one-off apply 系。sync_venue_master.py のようなread-only exporterは対象外。"
        ),
        bullet(
            "Notion実更新には APPLY LEGACY NOTION REPAIR の確認文字列を必須化した。"
            "--apply があるスクリプトは --apply 時だけ、--dry-run があるスクリプトは実反映時だけ確認する。"
        ),
        bullet(
            "目的: 誤ってローカルから古い一回限り修復を再実行して、Notionの会場・イベント・用語集・曲・Xメンバー状態を変える事故を防ぐ。"
        ),
        bullet(
            "記録先: docs/legacy-notion-repair-operations.md、docs/notion-usage-policy.md、"
            "docs/manual-auto-operations-inventory.md。"
        ),
        bullet(
            "次の深掘り候補: Master RDB / public JSON one-off apply scripts。"
            "apply_public_* など、ローカル正本や公開JSONを直接変更する経路を確認する。"
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
        print(f"Would append legacy Notion repair note to current work page: {CURRENT_WORK_PAGE_ID}")
        return
    append_note()
    print("Notionの今やっていることページへlegacy Notion repairの整理を追記しました")


if __name__ == "__main__":
    main()
