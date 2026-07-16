#!/usr/bin/env python3
"""Append the review console operations manual to the Notion operations manual."""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone

from notion_config import load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")
NOTION_VERSION = "2022-06-28"
DEFAULT_QUERY = "運用マニュアル"


def notion_request(method, path, payload=None):
    if not NOTION_TOKEN:
        raise RuntimeError("NOTION_API_TOKEN is not set")
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        NOTION_API + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def plain_title(page):
    props = page.get("properties", {})
    title_parts = []
    for prop in props.values():
        if prop.get("type") == "title":
            title_parts = prop.get("title") or []
            break
    if not title_parts:
        title_parts = page.get("title") or []
    return "".join(part.get("plain_text", "") for part in title_parts).strip()


def search_pages(query):
    cursor = None
    results = []
    while True:
        payload = {
            "query": query,
            "filter": {"property": "object", "value": "page"},
            "sort": {"direction": "descending", "timestamp": "last_edited_time"},
            "page_size": 20,
        }
        if cursor:
            payload["start_cursor"] = cursor
        data = notion_request("POST", "/search", payload)
        for item in data.get("results", []):
            title = plain_title(item)
            if title:
                results.append(
                    {
                        "id": item["id"],
                        "title": title,
                        "url": item.get("url", ""),
                        "last_edited_time": item.get("last_edited_time", ""),
                    }
                )
        if not data.get("has_more"):
            return results
        cursor = data.get("next_cursor")


def choose_manual_page(query, page_id=""):
    if page_id:
        page = notion_request("GET", f"/pages/{page_id}")
        return {
            "id": page_id,
            "title": plain_title(page),
            "url": page.get("url", ""),
            "last_edited_time": page.get("last_edited_time", ""),
        }, []
    candidates = search_pages(query)
    if not candidates:
        return None, []
    exact = [row for row in candidates if row["title"] == query]
    if exact:
        return exact[0], candidates
    contains = [row for row in candidates if "運用マニュアル" in row["title"]]
    if contains:
        return contains[0], candidates
    return candidates[0], candidates


def rich_text(text):
    return [{"type": "text", "text": {"content": str(text or "")[:2000]}}]


def heading_2(text):
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": rich_text(text)}}


def heading_3(text):
    return {"object": "block", "type": "heading_3", "heading_3": {"rich_text": rich_text(text)}}


def paragraph(text):
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(text)}}


def bullet(text):
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": rich_text(text)},
    }


def numbered(text):
    return {
        "object": "block",
        "type": "numbered_list_item",
        "numbered_list_item": {"rich_text": rich_text(text)},
    }


def code(text):
    return {
        "object": "block",
        "type": "code",
        "code": {"rich_text": rich_text(text), "language": "plain text"},
    }


