"""Append RDB implementation progress to the current work Notion page."""

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
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": rich_text(text)}}


def paragraph(text):
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(text)}}


def bullet(text):
    return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": rich_text(text)}}


def append_progress():
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    children = [
        heading("RDB整備 実装進捗"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "RDB整備ロードマップのうち、素材別SQLite、横断リンクDB、レビューキュー出力、再生成手順まで実装済み。"
        ),
        bullet("Notion正本ミラー: data/notion_snapshot.sqlite。会場202、イベント208、予定17、曲141、用語121。"),
        bullet("X/YouTube投稿証拠: data/evidence.sqlite。source_posts 2495、post_urls 9148、Xスコア1595、候補レビュー30。"),
        bullet("YouTube詳細分析: data/youtube_evidence.sqlite。動画288、イベント一致16、setlist occurrence 9、曲目201。"),
        bullet("横断DB: data/bon_odori.sqlite。イベント証拠リンク37、曲目証拠リンク201、レビューキュー264。"),
        bullet("レビュー出力: data/rdb_review_queue.json / .md。matched_existing_event 11、公式確認/保留25、曲マスタ未登録Top50。"),
        bullet("反映計画: data/rdb_event_apply_plan.json / .md。matched_existing_event 11件はNotion詳細欄に追加動画11件として要約反映済みのため、重複追記なし。"),
        bullet("曲レビュー元データ: data/rdb_song_review_source.json / .md。曲マスタ未登録候補118証拠を曲名単位で71候補に集約済み。"),
        bullet("再生成: python3 build_all_rdb.py で Notion取得から横断DB・レビュー出力・反映計画まで一括再生成できることを確認済み。"),
        bullet("小さな未解決点: X投稿からNotionイベントへの自動リンクは未実装。方針変更は不要なので rdb_issues に記録し、後続で照合ルールを追加する。"),
        bullet("検証: python3 -m unittest tests.test_build_bon_odori_rdb tests.test_build_notion_rdb tests.test_build_evidence_rdb tests.test_build_youtube_rdb tests.test_build_youtube_active_video_review tests.test_extract_youtube_setlists tests.test_export_rdb_apply_plans が成功。"),
        bullet("次: YouTube 2025総浚いは、このRDBと反映計画を使って既存イベント・会場・曲と照合しながら進める。"),
    ]
    return notion_request("PATCH", f"/blocks/{CURRENT_WORK_PAGE_ID}/children", {"children": children})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    if args.dry_run:
        print(f"Would append RDB progress to current work page: {CURRENT_WORK_PAGE_ID}")
        return
    append_progress()
    print("Notionの今やることページへRDB整備進捗を追記しました")


if __name__ == "__main__":
    main()
