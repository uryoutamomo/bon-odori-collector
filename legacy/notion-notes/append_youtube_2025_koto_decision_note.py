"""Append Koto-assisted YouTube 2025 decision progress to Notion."""

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
KOTO_APPLY = Path("data/youtube_2025_koto_ready_apply_result.json")
QUEUE = Path("data/youtube_2025_manual_confirmation_queue.json")
DECISIONS = Path("data/youtube_2025_manual_confirmation_decisions.json")


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


def count_actions(decisions):
    counts = {}
    for row in decisions.get("rows") or []:
        action = row.get("action") or "unknown"
        counts[action] = counts.get(action, 0) + 1
    return counts


def note_children(target_label):
    apply_result = load_json(KOTO_APPLY, {})
    queue = load_json(QUEUE, {})
    decisions = load_json(DECISIONS, {})
    rows = apply_result.get("rows") or []
    created_names = "、".join(row.get("event_name") or "" for row in rows if row.get("event_created")) or "なし"
    counts = count_actions(decisions)
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return [
        heading("YouTube 2025 こと分担裏取り反映"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。追記先: {target_label}。"
            "こと（Claude Code）へWeb目視・検索系の裏取りを振り、おと側でDB照合、重複確認、反映可否の検算を行った。"
        ),
        bullet(
            "ことの返答: register_ready 12件、hold 3件。"
            "おと側ではregister_readyをそのまま全登録せず、既存反映済み・重複・フェス内企画・動画由来のみの候補を再分類した。"
        ),
        bullet(
            "新規反映: "
            f"イベント {apply_result.get('event_created_count', 0)}件、会場 {apply_result.get('venue_created_count', 0)}件。"
            f"対象: {created_names}。"
        ),
        bullet(
            "既存/保留/除外: 神田明神、歌舞伎町BON ODORI、祐天寺、下北沢、奥浅草、すみだ錦糸町河内音頭などは"
            "既存反映済みとして重複登録を避けた。肉フェス、下町ハイボール、TOKYOわっしょい、歌舞伎町まつり10月は保留または分割扱い。"
        ),
        bullet(
            "手動確認キュー: "
            f"{queue.get('item_count', 0)}項目 / {queue.get('video_count', 0)}動画。"
            f"スキップ記録は {queue.get('skipped_count', 0)}項目 / {queue.get('skipped_video_count', 0)}動画。"
        ),
        bullet(
            "decision内訳: "
            f"skip_registered {counts.get('skip_registered', 0)}、"
            f"exclude_out_of_scope {counts.get('exclude_out_of_scope', 0)}、"
            f"hold系 {sum(value for key, value in counts.items() if key.startswith('hold_'))}。"
        ),
        bullet(
            "検証: export_public_events.py / export_public_venues.py 再生成済み、event_audit.py実行済み、"
            "pytest tests/test_export_youtube_2025_manual_confirmation_queue.py tests/test_apply_youtube_2025_official_candidate_existing_updates.py は3件通過。"
        ),
        bullet(
            "成果物: apply_youtube_2025_koto_ready_events.py、apply_youtube_2025_koto_decisions.py、"
            "data/youtube_2025_koto_ready_apply_result.json / .md、"
            "data/youtube_2025_manual_confirmation_decisions.json、data/youtube_2025_manual_confirmation_queue.json / .md。"
        ),
        bullet("コミット: 387aa47 Apply Koto YouTube 2025 decisions。"),
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
    print("NotionへYouTube 2025こと分担裏取り反映を追記しました")


if __name__ == "__main__":
    main()
