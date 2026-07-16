"""Append Shibuya research and public UI handoff progress to Notion."""

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
        heading("渋谷調査とYouTube公開UI受け渡し"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "渋谷盆踊り2025は公式URL候補を発見したが、ページ本文取得不能のため本登録は保留継続。"
            "公開UI向けには events_public.js と表示仕様メモを追加。"
        ),
        bullet("渋谷: shibuyadogenzaka.com/?p=6827 が動画説明欄の公式URL候補。HTTP 200とWordPress投稿IDは確認、本文/RESTは取得不能。複数動画では2025-08-02が優勢。"),
        bullet("公開UI受け渡し: data/public/events_public.js を生成。const EVENTS 形式で youtube_evidence を含む。"),
        bullet("表示仕様: docs/youtube-public-ui.md に、動画リンクは出典として必ず表示、サムネイルは詳細内で任意表示、曲目は動画由来の補助情報として扱う方針を記録。"),
    ]
    return notion_request("PATCH", f"/blocks/{YOUTUBE_TASK_PAGE_ID}/children", {"children": children})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    plan_text = (
        "YouTubeイベント更新プラン: 既存追記5件はdone。公開UI向けevents_public.jsを追加。"
        "残りは渋谷公式ページ本文の復旧確認。"
    )
    new_events_text = (
        "新規イベント候補の本登録: 丸の内de盆踊りは登録済み。"
        "渋谷盆踊り2025は公式URL候補ありだが本文未確認のため保留。"
    )

    if args.dry_run:
        print(f"Would update current work block: {CURRENT_WORK_PLAN_BLOCK_ID} -> {plan_text}")
        print(f"Would update current work block: {CURRENT_WORK_NEW_EVENTS_BLOCK_ID} -> {new_events_text}")
        print(f"Would append progress note to: {YOUTUBE_TASK_PAGE_ID}")
        return

    update_bullet(CURRENT_WORK_PLAN_BLOCK_ID, plan_text)
    update_bullet(CURRENT_WORK_NEW_EVENTS_BLOCK_ID, new_events_text)
    append_progress_note()
    print("Notionへ渋谷調査とYouTube公開UI受け渡し進捗を追記しました")


if __name__ == "__main__":
    main()
