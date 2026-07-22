#!/usr/bin/env python3
"""Create the glossary v2 Notion database if it does not already exist."""

import argparse
import json
import os
import urllib.request

from operation_safety.manual_apply_guards import LEGACY_NOTION_REPAIR_CONFIRMATION, require_confirmation
from notion_config import (
    EVENT_DATABASE_ID,
    VENUE_DATABASE_ID,
    load_local_env,
)


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
TITLE = "📖 盆踊ラー用語集 v2"
LEGACY_GLOSSARY_DB_ID = os.environ.get(
    "GLOSSARY_DB_ID", "989e9effc7fc40db8043a3b8e03090ee"
)
TOKEN = os.environ.get("NOTION_API_TOKEN")


def notion_request(method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{NOTION_API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Notion-Version", NOTION_VERSION)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())


def plain_title(obj):
    title = obj.get("title") or []
    return "".join(part.get("plain_text", "") for part in title).strip()


def find_existing_database():
    cursor = None
    while True:
        payload = {
            "query": TITLE,
            "filter": {"property": "object", "value": "database"},
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


def legacy_parent():
    legacy = notion_request("GET", f"/databases/{LEGACY_GLOSSARY_DB_ID}")
    parent = legacy.get("parent") or {}
    if parent.get("type") != "page_id":
        raise RuntimeError(f"legacy glossary parent is not a page: {parent}")
    return {"type": "page_id", "page_id": parent["page_id"]}


def create_database(parent):
    payload = {
        "parent": parent,
        "title": [{"type": "text", "text": {"content": TITLE}}],
        "properties": {
            "使用語": {"title": {}},
            "読み": {"rich_text": {}},
            "解釈": {"rich_text": {}},
            "種別": {
                "select": {
                    "options": [
                        {"name": "会場別名", "color": "blue"},
                        {"name": "イベント別名", "color": "purple"},
                        {"name": "曲名", "color": "pink"},
                        {"name": "行動語", "color": "green"},
                        {"name": "除外語", "color": "red"},
                        {"name": "地域語", "color": "yellow"},
                        {"name": "団体語", "color": "orange"},
                    ]
                }
            },
            "シグナル役割": {
                "multi_select": {
                    "options": [
                        {"name": "参加予告", "color": "green"},
                        {"name": "参加報告", "color": "blue"},
                        {"name": "開催示唆", "color": "purple"},
                        {"name": "会場ヒント", "color": "yellow"},
                        {"name": "曲目ヒント", "color": "pink"},
                        {"name": "除外語", "color": "red"},
                    ]
                }
            },
            "確度": {
                "select": {
                    "options": [
                        {"name": "推察", "color": "gray"},
                        {"name": "複数一致", "color": "blue"},
                        {"name": "公式確認", "color": "green"},
                        {"name": "除外確定", "color": "red"},
                    ]
                }
            },
            "ヒント先会場": {
                "relation": {
                    "database_id": VENUE_DATABASE_ID,
                    "single_property": {},
                }
            },
            "ヒント先イベント": {
                "relation": {
                    "database_id": EVENT_DATABASE_ID,
                    "single_property": {},
                }
            },
            "曲名": {"rich_text": {}},
            "出典URL": {"url": {}},
            "初出日": {"date": {}},
            "最終検出日": {"date": {}},
            "証拠数": {"number": {"format": "number"}},
            "自動適用可": {"checkbox": {}},
            "状態": {
                "select": {
                    "options": [
                        {"name": "候補", "color": "gray"},
                        {"name": "有効", "color": "green"},
                        {"name": "保留", "color": "yellow"},
                        {"name": "無効", "color": "red"},
                    ]
                }
            },
            "メモ": {"rich_text": {}},
        },
    }
    return notion_request("POST", "/databases", payload)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    if not TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    existing_id = find_existing_database()
    if existing_id:
        print(f"exists: {existing_id}")
        return
    try:
        require_confirmation(
            True,
            args.confirm,
            LEGACY_NOTION_REPAIR_CONFIRMATION,
            "legacy glossary v2 database creation",
        )
    except ValueError as exc:
        parser.error(str(exc))
    created = create_database(legacy_parent())
    print(f"created: {created['id']}")


if __name__ == "__main__":
    main()
