#!/usr/bin/env python3
"""Clean non-song and aggregate titles from the Notion song master."""

import argparse
import json
import os
from pathlib import Path

from manual_apply_guards import LEGACY_NOTION_REPAIR_CONFIRMATION, require_confirmation
from notion_config import SONG_MASTER_DATABASE_ID, load_local_env
from register_song_master_initial import classify_song, rich_text
from triage_weekly_song_candidates import norm, notion_request, title_index


load_local_env()

TOKEN = os.environ.get("NOTION_API_TOKEN")
SONG_DB_ID = os.environ.get("SONG_MASTER_DB_ID") or SONG_MASTER_DATABASE_ID
OUT = Path("data/song_master_title_cleanup_result.json")

INVALID_TITLES = {
    "横浜開港祭BON": "イベント/企画名の途中抽出で、曲名ではない。",
    "隅田公園そよ風ひろばに踊り": "文章片の抽出で、曲名ではない。",
    "飛鳥山公園輪踊り": "イベント/動画タイトル由来で、曲名ではない。",
    "山王音頭と千代田踊り": "複数曲を結合した名前。実曲は山王音頭と千代田踊りに分割する。",
    "鯵ヶ沢甚句と村崎野音頭": "複数曲を結合した名前。実曲は鯵ヶ沢甚句と村崎野音頭に分割する。",
}

GENRE_TITLES = {
    "郡上おどり": "郡上おどりは曲単体ではなく、踊り体系/行事体系として扱う。",
    "白鳥おどり": "白鳥おどりは曲単体ではなく、踊り体系/行事体系として扱う。",
}

ALIAS_TITLES = {
    "郡上踊り": "表記ゆれ。代表は郡上おどり。",
    "白鳥踊り": "表記ゆれ。代表は白鳥おどり。",
    "鰺ヶ沢甚句": "表記ゆれ。代表は鯵ヶ沢甚句。",
}

ENSURE_SONGS = {
    "千代田踊り": {
        "classification": "ご当地曲",
        "memo": (
            "曲マスタ整理で追加。"
            "山王音頭と千代田踊りの結合候補から分割した実曲。"
            "出典: https://www.edo-chiyoda.jp/chiyoda-bonodori.html"
        ),
        "url": "https://www.edo-chiyoda.jp/chiyoda-bonodori.html",
    },
}


def plain_text(prop):
    if not prop:
        return ""
    prop_type = prop.get("type")
    if prop_type in ("title", "rich_text"):
        return "".join(part.get("plain_text", "") for part in prop.get(prop_type, [])).strip()
    return ""


def append_memo(page, addition):
    old_memo = plain_text(page.get("properties", {}).get("メモ"))
    if addition in old_memo:
        return old_memo
    return (old_memo + "\n\n" + addition).strip()


def patch_page(page_id, props, dry_run=False):
    if dry_run:
        return
    notion_request("PATCH", f"/pages/{page_id}", {"properties": props})


def mark_invalid(name, reason, song_index, dry_run=False):
    item = song_index.get(norm(name))
    if not item:
        return {"song_name": name, "action": "missing"}
    memo = append_memo(
        item["page"],
        "曲マスタ整理: 無効化。\n"
        f"理由: {reason}",
    )
    props = {
        "状態": {"select": {"name": "無効"}},
        "メモ": {"rich_text": rich_text(memo)},
    }
    patch_page(item["id"], props, dry_run)
    return {"song_name": name, "page_id": item["id"], "action": "invalid", "dry_run": dry_run}


def mark_genre(name, reason, song_index, dry_run=False):
    item = song_index.get(norm(name))
    if not item:
        return {"song_name": name, "action": "missing"}
    memo = append_memo(
        item["page"],
        "曲マスタ整理: 曲単体ではなく体系名として分類。\n"
        f"理由: {reason}",
    )
    props = {
        "分類": {"select": {"name": "ジャンル総称"}},
        "状態": {"select": {"name": "有効"}},
        "メモ": {"rich_text": rich_text(memo)},
    }
    patch_page(item["id"], props, dry_run)
    return {"song_name": name, "page_id": item["id"], "action": "genre", "dry_run": dry_run}


def mark_alias(name, reason, song_index, dry_run=False):
    item = song_index.get(norm(name))
    if not item:
        return {"song_name": name, "action": "missing"}
    memo = append_memo(
        item["page"],
        "曲マスタ整理: 表記ゆれとして公開曲リストから除外。\n"
        f"理由: {reason}",
    )
    props = {
        "状態": {"select": {"name": "無効"}},
        "メモ": {"rich_text": rich_text(memo)},
    }
    patch_page(item["id"], props, dry_run)
    return {"song_name": name, "page_id": item["id"], "action": "alias_invalid", "dry_run": dry_run}


def ensure_song(name, spec, song_index, dry_run=False):
    existing = song_index.get(norm(name))
    props = {
        "曲名": {"title": rich_text(name[:200])},
        "分類": {"select": {"name": spec.get("classification") or classify_song(name)}},
        "状態": {"select": {"name": "有効"}},
        "証拠数": {"number": 1},
        "メモ": {"rich_text": rich_text(spec.get("memo", "曲マスタ整理で追加。"))},
    }
    if spec.get("url"):
        props["出典・音源URL"] = {"url": spec["url"]}
    if existing:
        props.pop("曲名", None)
        patch_page(existing["id"], props, dry_run)
        return {"song_name": name, "page_id": existing["id"], "action": "update_existing", "dry_run": dry_run}
    if dry_run:
        return {"song_name": name, "action": "create", "dry_run": True}
    page = notion_request(
        "POST",
        "/pages",
        {"parent": {"database_id": SONG_DB_ID}, "properties": props},
    )
    song_index[norm(name)] = {"id": page["id"], "name": name, "page": page}
    return {"song_name": name, "page_id": page["id"], "action": "create"}


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
            "legacy song master title cleanup Notion repair",
        )
    except ValueError as exc:
        parser.error(str(exc))

    if not TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    songs = title_index(SONG_DB_ID)
    result = {
        "dry_run": args.dry_run,
        "invalid": [mark_invalid(name, reason, songs, args.dry_run) for name, reason in INVALID_TITLES.items()],
        "genres": [mark_genre(name, reason, songs, args.dry_run) for name, reason in GENRE_TITLES.items()],
        "aliases": [mark_alias(name, reason, songs, args.dry_run) for name, reason in ALIAS_TITLES.items()],
        "ensured": [ensure_song(name, spec, songs, args.dry_run) for name, spec in ENSURE_SONGS.items()],
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
