#!/usr/bin/env python3
"""Seed the song master DB from song candidates and glossary v2 song terms."""

import argparse
import json
import os
import re
import urllib.request
from pathlib import Path

from notion_config import (
    GLOSSARY_V2_DATABASE_ID,
    SONG_MASTER_DATABASE_ID,
    load_local_env,
)


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
TOKEN = os.environ.get("NOTION_API_TOKEN")
GLOSSARY_DB_ID = os.environ.get("GLOSSARY_V2_DB_ID") or GLOSSARY_V2_DATABASE_ID
SONG_DB_ID = os.environ.get("SONG_MASTER_DB_ID") or SONG_MASTER_DATABASE_ID
SOURCE = Path("data/event_song_candidates.json")
OUT = Path("data/song_master_initial_registration.json")
DRY_RUN_OUT = Path("data/song_master_initial_registration_dry_run.json")


def notion_request(method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{NOTION_API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Notion-Version", NOTION_VERSION)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())


def rich_text(value, limit=1900):
    value = str(value or "")[:limit]
    return [{"type": "text", "text": {"content": value}}] if value else []


def plain_text(prop):
    if not prop:
        return ""
    prop_type = prop.get("type")
    if prop_type in ("title", "rich_text"):
        return "".join(item.get("plain_text", "") for item in prop.get(prop_type, [])).strip()
    return ""


def prop_select(prop):
    return (prop.get("select") or {}).get("name", "") if prop else ""


def norm_song(value):
    return re.sub(r"\s+", "", str(value or "")).casefold()


def classify_song(name):
    if name in {"盆踊り", "輪踊り", "民謡"}:
        return "ジャンル総称"
    if re.search(r"(東京音頭|炭坑節|ダンシングヒーロー|八木節|相馬盆唄|ドンパン節)", name):
        return "定番曲"
    if re.search(r"(区|市|町|村|郷|江戸|東京|音頭|小唄|甚句|節|おどり|踊り)$", name):
        return "ご当地曲"
    return "未分類"


def query_database(db_id, payload=None):
    rows = []
    cursor = None
    while True:
        page = dict(payload or {})
        page.setdefault("page_size", 100)
        if cursor:
            page["start_cursor"] = cursor
        data = notion_request("POST", f"/databases/{db_id}/query", page)
        rows.extend(data.get("results", []))
        if not data.get("has_more"):
            return rows
        cursor = data.get("next_cursor")


def load_song_candidates():
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    by_song = {}
    for row in data.get("candidates", []):
        name = row.get("song_name") or ""
        if not name:
            continue
        item = by_song.setdefault(
            norm_song(name),
            {
                "song_name": name,
                "candidate_count": 0,
                "event_names": set(),
                "venues": set(),
                "urls": [],
                "evidence_count": 0,
                "sources": {"event_song_candidates"},
            },
        )
        item["candidate_count"] += 1
        if row.get("event_name"):
            item["event_names"].add(row["event_name"])
        if row.get("venue"):
            item["venues"].add(row["venue"])
        item["evidence_count"] += int(row.get("evidence_count") or 0)
        for evidence in row.get("evidence") or []:
            url = evidence.get("url")
            if url and url not in item["urls"]:
                item["urls"].append(url)
    return by_song


def glossary_song_rows():
    rows = query_database(
        GLOSSARY_DB_ID,
        {
            "filter": {"property": "種別", "select": {"equals": "曲名"}},
            "page_size": 100,
        },
    )
    out = []
    for row in rows:
        props = row.get("properties", {})
        term = plain_text(props.get("使用語", {}))
        song = plain_text(props.get("曲名", {})) or plain_text(props.get("解釈", {})) or term
        if not song:
            continue
        out.append(
            {
                "page_id": row["id"],
                "term": term,
                "song_name": song,
                "state": prop_select(props.get("状態", {})),
                "confidence": prop_select(props.get("確度", {})),
            }
        )
    return out


def merge_sources():
    songs = load_song_candidates()
    for row in glossary_song_rows():
        key = norm_song(row["song_name"])
        item = songs.setdefault(
            key,
            {
                "song_name": row["song_name"],
                "candidate_count": 0,
                "event_names": set(),
                "venues": set(),
                "urls": [],
                "evidence_count": 0,
                "sources": set(),
            },
        )
        item["sources"].add("glossary_v2")
        item.setdefault("glossary_pages", []).append(row)
    for item in songs.values():
        item["event_names"] = sorted(item["event_names"])
        item["venues"] = sorted(item["venues"])
        item["sources"] = sorted(item["sources"])
        item["glossary_pages"] = item.get("glossary_pages", [])
    return songs


def existing_song_pages():
    pages = query_database(SONG_DB_ID)
    out = {}
    for page in pages:
        name = plain_text(page.get("properties", {}).get("曲名", {}))
        if name:
            out[norm_song(name)] = page
    return out


def song_props(row):
    memo_parts = [
        "初期登録: event_song_candidates.json と用語集v2曲名行から作成。",
        f"出典: {', '.join(row['sources'])}",
        f"候補行数: {row['candidate_count']}",
    ]
    if row["event_names"]:
        memo_parts.append("関連イベント候補: " + " / ".join(row["event_names"][:10]))
    if row["venues"]:
        memo_parts.append("関連会場候補: " + " / ".join(row["venues"][:10]))
    props = {
        "曲名": {"title": rich_text(row["song_name"][:200])},
        "分類": {"select": {"name": classify_song(row["song_name"])}},
        "状態": {"select": {"name": "候補"}},
        "証拠数": {"number": row["evidence_count"]},
        "メモ": {"rich_text": rich_text("\n".join(memo_parts))},
    }
    if row["urls"]:
        props["出典・音源URL"] = {"url": row["urls"][0]}
    return props


def connect_glossary_pages(row, song_page_id, dry_run=False):
    connected = []
    for glossary in row.get("glossary_pages", []):
        if dry_run:
            connected.append({"term": glossary["term"], "page_id": glossary["page_id"], "dry_run": True})
            continue
        notion_request(
            "PATCH",
            f"/pages/{glossary['page_id']}",
            {"properties": {"ヒント先曲": {"relation": [{"id": song_page_id}]}}},
        )
        connected.append({"term": glossary["term"], "page_id": glossary["page_id"]})
    return connected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    if not SONG_DB_ID:
        raise SystemExit("SONG_MASTER_DB_ID is not set")

    songs = merge_sources()
    existing = existing_song_pages()
    created = []
    skipped = []
    connected = []
    for key, row in sorted(songs.items(), key=lambda item: item[1]["song_name"]):
        page = existing.get(key)
        if page:
            skipped.append({"song_name": row["song_name"], "reason": "existing", "page_id": page["id"]})
            song_page_id = page["id"]
        elif args.dry_run:
            created.append({"song_name": row["song_name"], "dry_run": True, "classification": classify_song(row["song_name"])})
            song_page_id = "dry-run"
        else:
            page = notion_request(
                "POST",
                "/pages",
                {
                    "parent": {"database_id": SONG_DB_ID},
                    "properties": song_props(row),
                },
            )
            created.append({"song_name": row["song_name"], "page_id": page["id"], "classification": classify_song(row["song_name"])})
            song_page_id = page["id"]
        connected.extend(connect_glossary_pages(row, song_page_id, args.dry_run))

    result = {
        "dry_run": args.dry_run,
        "source": str(SOURCE),
        "song_master_db_id": SONG_DB_ID,
        "merged_song_count": len(songs),
        "created_count": len(created),
        "skipped_count": len(skipped),
        "connected_glossary_count": len(connected),
        "created": created,
        "skipped": skipped,
        "connected_glossary": connected,
    }
    out = DRY_RUN_OUT if args.dry_run else OUT
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "done: merged={merged_song_count} created={created_count} "
        "skipped={skipped_count} glossary_relations={connected_glossary_count} "
        "dry_run={dry_run}".format(**result)
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
