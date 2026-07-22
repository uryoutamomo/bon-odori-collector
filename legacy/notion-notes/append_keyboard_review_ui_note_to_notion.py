#!/usr/bin/env python3
"""Record the reusable keyboard review UI note in Notion."""

import json
import os
import urllib.request

from notion_support.notion_config import load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
TOKEN = os.environ.get("NOTION_API_TOKEN")
LEGACY_GLOSSARY_DB_ID = os.environ.get(
    "GLOSSARY_DB_ID", "989e9effc7fc40db8043a3b8e03090ee"
)
TITLE = "キーボード判定UI メモ（2026-06-11）"


def notion_request(method, path, payload=None):
    if not TOKEN:
        raise RuntimeError("NOTION_API_TOKEN is required")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{NOTION_API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Notion-Version", NOTION_VERSION)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())


def plain_title(obj):
    title = obj.get("properties", {}).get("title", {}).get("title")
    if title is None:
        title = obj.get("title") or []
    return "".join(part.get("plain_text", "") for part in title).strip()


def legacy_parent_page_id():
    db = notion_request("GET", f"/databases/{LEGACY_GLOSSARY_DB_ID}")
    parent = db.get("parent") or {}
    if parent.get("type") != "page_id":
        raise RuntimeError(f"legacy glossary parent is not a page: {parent}")
    return parent["page_id"]


def find_existing_page():
    cursor = None
    while True:
        payload = {
            "query": TITLE,
            "filter": {"property": "object", "value": "page"},
            "page_size": 20,
        }
        if cursor:
            payload["start_cursor"] = cursor
        data = notion_request("POST", "/search", payload)
        for item in data.get("results", []):
            if plain_title(item) == TITLE:
                return item["id"]
        if not data.get("has_more"):
            return ""
        cursor = data.get("next_cursor")


def rich_text(text):
    return [{"type": "text", "text": {"content": text[:2000]}}]


def paragraph(text):
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(text)}}


def heading(text):
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": rich_text(text)}}


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
        "code": {"rich_text": rich_text(text), "language": "bash"},
    }


def children():
    example = """python3 build_keyboard_review_ui.py \\
  --input data/glossary_v2_oto123_merged_terms.json \\
  --rows-key candidates \\
  --out data/glossary_v2_oto123_keyboard_review_ui.html \\
  --title 用語集v2キーボード判定UI \\
  --term-field term \\
  --category-field category \\
  --summary-fields interpretation,type,confidence,source_agent \\
  --detail-fields reason,evidence_text,evidence_url \\
  --key-fields term,category,type,evidence_url \\
  --download-name glossary_v2_oto123_keyboard_review_decisions.json \\
  --storage-key glossary-v2-oto123-keyboard-review-v1"""
    unreviewed = """python3 build_keyboard_review_ui.py \\
  --input data/glossary_v2_oto123_merged_terms.json \\
  --rows-key candidates \\
  --out data/glossary_v2_oto123_unreviewed_review_ui.html \\
  --decisions /Users/ryotauchida/Downloads/glossary_v2_oto123_review_decisions.json \\
  --exclude-decided"""
    return [
        paragraph("JSON候補リストをブラウザ上で高速に人手判定するためのローカルHTML生成ツールを追加。今回の用語集v2レビューで使った操作感を、他の候補レビューにも流用できるようにした。"),
        heading("追加したもの"),
        bullet("build_keyboard_review_ui.py: 任意のJSON配列からキーボード操作中心のレビューHTMLを生成する汎用ビルダー。"),
        bullet("--rows-key / --term-field / --category-field / --summary-fields / --detail-fields で入力JSONに合わせて表示を調整できる。"),
        bullet("--decisions と --exclude-decided で既存判定済み行を除外できる。"),
        heading("操作"),
        bullet("j / k: 次・前へ移動"),
        bullet("1: 採用、2: 不採用、3: まとめ、4: 保留"),
        bullet("n: メモ欄へ移動、Esc: メモ欄から戻る"),
        bullet("u: 未判定だけ表示、a: 全部表示、e: JSONを書き出し"),
        heading("用語集v2での実行例"),
        code(example),
        heading("判定済みを除外する例"),
        code(unreviewed),
        heading("運用メモ"),
        bullet("判定結果はブラウザのlocalStorageに保持される。"),
        bullet("書き出しボタンまたは e キーでJSONをダウンロードする。"),
        bullet("別案件で使う場合は --storage-key を案件ごとに変える。同じキーを使うとブラウザ内で判定状態が混ざる。"),
        paragraph("署名: おと（Codex）"),
    ]


def create_page(parent_page_id):
    payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "properties": {
            "title": {
                "title": [{"type": "text", "text": {"content": TITLE}}],
            }
        },
        "children": children(),
    }
    return notion_request("POST", "/pages", payload)["id"]


def append_to_page(page_id):
    payload = {"children": [paragraph("更新: 同内容を再確認。ローカルメモ docs/work-logs/2026-06-11-keyboard-review-ui.md も参照。")]}
    notion_request("PATCH", f"/blocks/{page_id}/children", payload)


def main():
    page_id = find_existing_page()
    if page_id:
        append_to_page(page_id)
        print(f"updated existing Notion page: {page_id}")
        return
    page_id = create_page(legacy_parent_page_id())
    print(f"created Notion page: {page_id}")


if __name__ == "__main__":
    main()
