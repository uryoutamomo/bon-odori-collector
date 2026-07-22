#!/usr/bin/env python3
"""Record the current public/internal event count interpretation in Notion."""

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
TITLE = "Web公開イベント数の解釈メモ（2026-06-13）"


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


def children():
    return [
        heading("結論"),
        paragraph("今のWeb公開仕様で、実際に見せられる盆踊りイベント数は168件。内部DB全体では206件あり、差分38件は主に23区外・会場未紐づけ・公開対象外のイベント。"),
        heading("意味"),
        bullet("Web上でユーザーが確認できる現在の実数は168件として見るのがよい。"),
        bullet("内部DBの206件は、Web公開済みだけでなく、来年の名寄せ・追加調査・23区外実績も含む運用資産。"),
        bullet("差分38件は、追加情報があれば公開できるものもあるが、23区外のものは現在の公開仕様では情報が増えても表示対象外。"),
        bullet("したがって、現行サイトの把握力を評価する指標は168件、将来の収集・照合に使う蓄積量は206件と分けて考える。"),
        heading("補足"),
        paragraph("今回のX過去分調査で、浅草橋マロニエまつり盆踊りは23区内の過去実績として公開側にも追加された。一方、藤沢・秋田・足寄・笠間などは内部DBには入っているが、23区外のため公開JSONからは除外されている。"),
        paragraph("署名: おと（Codex）"),
    ]


def create_page(parent_page_id):
    payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "properties": {
            "title": {"title": [{"type": "text", "text": {"content": TITLE}}]},
        },
        "children": children(),
    }
    return notion_request("POST", "/pages", payload)["id"]


def append_to_page(page_id):
    payload = {"children": [heading("更新"), *children()]}
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
