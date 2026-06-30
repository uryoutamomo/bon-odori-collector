#!/usr/bin/env python3
"""Apply small schema updates to the glossary v2 Notion database."""

import argparse
import json
import os
import urllib.request

from manual_apply_guards import LEGACY_NOTION_REPAIR_CONFIRMATION, require_confirmation
from notion_config import GLOSSARY_V2_DATABASE_ID, load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
TOKEN = os.environ.get("NOTION_API_TOKEN")
DB_ID = os.environ.get("GLOSSARY_V2_DB_ID") or GLOSSARY_V2_DATABASE_ID


def notion_request(method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{NOTION_API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Notion-Version", NOTION_VERSION)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    if not TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    database = notion_request("GET", f"/databases/{DB_ID}")
    props = database.get("properties", {})
    if "解釈" in props:
        print(f"ok: 解釈 property already exists in {DB_ID}")
        return
    if "正規語/表示名" not in props:
        raise SystemExit("neither 解釈 nor 正規語/表示名 exists")
    try:
        require_confirmation(
            True,
            args.confirm,
            LEGACY_NOTION_REPAIR_CONFIRMATION,
            "legacy glossary v2 schema update",
        )
    except ValueError as exc:
        parser.error(str(exc))
    notion_request("PATCH", f"/databases/{DB_ID}", {
        "properties": {
            "正規語/表示名": {"name": "解釈"}
        }
    })
    print(f"renamed: 正規語/表示名 -> 解釈 ({DB_ID})")


if __name__ == "__main__":
    main()
