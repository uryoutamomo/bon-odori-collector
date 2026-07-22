"""Append YouTube channel registry progress to the YouTube Notion task page."""

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
YOUTUBE_TASK_PAGE_URL = "https://app.notion.com/p/YouTube-37f8be04e762814ca63fdff18fe6cf35"


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
        heading("YouTubeチャンネル登録台帳と収集導線"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "YouTube由来DBの既存整理を使い、チャンネル登録台帳を作成。"
            "以後YouTube関連の作業入口はこのNotionページとして扱う。"
        ),
        bullet(
            "台帳: data/youtube_channel_registry.json を追加。15件を active=4、watch=3、hold=8 に分類。"
            "確認用に data/youtube_channel_registry.md も生成。"
        ),
        bullet(
            "収集導線: collect.py が台帳の status=active かつ collection_enabled=true のYouTube RSSを読むように変更。"
            "既存RSSと重複するチャンネルはRSS URLで重複排除する。"
        ),
        bullet(
            "現在のactive収集対象: 和太鼓お祭りチャンネル、祭のきせき 盆踊り、Tokyo Lonely Walker、Urban Walk、"
            "Tokyo Hz、Exploring Japan with Zen、shu channel。watchは0件。"
        ),
        bullet(
            "手動RSS取り込み: active 7チャンネルを対象化。再実行でExploring Japan with Zenも取得成功。"
            "YouTube voiceは288件、data/youtube_channels.json は7チャンネルに正規化済み。"
        ),
        bullet(
            "曲目接続: data/youtube_setlist_occurrences.json を再生成し、9 occurrence / 201曲を抽出。"
            "data/song_occurrences.json は10 occurrence / 206曲に更新。山王音頭と民踊大会の重複分裂は補正済み。"
        ),
        bullet(
            "動画レビュー: data/youtube_active_video_review.json / .md を追加。active各15件、計105件を分類。"
            "append_existing_event=17、needs_official_confirmation=6、review_video_evidence=10、out_of_scope=18、ignore=54。"
        ),
        bullet(
            "安全ルール: YouTube単独では新規イベントを本登録しない。サムネイルは動画証拠として扱い、会場写真として誤用しない。"
        ),
        bullet(f"参照入口: {YOUTUBE_TASK_PAGE_URL}"),
    ]
    return notion_request("PATCH", f"/blocks/{YOUTUBE_TASK_PAGE_ID}/children", {"children": children})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    current_text = (
        "YouTubeデータ活用: チャンネル登録台帳を作成し、activeチャンネルのRSS収集導線をcollect.pyへ接続済み。"
        "採用済み7チャンネルをactive化し、RSS取り込み、setlist抽出、song occurrence更新まで完了。"
        "今後のYouTube作業入口は「今後の課題リスト: YouTubeデータ活用」。"
    )

    if args.dry_run:
        print(f"Would update current work block: {CURRENT_WORK_PLAN_BLOCK_ID} -> {current_text}")
        print(f"Would append progress note to: {YOUTUBE_TASK_PAGE_ID}")
        return

    update_bullet(CURRENT_WORK_PLAN_BLOCK_ID, current_text)
    append_progress_note()
    print("NotionへYouTubeチャンネル登録台帳と収集導線の進捗を追記しました")


if __name__ == "__main__":
    main()
