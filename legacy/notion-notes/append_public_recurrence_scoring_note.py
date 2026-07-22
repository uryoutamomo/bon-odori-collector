"""Append public recurrence scoring progress to the current Notion work page."""

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
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": rich_text(text)}}


def subheading(text):
    return {"object": "block", "type": "heading_3", "heading_3": {"rich_text": rich_text(text)}}


def paragraph(text):
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(text)}}


def bullet(text):
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": rich_text(text)},
    }


def note_blocks():
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return [
        heading("公開準備・再開催見込みスコア進捗"),
        paragraph(f"更新: {now} / 署名: おと（Codex）。本日の終了メモ。"),
        subheading("到達点"),
        bullet("bon-odori-site は既存履歴に内部情報が残るため、既存repoをpublic化せず、クリーンスナップショットから新規public repoを作る方針。"),
        bullet("クリーンスナップショットは /Users/ryotauchida/bon-odori-site-public-snapshot に作成済み。commit: fad39d8 Initial public snapshot。remote/push/Pages公開は未実行。"),
        bullet("bon-odori-collector では再開催見込みプレビューを追加。commit: 9ea8dca Add public recurrence scoring preview / 8b19001 Use edition numbers in recurrence scoring。"),
        bullet("出力: score_event_recurrence.py、data/event_recurrence_candidates.json、data/event_recurrence_candidates.md、data/public/events_public_with_recurrence.json。"),
        subheading("公開カテゴリ方針"),
        bullet("全185件を出す。ただし2025年実績は『今年は終了』ではなく、事実として『昨年開催』系で見せる。"),
        bullet("public_category は upcoming / recurring_last_year / date_unknown / ended を想定。UI側で文言を組み立てる。"),
        bullet("開催回数表記（例: 第70回、6回目）は強い継続性シグナルとして edition_number に抽出し、recurrence_reasons に edition_number:N を残す。"),
        bullet("文言は『例年開催』『今年も開催見込み』の断定を避け、例: 『第70回・昨年開催: 2025-07-25〜2025-07-26。今年の日程は未確認です。』とする。"),
        subheading("現在の分類件数"),
        bullet("2026確認済み/upcoming_confirmed: 12件"),
        bullet("昨年開催・継続性 高/expected_high: 17件"),
        bullet("昨年開催・継続性 中/expected_medium: 73件"),
        bullet("昨年開催・継続性 低/expected_low: 3件"),
        bullet("日程未確認/date_unknown: 61件"),
        bullet("2026終了/ended_2026: 19件"),
        subheading("検証"),
        bullet("python3 -m py_compile score_event_recurrence.py tests/test_score_event_recurrence.py: OK"),
        bullet("python3 -m unittest tests.test_score_event_recurrence: OK（7 tests）"),
        bullet("python3 score_event_recurrence.py: OK"),
        subheading("次回再開ポイント"),
        bullet("こと（Claude Code）は app.js 側で public_category / edition_number / recurrence_score / recurrence_reasons を受け、表示文言を実装する。"),
        bullet("おとは、表示側の受け口確認後に public snapshot の生成元JSONへ events_public_with_recurrence.json を統合する。"),
        bullet("未コミットの song_occurrences.py、tests/test_song_occurrences.py、data/koto_2026_event_classification.json は今回のおとの変更では触っていない。"),
    ]


def append_note():
    return notion_request("PATCH", f"/blocks/{CURRENT_WORK_PAGE_ID}/children", {"children": note_blocks()})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    if args.dry_run:
        print(f"Would append public recurrence scoring note to current work page: {CURRENT_WORK_PAGE_ID}")
        return

    append_note()
    print("Notionへ公開準備・再開催見込みスコア進捗を追記しました")


if __name__ == "__main__":
    main()
