#!/usr/bin/env python3
"""Migrate legacy glossary venue aliases into glossary v2 as review candidates."""

import argparse
import json
import os
import urllib.request

from notion_config import GLOSSARY_V2_DATABASE_ID, load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
TOKEN = os.environ.get("NOTION_API_TOKEN")
LEGACY_DB_ID = os.environ.get("GLOSSARY_DB_ID", "989e9effc7fc40db8043a3b8e03090ee")
V2_DB_ID = os.environ.get("GLOSSARY_V2_DB_ID") or GLOSSARY_V2_DATABASE_ID


def notion_request(method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{NOTION_API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Notion-Version", NOTION_VERSION)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())


def plain(prop):
    if not prop:
        return ""
    kind = prop.get("type")
    values = prop.get(kind) or []
    if isinstance(values, list):
        return "".join(part.get("plain_text", "") for part in values).strip()
    return ""


def select_name(prop):
    value = (prop or {}).get("select") or {}
    return value.get("name") or ""


def rich_text(value, limit=1900):
    value = str(value or "")[:limit]
    return [{"type": "text", "text": {"content": value}}] if value else []


def iter_legacy_aliases():
    cursor = None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        data = notion_request("POST", f"/databases/{LEGACY_DB_ID}/query", payload)
        for row in data.get("results", []):
            props = row.get("properties", {})
            canonical = plain(props.get("正規名称"))
            aliases_raw = plain(props.get("表記ゆれ"))
            kind = select_name(props.get("種別"))
            confidence = select_name(props.get("確度"))
            source = ((props.get("出典") or {}).get("url") or "").strip()
            if not canonical or kind not in ("", "会場名"):
                continue
            for alias in [a.strip() for a in aliases_raw.split(",") if a.strip()]:
                if alias and alias != canonical:
                    yield {
                        "term": alias,
                        "interpretation": canonical,
                        "legacy_confidence": confidence,
                        "source": source,
                    }
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")


def existing_term(term):
    data = notion_request("POST", f"/databases/{V2_DB_ID}/query", {
        "filter": {"property": "使用語", "title": {"equals": term}},
        "page_size": 1,
    })
    return bool(data.get("results"))


def create_props(row):
    props = {
        "使用語": {"title": [{"type": "text", "text": {"content": row["term"][:200]}}]},
        "解釈": {"rich_text": rich_text(row["interpretation"])},
        "種別": {"select": {"name": "会場別名"}},
        "シグナル役割": {"multi_select": [{"name": "会場ヒント"}]},
        "確度": {"select": {"name": "推察"}},
        "状態": {"select": {"name": "候補"}},
        "自動適用可": {"checkbox": False},
        "証拠数": {"number": 1},
        "メモ": {
            "rich_text": rich_text(
                "旧用語集DBからの会場別名候補移行\n"
                f"旧確度: {row.get('legacy_confidence') or '未設定'}"
            )
        },
    }
    if row.get("source"):
        props["出典URL"] = {"url": row["source"]}
    return props


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    created = 0
    skipped = 0
    for row in iter_legacy_aliases():
        if created >= args.limit:
            break
        term = row["term"]
        if existing_term(term):
            skipped += 1
            print(f"skip existing: {term}")
            continue
        if args.dry_run:
            print(f"dry-run create: {term} -> {row['interpretation']}")
            created += 1
            continue
        notion_request("POST", "/pages", {
            "parent": {"database_id": V2_DB_ID},
            "properties": create_props(row),
        })
        created += 1
        print(f"created: {term} -> {row['interpretation']}")
    print(f"done: created={created} skipped={skipped} dry_run={args.dry_run}")


if __name__ == "__main__":
    main()
