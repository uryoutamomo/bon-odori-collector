"""Append the RDB roadmap to the current work Notion page."""

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


def todo(text, checked=False):
    return {
        "object": "block",
        "type": "to_do",
        "to_do": {"rich_text": rich_text(text), "checked": checked},
    }


def update_current_work_bullet():
    text = (
        "RDB整備: Notion正本・X/YouTube証拠・YouTube詳細DBのSQLite化は初期完了。"
        "次は素材別DBを横断するID対応表、照合テーブル、レビュー状態を整え、"
        "その後にYouTube 2025総浚いへ進む。"
    )
    return notion_request(
        "PATCH",
        f"/blocks/{CURRENT_WORK_PLAN_BLOCK_ID}",
        {"bulleted_list_item": {"rich_text": rich_text(text)}},
    )


def append_roadmap():
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    children = [
        heading("RDB整備ロードマップ"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "Notion・X・YouTube・公開JSONに分散した情報を、まずローカルSQLiteで横断検索・照合できる状態にする。"
            "これは本番DB移行ではなく、Notion正本を壊さずに作る分析・移行準備用RDB。"
        ),
        bullet(
            "ゴール: イベント、会場、開催日、X/YouTube証拠、曲目候補、Notion反映済み/候補/保留の状態をSQLで確認できるようにする。"
        ),
        bullet(
            "現在地: data/notion_snapshot.sqlite、data/evidence.sqlite、data/youtube_evidence.sqlite の素材別SQLiteは初期生成済み。"
        ),
        todo(
            "1. スキーマの役割整理: notion_snapshotはNotion正本ミラー、evidenceはX/YouTube投稿証拠、youtube_evidenceはYouTube詳細分析として責務を明確にする。"
        ),
        todo(
            "2. ID対応表を作る: NotionイベントID、会場ID、YouTube video_id、X status ID、曲マスタIDをつなぐリンクテーブルを設計する。"
        ),
        todo(
            "3. 既存データを照合する: Notion詳細欄の[youtube_evidence]、YouTube RDB、X投稿候補を突合し、反映済み/未反映を分ける。"
        ),
        todo(
            "4. レビュー状態を統一する: matched_existing_event、needs_official_confirmation、hold_out_of_scope、song_only、ignore をX/YouTube共通で扱う。"
        ),
        todo(
            "5. 代表クエリを整備する: 2025年イベントでYouTube証拠があるもの、未反映動画、公式未確認、曲マスタ未登録候補をSQLで出せるようにする。"
        ),
        todo(
            "6. 再生成手順を安定化する: build_notion_rdb.py、build_evidence_rdb.py、build_youtube_rdb.pyを順番に実行し、可能ならbuild_all_rdb.pyにまとめる。"
        ),
        todo(
            "7. Notion更新フローと接続する: SQLiteから直接書き戻さず、SQLite -> dry-run JSON/MD -> 既存apply系スクリプトで反映する安全な流れにする。"
        ),
        todo(
            "8. RDB整備後にYouTube 2025総浚いへ進む: activeチャンネル2025全件、必要なら検索API、RDB投入、既存Notion照合、反映候補/保留/範囲外/無視に分類する。"
        ),
        bullet(
            "次の山: 素材別DBを横断する対応表・照合テーブル・レビュー状態を作る。"
        ),
    ]
    return notion_request("PATCH", f"/blocks/{CURRENT_WORK_PAGE_ID}/children", {"children": children})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    if args.dry_run:
        print(f"Would update current work block: {CURRENT_WORK_PLAN_BLOCK_ID}")
        print(f"Would append RDB roadmap to current work page: {CURRENT_WORK_PAGE_ID}")
        return

    update_current_work_bullet()
    append_roadmap()
    print("Notionの今やることページへRDB整備ロードマップを追記しました")


if __name__ == "__main__":
    main()
