"""Add the current-work index link to the visible Notion first-look section."""

import argparse
import json
import os
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from manual_apply_guards import NOTION_WORKLOG_MAINTENANCE_CONFIRMATION, require_confirmation
from notion_config import load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")
DEFAULT_PARENT_PAGE_ID = "3708be04-e762-811d-bbb7-c984b14fe452"
CURRENT_WORK = Path("data/notion_current_work_index.json")
OUT = Path("data/notion_current_work_first_look_link.json")


def rich_text(text, href=None):
    text_obj = {"content": str(text or "")[:2000]}
    if href:
        text_obj["link"] = {"url": href}
    return [{"type": "text", "text": text_obj}]


def first_look_link_block(url):
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": rich_text("今やっていること", url)
        },
    }


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


def block_text(block):
    btype = block.get("type")
    if btype in {"paragraph", "heading_1", "heading_2", "heading_3", "bulleted_list_item"}:
        rich = (block.get(btype) or {}).get("rich_text") or []
        return "".join(part.get("plain_text", "") for part in rich)
    if btype == "child_page":
        return (block.get("child_page") or {}).get("title") or ""
    return ""


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


def first_look_insert_after_id(blocks):
    in_first_look = False
    last_in_section = None
    for block in blocks:
        btype = block.get("type")
        text = block_text(block)
        if btype in {"heading_1", "heading_2", "heading_3"} and "まず見る" in text:
            in_first_look = True
            last_in_section = block
            continue
        if in_first_look and btype in {"heading_1", "heading_2", "heading_3"}:
            break
        if in_first_look:
            if "今やっていること" in text:
                return None
            last_in_section = block
    if not last_in_section:
        raise RuntimeError("Notion page does not contain a visible 'まず見る' section")
    return last_in_section.get("id")


def append_after(parent_page_id, after_block_id, block):
    notion_request(
        "PATCH",
        f"/blocks/{parent_page_id}/children",
        {"after": after_block_id, "children": [block]},
    )


def load_json(path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".tmp-", suffix=".json", delete=False
    ) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        tmp_name = handle.name
    Path(tmp_name).replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-page-id", default=DEFAULT_PARENT_PAGE_ID)
    parser.add_argument("--current-work-json", default=str(CURRENT_WORK))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    try:
        require_confirmation(
            True,
            args.confirm,
            NOTION_WORKLOG_MAINTENANCE_CONFIRMATION,
            "current work first-look link update",
        )
    except ValueError as exc:
        parser.error(str(exc))
    current_work = load_json(args.current_work_json)
    url = current_work.get("url") or ""
    if not url:
        raise SystemExit("current work URL is missing")

    blocks = children(args.parent_page_id)
    after_id = first_look_insert_after_id(blocks)
    created = False
    if after_id:
        append_after(args.parent_page_id, after_id, first_look_link_block(url))
        created = True

    output = {
        "generated_by": "add_current_work_to_first_look_notion.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "parent_page_id": args.parent_page_id,
        "current_work_url": url,
        "inserted": created,
        "after_block_id": after_id,
    }
    atomic_write_json(args.out, output)
    if created:
        print(f"Notionの「まず見る」に今やっていることリンクを追加しました: {url}")
    else:
        print(f"Notionの「まず見る」には既に今やっていることリンクがあります: {url}")


if __name__ == "__main__":
    main()
