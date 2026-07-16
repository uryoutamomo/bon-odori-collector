"""Append the event time research policy to the current work page in Notion."""

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone

from notion_config import load_local_env


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
        heading("盆踊りイベント開始時間の公式確認方針"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "公開イベントで時間が未確認のものが多いため、近い開催日から公式URLを探して開始時間を補完する。"
        ),
        bullet(
            "優先順: 今日以降の開催日が近い順。まず 2026-06-27 以降の確定日あり・時間未確認イベントを対象にする。"
        ),
        bullet(
            "根拠の優先度: 2026年の公式/主催/自治体/会場ページ、公式PDF・チラシ、公式SNS。"
            "過去年実績や非公式まとめは今年の開始時間として確定扱いにしない。"
        ),
        bullet(
            "短期反映: 既存サイトが detail から時刻を抽出できるため、確認済み時刻は detail と根拠URLに入れて公開表示を改善する。"
        ),
        bullet(
            "中期改善: master RDB に time_text / time_status / time_source_url 相当を正式フィールドとして追加し、"
            "公開JSONへ明示的に流す設計に寄せる。"
        ),
        bullet(
            "最初の調査キュー: 奥浅草盆踊り、ビールと浴衣de盆踊りin上野、新橋こいち祭、築地本願寺納涼盆踊り大会、"
            "すみだ錦糸町河内音頭大盆踊り、中野駅前大盆踊り大会、みなと区民まつり盆踊り。"
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
        print(f"Would append event time research note to current work page: {CURRENT_WORK_PAGE_ID}")
        return
    append_note()
    print("Notionの今やっていることページへイベント開始時間確認方針を追記しました")


if __name__ == "__main__":
    main()
