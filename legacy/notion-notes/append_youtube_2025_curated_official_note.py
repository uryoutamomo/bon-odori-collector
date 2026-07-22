"""Append curated YouTube 2025 official candidate apply progress to Notion."""

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from notion_support.notion_config import load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")
YOUTUBE_TASK_PAGE_ID = "37f8be04-e762-814c-a63f-dff18fe6cf35"
CURRENT_WORK_PAGE_ID = "37f8be04-e762-815c-9f62-d76866ca9e83"
CURATED_APPLY = Path("data/youtube_2025_curated_official_apply_result.json")
VALIDATION = Path("data/youtube_2025_official_candidate_validation.json")
APPLY_SUMMARY = Path("data/rdb_apply_plan_summary.json")
RDB_SUMMARY = Path("data/bon_odori_rdb_summary.json")


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


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


def paragraph(text):
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(text)}}


def bullet(text):
    return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": rich_text(text)}}


def curated_rows(result):
    return [row for row in result.get("rows") or []]


def note_children(target_label):
    result = load_json(CURATED_APPLY, {})
    validation = load_json(VALIDATION, {})
    summary = load_json(APPLY_SUMMARY, {})
    rdb = load_json(RDB_SUMMARY, {})
    rows = curated_rows(result)
    names = "、".join(f"{row.get('event_name')}（{row.get('video_count')}動画）" for row in rows)
    changed_rows = [row for row in rows if row.get("changed") or row.get("event_created") or row.get("venue_created")]
    changed_names = "、".join(row.get("event_name") or "" for row in changed_rows) or "なし"
    table_counts = rdb.get("table_counts") or {}
    event_counts = summary.get("event_plan_counts") or {}
    counts = validation.get("status_counts") or {}
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return [
        heading("YouTube 2025 curated公式候補反映"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。追記先: {target_label}。"
            "公式URL候補のうち、既存表記差または新規登録が明確なものを個別判断で反映した。"
        ),
        bullet(f"反映済み: {len(rows)}件。対象: {names}。"),
        bullet(f"今回変更あり: {len(changed_rows)}件。対象: {changed_names}。"),
        bullet(
            "新規作成: "
            f"イベント {result.get('event_created_count', 0)}件、会場 {result.get('venue_created_count', 0)}件。"
        ),
        bullet("神田明神、渋谷、築地本願寺、アースデイ東京/イマジン盆踊り部は、こと（Claude Code）のWeb裏どり結果をもとにregister_ready扱いで反映した。"),
        bullet(
            "元の検証レポート上の未処理区分: "
            f"new_event_review {counts.get('new_event_review', 0)}、"
            f"source_date_hold {counts.get('source_date_hold', 0)}、"
            f"source_fetch_hold {counts.get('source_fetch_hold', 0)}。これらの一部はcurated反映済み。"
        ),
        bullet(
            "RDB再生成後: "
            f"events {table_counts.get('events', 0)}、venues {table_counts.get('venues', 0)}、"
            f"event_evidence_links {table_counts.get('event_evidence_links', 0)}、"
            f"review_batch_2025_backfill {event_counts.get('review_batch_2025_backfill', 0)}。"
        ),
        bullet("成果物: data/youtube_2025_curated_official_apply_result.json / .md。"),
    ]


def append_note(page_id, target_label):
    return notion_request("PATCH", f"/blocks/{page_id}/children", {"children": note_children(target_label)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    if args.dry_run:
        for child in note_children("dry-run"):
            print(json.dumps(child, ensure_ascii=False))
        return
    append_note(YOUTUBE_TASK_PAGE_ID, "YouTube課題ページ")
    append_note(CURRENT_WORK_PAGE_ID, "今やっていること")
    print("NotionへYouTube 2025 curated公式候補反映の進捗を追記しました")


if __name__ == "__main__":
    main()
