"""Mark completed RDB roadmap items on the current work Notion page."""

import argparse
import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone

from notion_config import load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")

RDB_OVERVIEW_BLOCK_ID = "37f8be04-e762-814a-9463-dabca26c86e0"
RDB_NEXT_BLOCK_ID = "3808be04-e762-8176-b587-d68d1dde9bf8"
RDB_PAUSED_BLOCK_ID = "37f8be04-e762-81c4-a50b-e08d0c2d31fa"
RDB_OLD_NEXT_TODO_ID = "37f8be04-e762-8144-8921-e2114703a4b4"
ROADMAP_TODO_BLOCKS = {
    "3808be04-e762-817e-b57c-e03b1eb59edb": (
        True,
        "完了: スキーマの役割整理。notion_snapshotはNotion正本ミラー、evidenceはX/YouTube投稿証拠、youtube_evidenceはYouTube詳細分析として分離。",
    ),
    "3808be04-e762-8153-8346-d27cfac348ac": (
        True,
        "完了: ID対応表。bon_odori.sqlite に event_evidence_links / song_evidence_links / event_venues / review_queue を作成。",
    ),
    "3808be04-e762-8132-a20b-fd5dd68665bf": (
        True,
        "完了: 既存データ照合。Notion詳細欄[youtube_evidence]、YouTube RDB、X/YouTube証拠を横断して反映済み/未反映を分類。",
    ),
    "3808be04-e762-8156-867b-f3fa1f64e70d": (
        True,
        "完了: レビュー状態統一。matched_existing_event、needs_official_confirmation、out_of_scope、song_not_in_master 等を review_queue に集約。",
    ),
    "3808be04-e762-81fa-8616-d70bd0864268": (
        True,
        "完了: 代表クエリ整備。docs/rdb-review-queries.md と data/rdb_review_queue.md を作成。",
    ),
    "3808be04-e762-8176-a760-c30aa5234e55": (
        True,
        "完了: 再生成手順を安定化。python3 build_all_rdb.py で Notion取得から反映計画まで一括再生成可能。",
    ),
    "3808be04-e762-815b-a099-d3e3fda5ddb9": (
        True,
        "完了: Notion更新フロー接続。data/rdb_event_apply_plan.* と data/rdb_song_review_source.* を作成し、直接書き戻しを避ける流れにした。",
    ),
    "3808be04-e762-816e-917b-f6316be8de04": (
        False,
        "次: RDB整備後にYouTube 2025総浚いへ進む。activeチャンネル2025全件、必要なら検索API、RDB投入、既存Notion照合、分類まで行う。",
    ),
}


def rich_text(text):
    return [{"type": "text", "text": {"content": str(text or "")[:2000]}}]


def notion_request(method, path, payload):
    data = json.dumps(payload).encode("utf-8")
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
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Notion API {method} {path} failed: {error.code} {body}") from error


def update_blocks():
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    notion_request(
        "PATCH",
        f"/blocks/{RDB_OVERVIEW_BLOCK_ID}",
        {
            "bulleted_list_item": {
                "rich_text": rich_text(
                    "RDB整備: Notion正本・X/YouTube証拠・YouTube詳細DB・横断DB・レビューキュー・反映計画まで初期完了。次はこのRDBを使ってYouTube 2025総浚いへ進む。"
                )
            }
        },
    )
    notion_request(
        "PATCH",
        f"/blocks/{RDB_NEXT_BLOCK_ID}",
        {
            "bulleted_list_item": {
                "rich_text": rich_text(
                    f"RDB整備の山は完了（更新: {now} / 署名: おと（Codex））。次の山はYouTube 2025総浚いをRDB照合フローで進める。"
                )
            }
        },
    )
    notion_request(
        "PATCH",
        f"/blocks/{RDB_PAUSED_BLOCK_ID}",
        {
            "bulleted_list_item": {
                "rich_text": rich_text(
                    "RDB集約の設計検討: 初期完了。notion/evidence/youtube/bon_odori SQLiteとレビュー/反映計画まで作成済み。"
                )
            }
        },
    )
    notion_request(
        "PATCH",
        f"/blocks/{RDB_OLD_NEXT_TODO_ID}",
        {
            "to_do": {
                "rich_text": rich_text(
                    "完了: RDB集約設計を、イベント・会場・曲・YouTube証拠/occurrenceの正本化方針として初期実装済み。"
                ),
                "checked": True,
            }
        },
    )
    for block_id, (checked, text) in ROADMAP_TODO_BLOCKS.items():
        notion_request(
            "PATCH",
            f"/blocks/{block_id}",
            {"to_do": {"rich_text": rich_text(text), "checked": checked}},
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    if args.dry_run:
        print(f"Would update RDB roadmap status blocks: {len(ROADMAP_TODO_BLOCKS)}")
        return
    update_blocks()
    print("NotionのRDBロードマップ状態を更新しました")


if __name__ == "__main__":
    main()
