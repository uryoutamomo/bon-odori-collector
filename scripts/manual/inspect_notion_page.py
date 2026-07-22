#!/usr/bin/env python3
"""Print a compact Notion page inspection for a page id."""

import argparse
import json
import os

from notion_support.notion_api import NotionApi, plain_text
from notion_config import load_local_env


def compact_prop(prop):
    prop_type = prop.get("type")
    if prop_type in {"title", "rich_text", "select", "url"}:
        return plain_text(prop)
    if prop_type == "date":
        return prop.get("date")
    if prop_type == "checkbox":
        return prop.get("checkbox")
    if prop_type == "relation":
        return [item.get("id") for item in prop.get("relation", [])]
    if prop_type == "number":
        return prop.get("number")
    return {"type": prop_type}


def inspect_page(api, page_id):
    page = api.retrieve_page(page_id)
    props = page.get("properties") or {}
    return {
        "id": page.get("id"),
        "url": page.get("url"),
        "parent": page.get("parent"),
        "archived": page.get("archived"),
        "created_time": page.get("created_time"),
        "last_edited_time": page.get("last_edited_time"),
        "properties": {name: compact_prop(prop) for name, prop in props.items()},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("page_id")
    args = parser.parse_args()

    load_local_env()
    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    print(json.dumps(inspect_page(api, args.page_id), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
