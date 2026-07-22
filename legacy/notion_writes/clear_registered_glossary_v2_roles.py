#!/usr/bin/env python3
"""Clear signal roles for the glossary v2 rows created by the review import."""

import argparse
import json
import os
import urllib.request
from pathlib import Path

from manual_apply_guards import LEGACY_NOTION_REPAIR_CONFIRMATION, require_confirmation
from notion_support.notion_config import load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
TOKEN = os.environ.get("NOTION_API_TOKEN")
SOURCE = Path("data/glossary_v2_oto123_registered_terms.json")


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
    try:
        require_confirmation(
            True,
            args.confirm,
            LEGACY_NOTION_REPAIR_CONFIRMATION,
            "legacy glossary role cleanup",
        )
    except ValueError as exc:
        parser.error(str(exc))

    if not TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    cleared = 0
    for row in data.get("created", []):
        page_id = row.get("page_id")
        term = row.get("term", "")
        if not page_id:
            continue
        notion_request(
            "PATCH",
            f"/pages/{page_id}",
            {"properties": {"シグナル役割": {"multi_select": []}}},
        )
        cleared += 1
        print(f"cleared roles: {term}")
    print(f"done: cleared={cleared}")


if __name__ == "__main__":
    main()
