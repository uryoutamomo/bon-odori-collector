#!/usr/bin/env python3
"""Append the public event publication flow diagrams to the Notion manual."""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from notion_config import load_local_env


load_local_env()

ROOT = Path(__file__).resolve().parent
FLOW_DOC = ROOT / "docs" / "public-event-publication-flow.md"
NOTION_API = "https://api.notion.com/v1"
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")
NOTION_VERSION = "2022-06-28"
DEFAULT_QUERY = "運用マニュアル"


def notion_request(method, path, payload=None):
    if not NOTION_TOKEN:
        raise RuntimeError("NOTION_API_TOKEN is not set")
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        NOTION_API + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def plain_title(page):
    props = page.get("properties", {})
    title_parts = []
    for prop in props.values():
        if prop.get("type") == "title":
            title_parts = prop.get("title") or []
            break
    if not title_parts:
        title_parts = page.get("title") or []
    return "".join(part.get("plain_text", "") for part in title_parts).strip()


def search_pages(query):
    cursor = None
    results = []
    while True:
        payload = {
            "query": query,
            "filter": {"property": "object", "value": "page"},
            "sort": {"direction": "descending", "timestamp": "last_edited_time"},
            "page_size": 20,
        }
        if cursor:
            payload["start_cursor"] = cursor
        data = notion_request("POST", "/search", payload)
        for item in data.get("results", []):
            title = plain_title(item)
            if title:
                results.append(
                    {
                        "id": item["id"],
                        "title": title,
                        "url": item.get("url", ""),
                        "last_edited_time": item.get("last_edited_time", ""),
                    }
                )
        if not data.get("has_more"):
            return results
        cursor = data.get("next_cursor")


def choose_manual_page(query, page_id=""):
    if page_id:
        page = notion_request("GET", f"/pages/{page_id}")
        return {
            "id": page_id,
            "title": plain_title(page),
            "url": page.get("url", ""),
            "last_edited_time": page.get("last_edited_time", ""),
        }, []
    candidates = search_pages(query)
    if not candidates:
        return None, []
    exact = [row for row in candidates if row["title"] == query]
    if exact:
        return exact[0], candidates
    contains = [row for row in candidates if "運用マニュアル" in row["title"]]
    if contains:
        return contains[0], candidates
    return candidates[0], candidates


def rich_text(text):
    value = str(text or "")
    return [{"type": "text", "text": {"content": value[:2000]}}]


def rich_text_chunks(text):
    value = str(text or "")
    if not value:
        return []
    return [
        {"type": "text", "text": {"content": value[index : index + 2000]}}
        for index in range(0, len(value), 2000)
    ]


def heading_2(text):
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": rich_text(text)}}


def heading_3(text):
    return {"object": "block", "type": "heading_3", "heading_3": {"rich_text": rich_text(text)}}


def paragraph(text):
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(text)}}


def bullet(text):
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": rich_text(text)},
    }


def code_block(text, language="mermaid"):
    return {
        "object": "block",
        "type": "code",
        "code": {
            "rich_text": rich_text_chunks(text),
            "language": language,
        },
    }


def extract_mermaid_sections(markdown):
    sections = []
    current_heading = ""
    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("## "):
            current_heading = line[3:].strip()
        if line.strip() == "```mermaid":
            index += 1
            block = []
            while index < len(lines) and lines[index].strip() != "```":
                block.append(lines[index])
                index += 1
            sections.append((current_heading or "Flow Diagram", "\n".join(block).strip()))
        index += 1
    return sections


def flow_blocks():
    markdown = FLOW_DOC.read_text(encoding="utf-8")
    mermaid_sections = extract_mermaid_sections(markdown)
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    blocks = [
        heading_2("公開イベント反映フロー図"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "鉄砲洲のような「根拠はあるが、会場・日程がmaster RDBに昇格しておらず公開JSONに出ない」ケースを防ぐための正規フロー。"
        ),
        heading_3("正本と禁止事項"),
        bullet("正本は data/bon_odori_master.sqlite。公開JSONとサイト側JSONは生成物として扱う。"),
        bullet("公開JSONを手で直して、master RDBの未整備を隠さない。"),
        bullet("source_urlだけを入れて、会場・日程・statusを更新したつもりにしない。"),
        bullet("guard_public_events_sync.py の pass はデプロイ承認ではない。公開反映には内田さんの明示承認が必要。"),
        heading_3("ローカル原本"),
        code_block(str(FLOW_DOC), "plain text"),
    ]
    for title, diagram in mermaid_sections:
        blocks.append(heading_3(title))
        blocks.append(code_block(diagram, "mermaid"))
    blocks.extend(
        [
            heading_3("鉄砲洲型ケースの止まり方"),
            bullet("publication_gap_review.json では event_publication_blocked / P0 として検出する。"),
            bullet("missing_venue_id がある場合は、公開同期へ進まず会場レビューと occurrence 更新へ戻す。"),
            bullet("missing_date_start がある場合は、根拠本文を確認して date_start/date_end/date_status を反映する。"),
            bullet("修正後に export_public_events.py と guard_public_events_sync.py を通し、site repo同期とデプロイ承認へ進む。"),
        ]
    )
    return blocks


def append_blocks(page_id, blocks):
    notion_request("PATCH", f"/blocks/{page_id}/children", {"children": blocks})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--page-id", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    target, candidates = choose_manual_page(args.query, args.page_id)
    if not target:
        raise SystemExit(f"No Notion page found for query: {args.query}")

    blocks = flow_blocks()
    if args.dry_run:
        print(f"Target: {target['title']} / {target['id']} / {target.get('url', '')}")
        print(f"Blocks: {len(blocks)}")
        print("Candidates:")
        for row in candidates[:10]:
            print(f"- {row['title']} / {row['id']} / {row.get('last_edited_time', '')}")
        return

    append_blocks(target["id"], blocks)
    print(f"Notionへ公開イベント反映フロー図を追記しました: {target['title']} / {target['id']} / {target.get('url', '')}")


if __name__ == "__main__":
    main()
