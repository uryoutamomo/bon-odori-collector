#!/usr/bin/env python3
"""Apply the reviewed glossary v2 first batch decisions."""

import argparse
import json
import os
import urllib.request

from manual_apply_guards import LEGACY_NOTION_REPAIR_CONFIRMATION, require_confirmation
from notion_support.notion_config import EVENT_DATABASE_ID, GLOSSARY_V2_DATABASE_ID, load_local_env
from legacy.notion_writes.register_glossary_v2_seed_candidates import selected_candidates


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
TOKEN = os.environ.get("NOTION_API_TOKEN")
GLOSSARY_DB_ID = os.environ.get("GLOSSARY_V2_DB_ID") or GLOSSARY_V2_DATABASE_ID
GUJO_TERM = "郡上おどり"
GUJO_REQUESTED_EVENT_NAME = "郡上おどり in 青山 2026"
GUJO_CURRENT_EVENT_NAME = "郡上おどり in 青山"
GUJO_EVENT_SEARCH = "郡上おどり in 青山"


def notion_request(method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{NOTION_API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Notion-Version", NOTION_VERSION)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())


def rich_text(value):
    return [{"type": "text", "text": {"content": value}}] if value else []


def query_page_by_title(database_id, property_name, value, match="equals"):
    data = notion_request("POST", f"/databases/{database_id}/query", {
        "filter": {"property": property_name, "title": {match: value}},
        "page_size": 5,
    })
    return data.get("results", [])


def glossary_page(term):
    rows = query_page_by_title(GLOSSARY_DB_ID, "使用語", term)
    if not rows:
        raise RuntimeError(f"glossary term not found: {term}")
    if len(rows) > 1:
        raise RuntimeError(f"glossary term is duplicated: {term}")
    return rows[0]


def event_page(name):
    rows = query_page_by_title(EVENT_DATABASE_ID, "イベント名", name)
    if not rows and name == GUJO_REQUESTED_EVENT_NAME:
        rows = query_page_by_title(EVENT_DATABASE_ID, "イベント名", GUJO_CURRENT_EVENT_NAME)
    if not rows and name == GUJO_REQUESTED_EVENT_NAME:
        rows = query_page_by_title(
            EVENT_DATABASE_ID, "イベント名", GUJO_EVENT_SEARCH, match="contains"
        )
    if not rows:
        raise RuntimeError(f"event not found: {name}")
    if len(rows) > 1:
        names = [
            "".join(
                part.get("plain_text", "")
                for part in row.get("properties", {}).get("イベント名", {}).get("title", [])
            )
            for row in rows
        ]
        raise RuntimeError(f"event is duplicated: {name}: {names}")
    return rows[0]


def reviewed_terms():
    terms = [row["term"] for row in selected_candidates(30)]
    if GUJO_TERM not in terms:
        raise RuntimeError(f"{GUJO_TERM} is not in selected first batch")
    return terms


def promote_props():
    return {
        "状態": {"select": {"name": "有効"}},
        "確度": {"select": {"name": "複数一致"}},
        "自動適用可": {"checkbox": True},
    }


def gujo_props(event_id, event_name):
    return {
        "解釈": {"rich_text": rich_text(event_name)},
        "種別": {"select": {"name": "イベント別名"}},
        "シグナル役割": {"multi_select": [{"name": "開催示唆"}]},
        "状態": {"select": {"name": "有効"}},
        "確度": {"select": {"name": "複数一致"}},
        "自動適用可": {"checkbox": False},
        "ヒント先イベント": {"relation": [{"id": event_id}]},
        "メモ": {
            "rich_text": rich_text(
                "初期30件レビューで多義語として修正。"
                "イベント別名としては有効だが、文脈判定が必要なため自動適用はOFF。"
            )
        },
    }


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
            "legacy reviewed glossary v2 promotion",
        )
    except ValueError as exc:
        parser.error(str(exc))

    terms = reviewed_terms()
    gujo_event = event_page(GUJO_REQUESTED_EVENT_NAME)
    gujo_event_name = (
        "".join(
            part.get("plain_text", "")
            for part in (
                gujo_event.get("properties", {})
                .get("イベント名", {})
                .get("title", [])
            )
        ).strip()
        or GUJO_REQUESTED_EVENT_NAME
    )
    promoted = 0
    for term in terms:
        page = glossary_page(term)
        if term == GUJO_TERM:
            props = gujo_props(gujo_event["id"], gujo_event_name)
            action = f"fix {term} -> {gujo_event_name}"
        else:
            props = promote_props()
            action = f"promote {term}"
        if args.dry_run:
            print(f"dry-run {action}")
        else:
            notion_request("PATCH", f"/pages/{page['id']}", {"properties": props})
            print(action)
        promoted += 1
    print(f"done: touched={promoted} dry_run={args.dry_run}")


if __name__ == "__main__":
    main()
