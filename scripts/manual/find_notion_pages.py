"""Find Notion pages by title query."""

import argparse
import json
import os
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


def plain_title(obj):
    props = obj.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            return "".join(part.get("plain_text", "") for part in prop.get("title", []))
    return "".join(part.get("plain_text", "") for part in obj.get("title") or [])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--page-size", type=int, default=10)
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    data = notion_request(
        "POST",
        "/search",
        {
            "query": args.query,
            "filter": {"property": "object", "value": "page"},
            "page_size": args.page_size,
        },
    )
    for item in data.get("results") or []:
        print(json.dumps({
            "id": item.get("id"),
            "title": plain_title(item),
            "url": item.get("url"),
            "archived": item.get("archived"),
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
