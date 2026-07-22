#!/usr/bin/env python3
"""Append review console operation notes to the current work Notion page."""

from __future__ import annotations

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
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": rich_text(text)},
    }


def code(text):
    return {
        "object": "block",
        "type": "code",
        "code": {"rich_text": rich_text(text), "language": "plain text"},
    }


def note_blocks():
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    shortcuts = "\n".join(
        [
            "j/↓: 次の候補、k/↑: 前の候補",
            "1: 採用、2: 却下、3: 保留、4: 要調査",
            "s: 保存、c: 解除、n: メモ、v: 適用値、i: JSON詳細、o: 最初の根拠URL",
            "/: 検索、u: 未レビュー、a: 全件、d: 決定済み、p: 処理済み",
            "r: 更新、t: 棚卸し保存、e: エクスポート、g: ステージ適用",
            "入力欄では文字入力を優先。Escでカード操作へ戻る。",
        ]
    )
    header_actions = "\n".join(
        [
            "更新: review/queue JSONとdecisions.jsonを読み直す。書き込みなし。キー r。",
            "棚卸し保存: source_inventory.json/mdへ現在の件数内訳を保存する。キー t。",
            "エクスポート: 保存済み判定をexported_decisions.json/mdへまとめる。キー e。",
            "ステージ適用: source別のstaged/*_decisions.jsonを作る。運用DBや公開データは変更しない。キー g。",
        ]
    )
    return [
        heading("レビューコンソール: 判定ボタンとキーボード操作"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "ローカルレビューコンソールの判定ボタン、上部操作、キーボードだけで操作するための仕様を記録。"
        ),
        bullet(
            "採用: 候補が有効で、次のステージ済み決定エクスポートへ進めてよい。"
            "保存値は decision=accept。実際の反映内容は適用値と対象ソースごとのapply処理で決まる。"
        ),
        bullet(
            "却下: 候補が誤り、対象外、重複ノイズ、または反映しない方がよい。"
            "保存値は decision=reject。理由はメモに残し、後から同じ候補をスキップ/監査できるようにする。"
        ),
        bullet(
            "保留: 今すぐ採用も却下もせず、文脈として保持する。"
            "保存値は decision=hold。根拠が弱い、同一性が曖昧、今は扱わない候補に使う。"
        ),
        bullet(
            "要調査: 採否の前に追加確認が必要。"
            "保存値は decision=needs_research。公式確認、会場同一性、日付差分、根拠URL品質の再確認などに使う。"
        ),
        bullet(
            "保存ボタンやsキーは data/review_console/decisions.json だけを書き換える。"
            "Master RDB、NotionイベントDB、公開JSON、S3/CloudFrontは直接変更しない。"
        ),
        bullet(
            "エクスポート/ステージ適用は data/review_console/exported_decisions.* と "
            "data/review_console/staged/ まで。実運用反映は、おとまたは領域別applyスクリプトで別途確認して行う。"
        ),
        paragraph("上部ボタン:"),
        code(header_actions),
        paragraph("キーボード操作:"),
        code(shortcuts),
        bullet("運用ドキュメント: docs/review-console-operations.md"),
    ]


def append_note():
    return notion_request(
        "PATCH",
        f"/blocks/{CURRENT_WORK_PAGE_ID}/children",
        {"children": note_blocks()},
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    if args.dry_run:
        print(f"Would append review console note to current work page: {CURRENT_WORK_PAGE_ID}")
        return
    append_note()
    print("Notionの今やっていることページへレビューコンソール説明を追記しました")


if __name__ == "__main__":
    main()
