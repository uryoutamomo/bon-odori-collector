"""Inspect children blocks of a Notion page."""

import argparse
import json
import os
import urllib.parse
import urllib.request

from notion_config import load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")


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


def rich_text(block, key):
    value = (block.get(key) or {}).get("rich_text") or []
    return "".join(part.get("plain_text", "") for part in value)


def block_text(block):
    btype = block.get("type")
    if btype in {"paragraph", "heading_1", "heading_2", "heading_3", "bulleted_list_item", "to_do"}:
        return rich_text(block, btype)
    if btype == "child_page":
        return (block.get("child_page") or {}).get("title") or ""
    if btype == "link_to_page":
        return json.dumps(block.get("link_to_page") or {}, ensure_ascii=False)
    return ""


def block_checked(block):
    if block.get("type") != "to_do":
        return None
    return bool((block.get("to_do") or {}).get("checked"))


def children(block_id):
    rows = []
    cursor = ""
    while True:
        query = "?page_size=100"
        if cursor:
            query += "&" + urllib.parse.urlencode({"start_cursor": cursor})
        data = notion_request("GET", f"/blocks/{block_id}/children{query}")
        rows.extend(data.get("results") or [])
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor") or ""
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("page_id")
    parser.add_argument("--children", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    for idx, block in enumerate(children(args.page_id), start=1):
        print(json.dumps({
            "index": idx,
            "id": block.get("id"),
            "type": block.get("type"),
            "has_children": block.get("has_children"),
            "checked": block_checked(block),
            "text": block_text(block),
        }, ensure_ascii=False))
        if args.children and block.get("has_children"):
            for child_idx, child in enumerate(children(block["id"]), start=1):
                print(json.dumps({
                    "index": f"{idx}.{child_idx}",
                    "id": child.get("id"),
                    "type": child.get("type"),
                    "has_children": child.get("has_children"),
                    "checked": block_checked(child),
                    "text": block_text(child),
                }, ensure_ascii=False))


if __name__ == "__main__":
    main()
