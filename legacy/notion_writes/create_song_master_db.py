#!/usr/bin/env python3
"""Create the Notion song master database and connect glossary v2 to it."""

import argparse
import json
import os
import urllib.request

from operation_safety.manual_apply_guards import LEGACY_NOTION_REPAIR_CONFIRMATION, require_confirmation
from notion_support.notion_config import (
    EVENT_DATABASE_ID,
    GLOSSARY_V2_DATABASE_ID,
    SONG_MASTER_DATABASE_ID,
    VENUE_DATABASE_ID,
    load_local_env,
)


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
TITLE = "🎵 盆踊り曲マスタ"
TOKEN = os.environ.get("NOTION_API_TOKEN")
GLOSSARY_DB_ID = os.environ.get("GLOSSARY_V2_DB_ID") or GLOSSARY_V2_DATABASE_ID
SONG_DB_ID = os.environ.get("SONG_MASTER_DB_ID") or SONG_MASTER_DATABASE_ID


def notion_request(method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{NOTION_API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Notion-Version", NOTION_VERSION)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())


def plain_title(obj):
    return "".join(part.get("plain_text", "") for part in obj.get("title") or []).strip()


def find_existing_database():
    if SONG_DB_ID:
        return SONG_DB_ID
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


def parent_from_glossary():
    glossary = notion_request("GET", f"/databases/{GLOSSARY_DB_ID}")
    parent = glossary.get("parent") or {}
    if parent.get("type") != "page_id":
        raise RuntimeError(f"glossary v2 parent is not a page: {parent}")
    return {"type": "page_id", "page_id": parent["page_id"]}


def create_database(parent):
    payload = {
        "parent": parent,
        "title": [{"type": "text", "text": {"content": TITLE}}],
        "properties": {
            "曲名": {"title": {}},
            "分類": {
                "select": {
                    "options": [
                        {"name": "ご当地曲", "color": "blue"},
                        {"name": "定番曲", "color": "green"},
                        {"name": "ジャンル総称", "color": "purple"},
                        {"name": "未分類", "color": "gray"},
                    ]
                }
            },
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
            "会場": {"relation": {"database_id": VENUE_DATABASE_ID, "single_property": {}}},
            "イベント": {"relation": {"database_id": EVENT_DATABASE_ID, "single_property": {}}},
            "出典・音源URL": {"url": {}},
            "証拠数": {"number": {"format": "number"}},
            "メモ": {"rich_text": {}},
        },
    }
    return notion_request("POST", "/databases", payload)


def ensure_glossary_relation(song_db_id):
    glossary = notion_request("GET", f"/databases/{GLOSSARY_DB_ID}")
    props = glossary.get("properties", {})
    if "ヒント先曲" in props:
        return "exists"
    notion_request(
        "PATCH",
        f"/databases/{GLOSSARY_DB_ID}",
        {
            "properties": {
                "ヒント先曲": {
                    "relation": {
                        "database_id": song_db_id,
                        "single_property": {},
                    }
                }
            }
        },
    )
    return "created"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    if not TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    try:
        require_confirmation(
            not args.dry_run,
            args.confirm,
            LEGACY_NOTION_REPAIR_CONFIRMATION,
            "legacy song master database setup",
        )
    except ValueError as exc:
        parser.error(str(exc))
    existing = find_existing_database()
    if existing:
        song_db_id = existing
        created = False
    elif args.dry_run:
        print(f"dry-run create database: {TITLE}")
        print("dry-run add glossary relation: ヒント先曲")
        return
    else:
        created_db = create_database(parent_from_glossary())
        song_db_id = created_db["id"]
        created = True

    relation_status = "dry-run"
    if not args.dry_run:
        relation_status = ensure_glossary_relation(song_db_id)

    print(("created" if created else "exists") + f": {song_db_id}")
    print(f"glossary relation ヒント先曲: {relation_status}")
    print(f"set SONG_MASTER_DB_ID={song_db_id}")


if __name__ == "__main__":
    main()
