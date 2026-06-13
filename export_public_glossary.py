#!/usr/bin/env python3
"""Export glossary v2 terms for the public Yoimatsuri site.

The public JSON intentionally omits operational review notes and raw evidence.
It keeps enough structure for the site UI to group, search, and filter terms.
"""

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from notion_config import (
    GLOSSARY_V2_DATABASE_ID,
    NOTION_API_BASE,
    load_local_env,
)


load_local_env()

NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")
DB_ID = os.environ.get("GLOSSARY_V2_DB_ID") or GLOSSARY_V2_DATABASE_ID
DEFAULT_OUT = Path.home() / "bon-odori-site" / "data" / "glossary_public.json"
NOTION_VERSION = "2022-06-28"

PUBLIC_STATES = {"候補", "有効", "保留"}
EXCLUDED_KINDS = {"除外語"}
EXCLUDED_CONFIDENCES = {"除外確定"}

KIND_LABELS = {
    "会場別名": "会場の呼び名",
    "イベント別名": "イベントの呼び名",
    "曲名": "曲名・踊り名",
    "行動語": "参加・行動",
    "地域語": "地域語",
    "団体語": "呼び名・略語",
}

KIND_ORDER = {
    "行動語": 0,
    "団体語": 1,
    "地域語": 2,
    "会場別名": 3,
    "イベント別名": 4,
    "曲名": 5,
}


def notion_request(method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{NOTION_API_BASE}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {NOTION_TOKEN}")
    req.add_header("Notion-Version", NOTION_VERSION)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())


def query_all_pages(db_id):
    rows = []
    cursor = None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        data = notion_request("POST", f"/databases/{db_id}/query", payload)
        rows.extend(data.get("results", []))
        if not data.get("has_more"):
            return rows
        cursor = data.get("next_cursor")


def plain_text(prop):
    if not prop:
        return ""
    prop_type = prop.get("type")
    if prop_type == "title":
        return "".join(part.get("plain_text", "") for part in prop.get("title", [])).strip()
    if prop_type == "rich_text":
        return "".join(part.get("plain_text", "") for part in prop.get("rich_text", [])).strip()
    if prop_type == "select":
        return (prop.get("select") or {}).get("name", "")
    if prop_type == "url":
        return prop.get("url") or ""
    if prop_type == "number":
        value = prop.get("number")
        return "" if value is None else str(value)
    if prop_type == "date":
        return (prop.get("date") or {}).get("start", "")
    if prop_type == "checkbox":
        return "true" if prop.get("checkbox") else "false"
    return ""


def multi_select(prop):
    if not prop or prop.get("type") != "multi_select":
        return []
    return [item.get("name", "") for item in prop.get("multi_select", []) if item.get("name")]


def number_value(prop):
    if not prop or prop.get("type") != "number":
        return 0
    return prop.get("number") or 0


def first_existing_text(props, names):
    for name in names:
        value = plain_text(props.get(name, {}))
        if value:
            return value
    return ""


def public_tags(kind, roles):
    tags = []
    if kind:
        tags.append(KIND_LABELS.get(kind, kind))
    for role in roles:
        if role and role not in tags and role != "除外語":
            tags.append(role)
    return tags


def should_include(props):
    state = plain_text(props.get("状態", {})) or "候補"
    kind = plain_text(props.get("種別", {}))
    confidence = plain_text(props.get("確度", {}))
    roles = set(multi_select(props.get("シグナル役割", {})))
    if state not in PUBLIC_STATES:
        return False
    if kind in EXCLUDED_KINDS:
        return False
    if confidence in EXCLUDED_CONFIDENCES:
        return False
    if "除外語" in roles:
        return False
    return True


def row_to_public_item(row):
    props = row.get("properties", {})
    term = plain_text(props.get("使用語", {}))
    kind = plain_text(props.get("種別", {}))
    roles = multi_select(props.get("シグナル役割", {}))
    description = first_existing_text(props, ("公開説明", "説明", "解釈", "正規語/表示名")) or term
    reading = first_existing_text(props, ("読み", "よみ", "フリガナ", "ふりがな"))
    confidence = plain_text(props.get("確度", {}))
    state = plain_text(props.get("状態", {})) or "候補"

    return {
        "term": term,
        "reading": reading,
        "description": description,
        "tags": public_tags(kind, roles),
        "category": kind,
        "category_label": KIND_LABELS.get(kind, kind or "その他"),
        "roles": roles,
        "status": state,
        "confidence": confidence,
        "source_count": number_value(props.get("証拠数", {})),
    }


def build_public_glossary():
    items = []
    skipped = 0
    for row in query_all_pages(DB_ID):
        props = row.get("properties", {})
        term = plain_text(props.get("使用語", {}))
        if not term:
            skipped += 1
            continue
        if not should_include(props):
            skipped += 1
            continue
        items.append(row_to_public_item(row))

    items.sort(key=lambda item: (
        KIND_ORDER.get(item["category"], 99),
        item["reading"] or item["term"],
        item["term"],
    ))
    return {
        "generated_by": "export_public_glossary.py",
        "glossary_v2_db_id": DB_ID,
        "count": len(items),
        "skipped_count": skipped,
        "items": items,
    }


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output JSON path")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    out_path = Path(args.out).expanduser()
    try:
        payload = build_public_glossary()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"用語集公開JSON export失敗 (HTTP {exc.code}): {body}") from exc

    write_json(out_path, payload)
    print(
        f"用語集公開JSON export完了: {payload['count']} 件 "
        f"(skipped={payload['skipped_count']}) -> {out_path}"
    )


if __name__ == "__main__":
    main()
