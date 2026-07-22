#!/usr/bin/env python3
"""Apply final corrections from the first weekly song harvest review."""

import argparse
import json
import os
from pathlib import Path

from operation_safety.manual_apply_guards import LEGACY_NOTION_REPAIR_CONFIRMATION, require_confirmation
from notion_config import (
    GLOSSARY_V2_DATABASE_ID,
    SONG_MASTER_DATABASE_ID,
    load_local_env,
)
from song_processing.song_master_registration import rich_text
from song_processing.weekly_song_triage import norm, notion_request, title_index


load_local_env()

TOKEN = os.environ.get("NOTION_API_TOKEN")
SONG_DB_ID = os.environ.get("SONG_MASTER_DB_ID") or SONG_MASTER_DATABASE_ID
GLOSSARY_DB_ID = os.environ.get("GLOSSARY_V2_DB_ID") or GLOSSARY_V2_DATABASE_ID
OUT = Path("data/weekly_song_final_corrections_result.json")

REMOVE_SONG_UPDATES = [
    {
        "song_name": "夜の踊り子",
        "page_id": "37c8be04-e762-81b9-9424-ee8eb21a0918",
        "reason": "内田さん最終判定: `夜の踊り` は曲候補として不採用。日次X収穫由来の更新を取り消し。",
    },
    {
        "song_name": "馬鹿おどり",
        "page_id": "37c8be04-e762-81c7-b8a4-d56cc9e46590",
        "reason": "内田さん最終判定: 曲ではない。日次X収穫由来の更新を取り消し。",
    },
]

SOURCE_MEMOS = {
    "山王音頭": (
        "日次X収穫11件の最終判定でWeb裏取り済み。"
        "山王祭限定のご当地ソングとして扱う。"
        "出典: https://www.tenkamatsuri.jp/minyo/"
    ),
    "千代田踊り": (
        "日次X収穫11件の最終判定でWeb裏取り済み。"
        "千代田区民踊連盟の民踊として扱う。"
        "出典: https://www.edo-chiyoda.jp/chiyoda-bonodori.html"
    ),
    "岡崎音頭": (
        "日次X収穫11件の最終判定でWeb裏取り済み。"
        "岡崎周辺の曲候補として曲マスタに残す。"
    ),
    "五万石おどり": (
        "日次X収穫11件の最終判定でWeb裏取り済み。"
        "正式名は「岡崎五万石」の可能性が高いため別名メモとして保持。"
        "出典: https://nichimin.or.jp/commentary/岡崎五万石/"
    ),
}

BONJOVI_TERM = {
    "term": "盆ジョビ",
    "interpretation": "中野駅前大盆踊り大会の名物企画（盆ジョヴィ）。曲はBon Jovi『Livin' on a Prayer』。",
    "aliases": "盆ジョビ / 盆ジョヴィ",
    "source_url": "https://amass.jp/176830/",
}


def plain_text(prop):
    if not prop:
        return ""
    prop_type = prop.get("type")
    if prop_type in ("title", "rich_text"):
        return "".join(item.get("plain_text", "") for item in prop.get(prop_type, [])).strip()
    return ""


def existing_glossary_pages(term):
    data = notion_request(
        "POST",
        f"/databases/{GLOSSARY_DB_ID}/query",
        {
            "filter": {"property": "使用語", "title": {"equals": term}},
            "page_size": 10,
        },
    )
    return data.get("results", [])


def update_song_to_rejected(item, dry_run=False):
    memo = (
        "日次X収穫11件の最終判定により、曲マスタ有効更新を取り消し。\n"
        f"{item['reason']}\n"
        "運用メモ: ページは監査用に残し、状態を無効・証拠数0・出典URL空にする。"
    )
    props = {
        "状態": {"select": {"name": "無効"}},
        "証拠数": {"number": 0},
        "メモ": {"rich_text": rich_text(memo)},
        "出典・音源URL": {"url": None},
    }
    if dry_run:
        return {"song_name": item["song_name"], "page_id": item["page_id"], "action": "reject", "dry_run": True}
    notion_request("PATCH", f"/pages/{item['page_id']}", {"properties": props})
    return {"song_name": item["song_name"], "page_id": item["page_id"], "action": "reject"}


def append_song_source_memo(song_name, song_index, dry_run=False):
    song = song_index.get(norm(song_name))
    if not song:
        return {"song_name": song_name, "action": "missing"}
    page = song["page"]
    old_memo = plain_text(page.get("properties", {}).get("メモ"))
    addition = SOURCE_MEMOS[song_name]
    memo = old_memo if addition in old_memo else (old_memo + "\n\n" + addition).strip()
    props = {"メモ": {"rich_text": rich_text(memo)}}
    if dry_run:
        return {"song_name": song_name, "page_id": song["id"], "action": "source_memo", "dry_run": True}
    notion_request("PATCH", f"/pages/{song['id']}", {"properties": props})
    return {"song_name": song_name, "page_id": song["id"], "action": "source_memo"}


def bonjovi_props():
    memo = (
        "日次X収穫11件レビュー最終判定から登録。\n"
        "曲マスタではなく用語集v2候補として扱う。\n"
        f"表記ゆれ: {BONJOVI_TERM['aliases']}\n"
        f"証拠URL: {BONJOVI_TERM['source_url']}"
    )
    return {
        "使用語": {"title": rich_text(BONJOVI_TERM["term"])},
        "解釈": {"rich_text": rich_text(BONJOVI_TERM["interpretation"])},
        "種別": {"select": {"name": "界隈語"}},
        "シグナル役割": {"multi_select": []},
        "確度": {"select": {"name": "推察"}},
        "状態": {"select": {"name": "候補"}},
        "自動適用可": {"checkbox": False},
        "証拠数": {"number": 1},
        "出典URL": {"url": BONJOVI_TERM["source_url"]},
        "メモ": {"rich_text": rich_text(memo)},
    }


def register_bonjovi(dry_run=False):
    existing = existing_glossary_pages(BONJOVI_TERM["term"])
    if dry_run:
        return {
            "term": BONJOVI_TERM["term"],
            "action": "update" if existing else "create",
            "dry_run": True,
        }
    if existing:
        page_id = existing[0]["id"]
        props = bonjovi_props()
        props.pop("使用語", None)
        notion_request("PATCH", f"/pages/{page_id}", {"properties": props})
        return {"term": BONJOVI_TERM["term"], "page_id": page_id, "action": "update"}
    page = notion_request(
        "POST",
        "/pages",
        {"parent": {"database_id": GLOSSARY_DB_ID}, "properties": bonjovi_props()},
    )
    return {"term": BONJOVI_TERM["term"], "page_id": page["id"], "action": "create"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        require_confirmation(
            not args.dry_run,
            args.confirm,
            LEGACY_NOTION_REPAIR_CONFIRMATION,
            "legacy weekly song final correction Notion repair",
        )
    except ValueError as exc:
        parser.error(str(exc))

    if not TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    songs = title_index(SONG_DB_ID)
    result = {
        "dry_run": args.dry_run,
        "rejected_songs": [
            update_song_to_rejected(item, args.dry_run)
            for item in REMOVE_SONG_UPDATES
        ],
        "source_memos": [
            append_song_source_memo(song_name, songs, args.dry_run)
            for song_name in SOURCE_MEMOS
        ],
        "glossary": register_bonjovi(args.dry_run),
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
