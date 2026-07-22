"""Append YouTube 2025 backfill progress to Notion."""

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
REPORT = Path("data/youtube_2025_backfill_report.json")
APPLY_SUMMARY = Path("data/rdb_apply_plan_summary.json")
SAFE_APPLY_RESULT = Path("data/youtube_2025_safe_existing_event_apply_result.json")


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


def note_children(target_label):
    report = load_json(REPORT, {})
    apply_summary = load_json(APPLY_SUMMARY, {})
    safe_apply = load_json(SAFE_APPLY_RESULT, {})
    status_counts = {row["review_status"]: row["count"] for row in report.get("review_status_counts") or []}
    event_counts = apply_summary.get("event_plan_counts") or {}
    safe_video_count = sum(row.get("video_count") or 0 for row in safe_apply.get("updates") or [])
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return [
        heading("YouTube 2025総浚い 進捗"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。追記先: {target_label}。"
            "active YouTubeチャンネルの2025年動画をYouTube Data APIで取得し、RDBへ反映。"
        ),
        bullet(f"RDB内2025動画数: {report.get('total_2025_videos_in_rdb')}。対象チャンネル: {len(report.get('channel_counts') or [])}。"),
        bullet("チャンネル別: 和太鼓お祭りチャンネル 2283、Urban Walk 789、Tokyo Hz 431、Tokyo Lonely Walker 132、祭のきせき 125、shu channel 116、Exploring Japan with Zen 62。"),
        bullet(f"レビュー状態: already_reflected {status_counts.get('already_reflected', 0)}、matched_existing_event {status_counts.get('matched_existing_event', 0)}、needs_official_confirmation {status_counts.get('needs_official_confirmation', 0)}、review_video_evidence {status_counts.get('review_video_evidence', 0)}、out_of_scope {status_counts.get('out_of_scope', 0)}。"),
        bullet(f"曲マスタ未登録: 証拠 {status_counts.get('song_not_in_master', 0)}、曲名集約 {apply_summary.get('song_review_candidates')}候補。"),
        bullet(f"Notion反映済み: 安全条件を満たした既存イベント {safe_apply.get('applied_count', 0)}件 / 動画 {safe_video_count}件をイベント詳細欄[youtube_evidence]へ追記。"),
        bullet(f"Notion反映計画: 2025総浚い由来の残り {event_counts.get('review_batch_2025_backfill', 0)}件は review_batch_2025_backfill として隔離。直接applyしない。"),
        bullet(f"通常ready: {event_counts.get('ready', 0)}件、既に要約反映済み: {event_counts.get('no_action_summary_present', 0)}件。"),
        bullet("日付不一致の誤紐付けを避けるため、検出日付があるYouTube動画はNotionイベント期間と一致する場合だけ既存イベント一致にするよう修正済み。"),
        bullet("成果物: data/youtube_2025_backfill_report.md、data/rdb_event_apply_plan.md、data/rdb_song_review_source.md。"),
        bullet("次: 575件の既存イベント一致をイベント単位で小分けにし、公式確認候補194件と曲候補743件は別レビューに回す。"),
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
    print("NotionへYouTube 2025総浚い進捗を追記しました")


if __name__ == "__main__":
    main()
