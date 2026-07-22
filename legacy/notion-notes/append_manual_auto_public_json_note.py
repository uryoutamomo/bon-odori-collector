"""Append the public JSON / Master RDB one-off decision to the current work page."""

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone

from notion_support.notion_config import load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")
CURRENT_WORK_PAGE_ID = "37f8be04-e762-815c-9f62-d76866ca9e83"


def rich_text(text):
    return [{"type": "text", "text": {"content": str(text or "")[:2000]}}]


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


def heading(text):
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": rich_text(text)},
    }


def paragraph(text):
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": rich_text(text)},
    }


def bullet(text):
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": rich_text(text)},
    }


def note_blocks():
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return [
        heading("手動/自動の使い分け: public JSON / Master RDB apply"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "Master RDB / public JSON one-off apply scripts を深掘りし、自動維持と手動維持を分けた。"
        ),
        bullet(
            "apply_public_date_predictions.py / apply_public_historical_references.py / "
            "apply_public_season_hints.py は公開JSON生成後処理として自動継続。"
            "Notion・S3・CloudFront・Master RDBは書かない。"
        ),
        bullet(
            "apply_public_event_name_cleanup.py と apply_public_official_source_urls.py は手動one-off。"
            "公開JSON/JSを書く場合は APPLY PUBLIC JSON ONE-OFF の確認文字列を必須化した。"
        ),
        bullet(
            "apply_ph2_shinagawa_second_venue_review.py と派生テーブル再生成系 build_* は "
            "APPLY MASTER RDB ONE-OFF を必須化。既存RDB one-offの個別確認文字列も維持。"
        ),
        bullet(
            "apply_youtube_year_backfill_review_decisions.py はローカル証拠JSONを書き換えるため、"
            "APPLY LOCAL EVIDENCE ONE-OFF を必須化した。"
        ),
        bullet(
            "記録先: docs/master-rdb-public-json-one-off-operations.md、"
            "docs/manual-auto-operations-inventory.md。"
        ),
        bullet(
            "次の深掘り候補: remaining report/export/build scripts。"
            "export_* / build_* / compare_* / audit_* のread-only、再生成、正本変更の境界を確認する。"
        ),
    ]


def append_note():
    return notion_request(
        "PATCH",
        f"/blocks/{CURRENT_WORK_PAGE_ID}/children",
        {"children": note_blocks()},
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    if args.dry_run:
        print(f"Would append public JSON/RDB note to current work page: {CURRENT_WORK_PAGE_ID}")
        return
    append_note()
    print("Notionの今やっていることページへpublic JSON/RDBの整理を追記しました")


if __name__ == "__main__":
    main()
