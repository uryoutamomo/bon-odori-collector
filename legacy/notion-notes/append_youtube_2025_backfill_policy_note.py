"""Append the YouTube 2025 backfill policy note to Notion."""

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
CURRENT_WORK_PAGE_ID = "37f8be04-e762-815c-9f62-d76866ca9e83"
YOUTUBE_TASK_PAGE_URL = "https://app.notion.com/p/YouTube-37f8be04e762814ca63fdff18fe6cf35"
CURRENT_WORK_PAGE_URL = "https://app.notion.com/p/37f8be04e762815c9f62d76866ca9e83"


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


def todo(text, checked=False):
    return {
        "object": "block",
        "type": "to_do",
        "to_do": {"rich_text": rich_text(text), "checked": checked},
    }


def update_bullet(block_id, text):
    return notion_request("PATCH", f"/blocks/{block_id}", {"bulleted_list_item": {"rich_text": rich_text(text)}})


def policy_note_blocks(target_label):
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return [
        heading("YouTube 2025バックフィル方針"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            f"追記先: {target_label}。"
            "2025年イベント・曲・会場情報は、現時点ではYouTubeから全量洗い出し済みではない。"
            "既存データ・採用済みチャンネル・見つかっていた候補の初回整理まで完了した状態として扱う。"
        ),
        bullet(
            "現状確認: data/youtube_event_song_candidates.json では2025年候補7件を抽出。"
            "既存イベント追記5件、範囲外保留1件、渋谷盆踊り2025は公式確認未解決で要調査。"
        ),
        bullet(
            "現状確認: active 7チャンネルの動画レビューは各チャンネル最大15件まで。"
            "そのため、2025年の全履歴バックフィルや検索APIによる網羅探索は未完了。"
        ),
        bullet(
            "基本方針: YouTube 2025バックフィルを次の主要タスクにする。"
            "YouTube単独で新規イベント本登録はせず、既存イベント一致・公式確認待ち・範囲外・曲目だけ採用・無視に分類する。"
        ),
        todo(
            "優先1: activeチャンネルの2025年動画を全件バックフィルする。"
            "RSS/既存voicesで足りない分は、チャンネル単位の取得方法とquota見積もりを先に確認する。"
        ),
        todo(
            "優先2: 動画タイトル・説明欄から event_date、event_name_hint、venue_hint、songs、official_urls を抽出し、"
            "data/evidence.sqlite / data/youtube_evidence.sqlite に集約する。"
        ),
        todo(
            "優先3: 既存イベントDB・公開イベントJSONと照合し、2025実績証拠として追記できるものをdry-run化する。"
        ),
        todo(
            "優先4: 未一致候補は、公式URLまたは複数信頼ソースで確認できるまで本登録しない。"
            "全国展開候補や周辺祭りは hold として別保持する。"
        ),
        todo(
            "優先5: activeチャンネル由来が尽きた後に、検索APIで「盆踊り 2025 東京」「Bon Odori 2025 Tokyo」"
            "および区名・会場名つきクエリを広げる。"
        ),
        bullet(
            "成果物予定: 2025バックフィル元データ、分類レビューJSON/MD、SQLite更新、既存イベント追記dry-run、"
            "Notion反映結果をセットで残す。"
        ),
        bullet(f"入口: {YOUTUBE_TASK_PAGE_URL}"),
        bullet(f"今やっていること: {CURRENT_WORK_PAGE_URL}"),
    ]


def append_policy_note(page_id, target_label):
    return notion_request("PATCH", f"/blocks/{page_id}/children", {"children": policy_note_blocks(target_label)})
    return notion_request("PATCH", f"/blocks/{YOUTUBE_TASK_PAGE_ID}/children", {"children": children})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    current_text = (
        "YouTube次課題: 2025年イベント・曲・会場情報の全量洗い出しは未完了。"
        "次はYouTube 2025バックフィルを主要タスクにし、まずactiveチャンネルの2025年動画全件を集約・分類する。"
    )

    if args.dry_run:
        print(f"Would update current work block: {CURRENT_WORK_PLAN_BLOCK_ID} -> {current_text}")
        print(f"Would append 2025 backfill policy note to YouTube task page: {YOUTUBE_TASK_PAGE_ID}")
        print(f"Would append 2025 backfill policy note to current work page: {CURRENT_WORK_PAGE_ID}")
        return

    update_bullet(CURRENT_WORK_PLAN_BLOCK_ID, current_text)
    append_policy_note(YOUTUBE_TASK_PAGE_ID, "YouTube課題ページ")
    append_policy_note(CURRENT_WORK_PAGE_ID, "今やっていることページ")
    print("NotionへYouTube 2025バックフィル方針を追記しました")


if __name__ == "__main__":
    main()
