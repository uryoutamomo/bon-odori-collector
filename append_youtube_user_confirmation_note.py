"""Append user confirmation results for held YouTube candidates to Notion."""

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


def append_note():
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    children = [
        heading("YouTube保留案件の掲載基準確認"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "内田さん確認により、YouTube保留案件はおとの推奨セットで確定。"
        ),
        bullet("渋谷・鹿児島おはら祭: 盆踊り本DBには入れず、周辺の踊り/祭りイベントとして別扱いで保留。"),
        bullet("Pokémon GO Fest TOKYO 2026 ピカチュウ音頭: 開催情報DBには入れず、曲目・現象メモだけ保持。"),
        bullet("渋谷盆踊り2025: 公式確認まで本登録保留。YouTube証拠は未公式実績候補として別保持。"),
        bullet("横浜開港祭 BON ODORI: 現行の東京23区公開DBには入れず、全国展開候補として保持のみ。"),
        bullet("ローカル反映: data/youtube_user_confirmation_queue.json / .md に確定判断を保存。"),
    ]
    return notion_request("PATCH", f"/blocks/{YOUTUBE_TASK_PAGE_ID}/children", {"children": children})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    if args.dry_run:
        print(f"Would append user confirmation note to: {YOUTUBE_TASK_PAGE_ID}")
        return

    append_note()
    print("NotionへYouTube保留案件の確認結果を追記しました")


if __name__ == "__main__":
    main()
