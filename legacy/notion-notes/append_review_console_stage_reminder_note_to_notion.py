#!/usr/bin/env python3
"""Append stage reminder guidance to the Notion operations manual."""

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
        heading_2("反映待ちの見落とし防止"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "ステージ適用後に個別applyを動かし忘れるリスクと、レビューコンソール側の見落とし防止表示。"
        ),
        heading_3("起き得ること"),
        bullet("ステージ適用までは完了したが、実データへ反映する個別applyをまだ動かしていない、という状態はあり得る。"),
        bullet("理由は安全設計。レビューコンソールは本番DB、Notion、公開JSON、S3/CloudFrontを自動では変更しない。"),
        heading_3("画面での対策"),
        bullet("data/review_console/staged/ にapply用パケットが残っている場合、画面上部に「反映待ちステージあり」と表示する。"),
        bullet("この表示が出ている時は、個別applyをdry-runしてから明示実行する。"),
        bullet("ステージ適用後にレビュー判断を追加・変更した場合は「ステージが古い可能性」と表示し、再ステージを促す。"),
        bullet("ステージ適用をやり直すと、前回の staged/*_decisions.json は作り直され、古いステージファイルと今回の判断が混ざらない。"),
        heading_3("判断の目安"),
        bullet("エクスポートだけなら確認用レポート。反映待ちバナーは基本的に出ない。"),
        bullet("ステージ適用後にバナーが出たら、まだ個別apply確認が残っていると見る。"),
        bullet("実データ反映は、おと、または個別applyスクリプトがdry-run確認後に明示実行する。"),
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
    print(f"Notion運用マニュアルへ反映待ち見落とし防止の説明を追記しました: {target['title']} / {target['id']}")
    if target.get("url"):
        print(target["url"])


if __name__ == "__main__":
    main()
