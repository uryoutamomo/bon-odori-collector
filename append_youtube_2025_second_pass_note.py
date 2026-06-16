"""Append YouTube 2025 second-pass RDB classification progress to Notion."""

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from notion_config import load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")
YOUTUBE_TASK_PAGE_ID = "37f8be04-e762-814c-a63f-dff18fe6cf35"
CURRENT_WORK_PAGE_ID = "37f8be04-e762-815c-9f62-d76866ca9e83"
SECOND_PASS_REPORT = Path("data/youtube_2025_second_pass_event_groups.json")


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


def count_by_category(report):
    return {
        row["category"]: {
            "events": row.get("event_count", 0),
            "videos": row.get("video_count", 0),
        }
        for row in report.get("category_counts") or []
    }


def category_line(label, category, counts):
    count = counts.get(category, {"events": 0, "videos": 0})
    return f"{label}: {count['events']}イベント / {count['videos']}動画。"


def note_children(target_label):
    report = load_json(SECOND_PASS_REPORT, {})
    counts = count_by_category(report)
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    date_backfill_videos = (
        counts.get("date_backfill_candidate_single_date", {}).get("videos", 0)
        + counts.get("date_backfill_candidate_multi_date", {}).get("videos", 0)
    )
    hold_videos = (
        counts.get("prior_year_video_uploaded_in_2025", {}).get("videos", 0)
        + counts.get("year_mismatch_or_recurring_event_review", {}).get("videos", 0)
    )
    return [
        heading("YouTube 2025 二次分類"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。追記先: {target_label}。"
            "RDB上の review_batch_2025_backfill をイベント単位で分類し、すぐ反映せずに日付補正候補と保留候補へ分けた。"
        ),
        bullet(f"対象: {report.get('remaining_review_batch_rows', 0)}動画 / {report.get('event_group_count', 0)}イベントグループ。"),
        bullet(category_line("単日の日付補正候補", "date_backfill_candidate_single_date", counts)),
        bullet(category_line("複数日の補正/混入確認候補", "date_backfill_candidate_multi_date", counts)),
        bullet(f"日付補正候補の合計: {date_backfill_videos}動画。公式/既存ソース確認後にNotion日付補正とYouTube証拠反映へ進める。"),
        bullet(category_line("2025公開だがタイトル上は過去年実績", "prior_year_video_uploaded_in_2025", counts)),
        bullet(category_line("2026ページ等との年ズレ/継続イベント要確認", "year_mismatch_or_recurring_event_review", counts)),
        bullet(f"保留候補の合計: {hold_videos}動画。2025イベント証拠として自動反映しない。"),
        bullet("注意点: 品川区民まつり西大井、京橋盆踊り、根津神社はタイトル年が2024のみなので、2025公開でも2025イベント証拠から外す。"),
        bullet("成果物: data/youtube_2025_second_pass_event_groups.json / .md。"),
        bullet("次: 日付補正候補383動画を、イベント単位で公式確認→Notion日付補正→安全applyの順に処理する。"),
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
    print("NotionへYouTube 2025二次分類を追記しました")


if __name__ == "__main__":
    main()
