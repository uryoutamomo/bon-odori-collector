#!/usr/bin/env python3
"""Append export vs stage clarification to the Notion operations manual."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from append_review_console_operations_manual_to_notion import (
    DEFAULT_QUERY,
    bullet,
    choose_manual_page,
    code,
    heading_2,
    heading_3,
    notion_request,
    paragraph,
)
from append_review_console_flow_to_notion import DEFAULT_PAGE_ID


def note_blocks() -> list[dict]:
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return [
        {"object": "block", "type": "divider", "divider": {}},
        heading_2("エクスポートとステージ適用の違い"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "レビューコンソールの上部ボタンで迷いやすい「エクスポート」と「ステージ適用」の違い。"
        ),
        heading_3("ひとことで言うと"),
        bullet("エクスポート = 人間が確認するためのまとめ。"),
        bullet("ステージ適用 = 次の処理に渡すための作業箱づめ。"),
        heading_3("エクスポート e"),
        bullet("目的: 内田さんが選んだ採用/却下/保留/要調査を、確認・共有・見直し用の一覧にする。"),
        bullet("出力: data/review_console/exported_decisions.json と data/review_console/exported_decisions.md。"),
        bullet("意味: 「今回こう判断しました」というレビュー結果レポート。"),
        bullet("ここでは Master RDB、Notion、公開JSON、S3/CloudFront などは変更しない。"),
        heading_3("ステージ適用 g"),
        bullet("目的: レビュー結果をソース別・処理別に分け、あとで apply スクリプトが読める形にする。"),
        bullet("出力: data/review_console/staged/*_decisions.json。"),
        bullet("意味: 「次の処理に渡すための作業箱づめ」。"),
        bullet("ここでもまだ本番反映はしない。Master RDB、Notion、公開JSON、S3/CloudFront などは変更しない。"),
        bullet("実データへの反映は、この後におと、または個別applyスクリプトが dry-run で確認してから明示実行する。"),
        heading_3("通常の流れ"),
        code("レビューする -> 保存 -> エクスポートで確認 -> 問題なければステージ適用 -> おと/個別applyが実反映"),
    ]


def append_note(page_id: str) -> None:
    notion_request("PATCH", f"/blocks/{page_id}/children", {"children": note_blocks()})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--page-id", default=DEFAULT_PAGE_ID)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    target, candidates = choose_manual_page(args.query, args.page_id)
    if not target:
        raise SystemExit(f"No Notion page found for query: {args.query}")

    if args.dry_run:
        print(f"Target: {target['title']} / {target['id']} / {target.get('url', '')}")
        if candidates:
            print("Candidates:")
            for row in candidates[:10]:
                print(f"- {row['title']} / {row['id']} / {row.get('last_edited_time', '')}")
        print(f"Blocks: {len(note_blocks())}")
        return

    append_note(target["id"])
    print(f"Notion運用マニュアルへエクスポート/ステージ適用の説明を追記しました: {target['title']} / {target['id']}")
    if target.get("url"):
        print(target["url"])


if __name__ == "__main__":
    main()
