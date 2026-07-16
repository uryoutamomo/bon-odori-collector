"""Append the legacy YouTube/retrospective Notion apply decision to the current work page."""

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
        heading("手動/自動の使い分け: legacy YouTube Notion apply"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "YouTube / retrospective direct Notion apply scripts を深掘りし、手動維持に確定した。"
        ),
        bullet(
            "対象は apply_youtube_* と apply_retrospective_* のうち、古いNotion直書きapply 12本。"
            "通常運用ではMaster RDB / public export側を使い、これらを自動化しない。"
        ),
        bullet(
            "dry-run / report生成は維持。Notion実更新を行う --apply には "
            "APPLY LEGACY YOUTUBE NOTION UPDATES の確認文字列を必須化した。"
        ),
        bullet(
            "理由: 2025/retrospectiveのレビュー済みローカル証拠を直接Notionへ反映する経路で、"
            "定期実行すると古い判断を再適用しやすい。"
        ),
        bullet(
            "記録先: docs/legacy-youtube-notion-apply-operations.md、docs/notion-usage-policy.md、"
            "docs/manual-auto-operations-inventory.md。"
        ),
        bullet(
            "次の深掘り候補: legacy one-off Notion repair / registration scripts。"
            "fill_* / register_* / merge_* / fix_* 系の書き込み先、dry-run可否、確認文字列の有無を確認する。"
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
        print(
            "Would append legacy YouTube Notion apply note to current work page: "
            f"{CURRENT_WORK_PAGE_ID}"
        )
        return
    append_note()
    print("Notionの今やっていることページへlegacy YouTube Notion applyの整理を追記しました")


if __name__ == "__main__":
    main()
