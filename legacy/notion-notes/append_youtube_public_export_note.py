"""Append the public YouTube evidence export progress note to Notion."""

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone

from notion_support.notion_config import load_local_env


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
        heading("YouTube公開データ整理"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "既存イベント追記候補を再dry-runし、5件すべてNotion反映済みとしてdone確認。"
            "公開JSONにはYouTube証拠を構造化したyoutube_evidence配列を追加。"
        ),
        bullet("done確認: 自由が丘納涼盆踊り大会、歌舞伎町BON ODORI、奥浅草盆踊り、丸の内de盆踊り。重複URLまたは既存曲目カバーで追加更新なし。"),
        bullet("公開データ: data/public/events_public.json に video_url、channel、thumbnail_url、songs を持つ youtube_evidence を出力。detail本文は互換性のため維持。"),
        bullet("次の実装候補: 公開UI側で youtube_evidence をカード詳細または曲目ヒント付近に表示する。サムネイルは任意表示、動画リンクは必ず出典として表示する。"),
    ]
    return notion_request("PATCH", f"/blocks/{YOUTUBE_TASK_PAGE_ID}/children", {"children": children})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    current_text = (
        "YouTubeイベント更新プラン: 既存追記5件は再dry-runでdone確認済み。"
        "公開JSONにyoutube_evidenceを追加。残りは渋谷公式確認と公開UI表示。"
    )

    if args.dry_run:
        print(f"Would update current work block: {CURRENT_WORK_PLAN_BLOCK_ID} -> {current_text}")
        print(f"Would append progress note to: {YOUTUBE_TASK_PAGE_ID}")
        return

    update_bullet(CURRENT_WORK_PLAN_BLOCK_ID, current_text)
    append_progress_note()
    print("NotionへYouTube公開データ整理の進捗を追記しました")


if __name__ == "__main__":
    main()
