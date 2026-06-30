#!/usr/bin/env python3
"""Append domain difference guidance to the Notion operations manual."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from append_review_console_operations_manual_to_notion import (
    DEFAULT_QUERY,
    bullet,
    choose_manual_page,
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
        heading_2("開催日・会場 と 根拠URL の違い"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "レビューコンソールで似て見える「開催日・会場」と「根拠URL」の判断対象の違い。"
        ),
        paragraph("どちらもイベント名・日付・会場・URLが表示されるため似て見えるが、判断している問いが違う。"),
        heading_3("開催日・会場"),
        bullet("判断する問い: このイベントは、対象年にこの日付・この会場で扱ってよいか。"),
        bullet("見ているもの: イベント本体の中身。"),
        bullet("例: 2026年開催として載せてよいか、日付が正しいか、会場が正しいか、過去実績から今年候補に上げてよいか、公式確認待ちにするべきか。"),
        bullet("短い言い方: イベント内容確認。"),
        heading_3("根拠URL"),
        bullet("判断する問い: その判断の根拠として、このURLを付けてよいか。"),
        bullet("見ているもの: 証拠リンクの品質と妥当性。"),
        bullet("例: 公式ページとして使えるか、自治体・主催・会場ページなど信頼できるURLか、既存イベントの source_url として入れてよいか、URLは関係あるが今年の確定情報ではないため要調査にするべきか。"),
        bullet("短い言い方: 証拠リンク確認。"),
        heading_3("優先順位"),
        bullet("公開情報に直結するため、まずは開催日・会場を優先する。"),
        bullet("根拠URLは、そのイベント判断の裏付けを整える作業として見る。"),
        bullet("迷ったら、イベント内容が正しいかを先に見て、その後に証拠リンクとして十分かを見る。"),
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
    print(f"Notion運用マニュアルへ開催日・会場/根拠URLの違いを追記しました: {target['title']} / {target['id']}")
    if target.get("url"):
        print(target["url"])


if __name__ == "__main__":
    main()
