"""Rename the visible Notion first-look current-work link."""

import argparse
import json
import os
import urllib.request

from manual_apply_guards import NOTION_WORKLOG_MAINTENANCE_CONFIRMATION, require_confirmation
from notion_config import load_local_env
from add_current_work_to_first_look_notion import rich_text


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")
DEFAULT_BLOCK_ID = "37f8be04-e762-8130-8ef1-e65d29038fc6"
CURRENT_WORK_URL = "https://app.notion.com/p/37f8be04e762815c9f62d76866ca9e83"


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    try:
        require_confirmation(
            True,
            args.confirm,
            NOTION_WORKLOG_MAINTENANCE_CONFIRMATION,
            "current work first-look link rename",
        )
    except ValueError as exc:
        parser.error(str(exc))
    notion_request(
        "PATCH",
        f"/blocks/{DEFAULT_BLOCK_ID}",
        {
            "bulleted_list_item": {
                "rich_text": rich_text("今やっていること", CURRENT_WORK_URL)
            }
        },
    )
    print("Notionの「まず見る」リンク名を「今やっていること」に変更しました")


if __name__ == "__main__":
    main()
