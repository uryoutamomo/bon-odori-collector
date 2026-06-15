"""Append YouTube channel review progress to Notion."""

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
        heading("YouTubeチャンネル候補レビュー"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "YouTubeチャンネル候補15件をレビューし、採用5件、既存登録済み2件、保留8件に分類。"
        ),
        bullet("採用: Tokyo Lonely Walker、Urban Walk、Tokyo Hz、Exploring Japan with Zen、shu channel。東京圏実績・曲目証拠・公式URL探索に使う。"),
        bullet("既存登録済み: 祭のきせき 盆踊り、和太鼓お祭りチャンネル。既存の手動/定期収集対象として維持。"),
        bullet("保留: 祭りが好き! は東京23区外中心。その他単発/街歩き寄りは、複数の東京圏盆踊り動画が見つかったら再評価。"),
        bullet("ローカル成果物: data/youtube_channel_review.json と data/youtube_channel_review.md。"),
    ]
    return notion_request("PATCH", f"/blocks/{YOUTUBE_TASK_PAGE_ID}/children", {"children": children})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    current_text = (
        "YouTubeチャンネル候補レビュー: 採用5件、既存登録済み2件、保留8件に分類済み。"
        "次は採用チャンネルから手動発掘する検索/重複ルールの整備。"
    )

    if args.dry_run:
        print(f"Would update current work block: {CURRENT_WORK_PLAN_BLOCK_ID} -> {current_text}")
        print(f"Would append progress note to: {YOUTUBE_TASK_PAGE_ID}")
        return

    update_bullet(CURRENT_WORK_PLAN_BLOCK_ID, current_text)
    append_progress_note()
    print("NotionへYouTubeチャンネル候補レビューを追記しました")


if __name__ == "__main__":
    main()
