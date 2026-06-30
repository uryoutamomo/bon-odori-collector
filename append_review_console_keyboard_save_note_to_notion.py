#!/usr/bin/env python3
"""Append keyboard-save guidance to the Notion operations manual."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from append_review_console_flow_to_notion import DEFAULT_PAGE_ID
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


def note_blocks() -> list[dict]:
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return [
        {"object": "block", "type": "divider", "divider": {}},
        heading_2("レビューコンソール: 数字キーの即保存"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "内田さんがレビュー中に数字キーで判断した後、そのまま放置しても判断が失われないよう、保存動作を明文化する。"
        ),
        heading_3("結論"),
        bullet("レビュー画面で 1〜5 の数字キーを押すと、アクティブな候補カードの該当反映ルートが即保存される。"),
        bullet("保存先は data/review_console/decisions.json。ブラウザ上の一時選択だけではなく、ローカルファイルにPOST保存される。"),
        bullet("保存に成功すると画面に「保存しました」と出る。これが出た判断は、画面を閉じたり放置したりしても残る。"),
        bullet("通信エラーや検証エラーで保存できなかった場合はエラーメッセージが出て、ボタンは再度押せる状態に戻る。"),
        heading_3("画面移動ショートカット"),
        bullet("h: ホームへ移動。"),
        bullet("m: メトリクスへ移動。"),
        bullet("v: レビューへ移動。"),
        heading_3("実装上の流れ"),
        code(
            "\n".join(
                [
                    "1〜5キー",
                    "-> アクティブカード内の data-shortcut ボタンを click()",
                    "-> saveDecision(...)",
                    "-> POST /api/decision",
                    "-> data.save_decision(...)",
                    "-> data/review_console/decisions.json に書き込み",
                ]
            )
        ),
        heading_3("注意"),
        bullet("メモ欄や検索欄にフォーカスがある時は文字入力を優先する。Escで入力欄から戻ってから数字キーを使う。"),
        bullet("ステージ適用 g は本番反映ではない。数字キー保存後も、実データ反映はエクスポート/ステージ/個別applyの確認後に行う。"),
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
    print(f"Notion運用マニュアルへ数字キー即保存の説明を追記しました: {target['title']} / {target['id']}")
    if target.get("url"):
        print(target["url"])


if __name__ == "__main__":
    main()
