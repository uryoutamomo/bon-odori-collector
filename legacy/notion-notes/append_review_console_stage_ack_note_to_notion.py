#!/usr/bin/env python3
"""Append stage acknowledgement guidance to the Notion operations manual."""

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
        heading_2("個別apply済みとして記録"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "レビューコンソールの反映待ちバナーを消すための確認記録について。"
        ),
        heading_3("何をするボタンか"),
        bullet("個別applyをdry-run後に明示実行したことを、ローカルに記録するボタン。"),
        bullet("記録先は data/review_console/staged/stage_apply_ack.json。"),
        bullet("このボタン自体は、Master RDB、Notion、公開JSON、S3/CloudFront などを変更しない。"),
        heading_3("いつ押すか"),
        bullet("画面上部に「反映待ちステージあり」が出ている。"),
        bullet("おと、または個別applyスクリプトが staged/*_decisions.json を読み、dry-runで確認した。"),
        bullet("その後、個別applyを明示実行して、実データ側への反映を終えた。"),
        bullet("ここまで終わってから「個別apply済みとして記録」を押す。"),
        heading_3("押さない場合"),
        bullet("実データへの反映がまだ終わっていない場合は押さない。"),
        bullet("ステージ後にレビュー判断を追加・変更した場合は、記録ではなく再ステージする。画面には「ステージが古い可能性」と出る。"),
        bullet("新しくステージ適用すると、以前の確認記録はリセットされ、また反映待ちとして表示される。"),
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
    print(f"Notion運用マニュアルへ個別apply済み記録の説明を追記しました: {target['title']} / {target['id']}")
    if target.get("url"):
        print(target["url"])


if __name__ == "__main__":
    main()