def manual_blocks():
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    shortcuts = "\n".join(
        [
            "j/↓: 次の候補、k/↑: 前の候補",
            "1: 採用、2: 却下、3: 保留、4: 要調査",
            "s: 保存、c: 解除、n: メモ、v: 適用値、i: JSON詳細、o: 最初の根拠URL",
            "/: 検索、u: 未レビュー、a: 全件、d: 決定済み、p: 処理済み",
            "r: 更新、t: 棚卸し保存、e: エクスポート、g: ステージ適用、?: 操作ガイド",
            "入力欄では文字入力を優先。Escでカード操作へ戻る。",
        ]
    )
    return [
        heading_2("レビューコンソール運用マニュアル"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "ローカルレビューコンソール（http://127.0.0.1:8751/）の画面構成、判定、上部ボタン、ショートカット、保存先、反映境界を整理。"
        ),
        heading_3("位置づけ"),
        bullet("レビュー候補が溜まっているかを確認し、内田さんの判断を保存・エクスポート・ステージ化するためのローカル専用画面。"),
        bullet("Master RDB、NotionイベントDB、公開JSON、S3/CloudFront、DynamoDB、Google Calendarは直接変更しない。"),
        bullet("ステージ適用は本番反映ではなく、data/review_console/staged/ にapply用パケットを作るだけ。"),
        heading_3("画面構成"),
        bullet("上部: 操作ガイド、更新、棚卸し保存、エクスポート、ステージ適用。各ボタン横にショートカットを表示。"),
        bullet("左: 全件/未レビュー/決定済み/処理済み、検索、種類、簡易ショートカット、ソース別フィルタ。"),
        bullet("中央: レビューカード一覧。緑枠が現在選択中のカード。URLチップは根拠URLや動画URL。"),
        bullet("右: 判定パネル。採用/却下/保留/要調査、適用値、メモ、保存、解除、JSON詳細。"),
        heading_3("日常手順"),
        numbered("開く: http://127.0.0.1:8751/"),
        numbered("uで未レビューに絞り、左側の種類別件数を見る。"),
        numbered("j/kで候補を移動し、必要ならoで根拠URL、iでJSON詳細を見る。"),
        numbered("1/2/3/4で採用・却下・保留・要調査を選ぶ。"),
        numbered("必要ならnでメモ、vで適用値を入力する。"),
        numbered("sで保存する。保存先はdata/review_console/decisions.jsonのみ。"),
        numbered("まとまったらeでエクスポートし、gでステージ適用する。"),
        numbered("おと、または領域別applyスクリプトがstagedファイルを確認してから実運用反映する。"),
        heading_3("判定ボタン"),
        bullet("採用 1: 候補が有効。次のエクスポート/ステージ対象にする。保存値はdecision=accept。"),
        bullet("却下 2: 誤り、対象外、重複ノイズ、反映しない方がよい候補。保存値はdecision=reject。"),
        bullet("保留 3: 今すぐ採否を決めない。根拠が弱い、同一性が曖昧、今は扱わない候補。保存値はdecision=hold。"),
        bullet("要調査 4: 採否前に公式確認、会場同一性、日付差分、根拠URL品質などの追加確認が必要。保存値はdecision=needs_research。"),
        heading_3("上部ボタン"),
        bullet("更新 r: review/queue JSONとdecisions.jsonを読み直す。書き込みなし。"),
        bullet("棚卸し保存 t: 現在の件数内訳をdata/review_console/source_inventory.json/mdへ保存する。"),
        bullet("エクスポート e: 保存済み判定をdata/review_console/exported_decisions.json/mdへまとめる。"),
        bullet("ステージ適用 g: ソース別にdata/review_console/staged/*_decisions.jsonを作る。本番DBや公開データは変更しない。"),
        heading_3("ショートカット"),
        code(shortcuts),
        heading_3("保存先と反映境界"),
        bullet("保存/解除: data/review_console/decisions.jsonだけを変更。元のreview/queue JSONは変更しない。"),
        bullet("棚卸し保存: data/review_console/source_inventory.json/mdだけを変更。"),
        bullet("エクスポート: data/review_console/exported_decisions.json/mdだけを変更。"),
        bullet("ステージ適用: data/review_console/staged/だけを変更。運用DB、Notion、公開JSON、S3/CloudFrontは変更しない。"),
        heading_3("確認用コマンド"),
        code(
            "\n".join(
                [
                    "cd /Users/ryotauchida/bon-odori-collector",
                    "python3 run_review_console.py --inventory",
                    "python3 run_review_console.py --export",
                    "python3 apply_review_console_decisions.py --write",
                    "python3 -m pytest tests/test_review_console.py",
                    "node --check review_console/static/app.js",
                ]
            )
        ),
        paragraph("ローカル詳細版: docs/review-console-operations.md"),
    ]


def append_blocks(page_id):
    return notion_request("PATCH", f"/blocks/{page_id}/children", {"children": manual_blocks()})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--page-id", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    target, candidates = choose_manual_page(args.query, args.page_id)
    if not target:
        raise SystemExit(f"No Notion page found for query: {args.query}")

    if args.dry_run:
        print(f"Target: {target['title']} / {target['id']} / {target.get('url', '')}")
        print("Candidates:")
        for row in candidates[:10]:
            print(f"- {row['title']} / {row['id']} / {row.get('last_edited_time', '')}")
        return

    append_blocks(target["id"])
    print(f"Notion運用マニュアルへレビューコンソール運用マニュアルを追記しました: {target['title']} / {target['id']}")


if __name__ == "__main__":
    main()
