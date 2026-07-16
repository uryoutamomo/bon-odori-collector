"""Append next YouTube task priorities to the YouTube Notion task page."""

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone

from notion_config import load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")

YOUTUBE_TASK_PAGE_ID = "37f8be04-e762-814c-a63f-dff18fe6cf35"
CURRENT_WORK_PLAN_BLOCK_ID = "37f8be04-e762-814a-9463-dabca26c86e0"
YOUTUBE_TASK_PAGE_URL = "https://app.notion.com/p/YouTube-37f8be04e762814ca63fdff18fe6cf35"


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
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": rich_text(text)},
    }


def update_bullet(block_id, text):
    return notion_request("PATCH", f"/blocks/{block_id}", {"bulleted_list_item": {"rich_text": rich_text(text)}})


def append_next_tasks_note():
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    children = [
        heading("YouTube次課題整理"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "active 7チャンネル収集後の主要処理を一巡。"
            "YouTube関連作業は引き続きこのページを入口にする。"
        ),
        bullet(
            "優先1: append_existing_event 17件のうち、山王音頭と民踊大会は既存イベントへ反映済み。"
            "4グループを1つの[youtube_evidence]に集約し、動画16件・曲目候補13件を追記した。"
        ),
        bullet(
            "優先1 dry-run結果: data/youtube_active_existing_event_update_dry_run.json / .md を追加。"
            "再実行でready=0、review=0、blocked=0、done=5を確認。"
            "山王音頭と民踊大会4件と国立旭通りジューンフェスタ盆踊り1件は処理済み。"
        ),
        bullet(
            "優先1 apply結果: data/youtube_active_existing_event_update_apply_result.json / .md を追加。"
            "再dry-runで山王音頭と民踊大会はchanged=0となり、重複追記されないことを確認済み。"
        ),
        bullet(
            "国立旭通りblocked解消: 予定管理DBには既存ページがあったが、イベント本DB未登録だったため、"
            "data/youtube_blocked_new_event_apply_result.json / .md を追加し、会場1件・イベント1件を本DBへ登録。"
        ),
        bullet(
            "優先2: needs_official_confirmation 6件を処理。丸の内3件はMarunouchi.com公式確認済みとして、"
            "既存イベント「丸の内de盆踊り」へYouTube追加証拠を追記済み。"
        ),
        bullet(
            "優先2 hold: 渋谷盆踊り2025は公式URL候補の本文取得不可のため保留。"
            "渋谷・鹿児島おはら祭とPokémon GO Fest TOKYO 2026は、盆踊り本DB登録対象として要確認。"
            "結果は data/youtube_official_confirmation_apply_result.json / .md に保存。"
        ),
        bullet(
            "優先3: review_video_evidence 10件を処理。自由が丘2件・丸の内4件は既存イベントへ"
            "[youtube_evidence] YouTube shorts追加証拠として追記済み。再dry-runでchanged=0を確認。"
            "結果は data/youtube_review_video_evidence_apply_result.json / .md に保存。"
        ),
        bullet(
            "優先3 hold: 渋谷盆踊り2025の短尺動画4件は、公式確認が未解決のため保留。"
            "YouTube単独では本DB登録/既存イベント追記をしない。"
        ),
        bullet(
            "渋谷再確認: shibuyadogenzaka.com/?p=6827 はHTTP 200とRESTリンクを返すが、"
            "通常本文は空、REST本文はWordPress重大エラーHTMLのため公式確認ソースとして使わない。"
        ),
        bullet(
            "保留: out_of_scope 18件は data/youtube_nationwide_hold_candidates.json / .md に集約。"
            "横浜開港祭 BON ODORI 2026の1候補として保持し、東京23区公開DBには入れない。"
        ),
        bullet(
            "設計判断: docs/youtube-evidence-architecture.md を追加。短期はイベント詳細欄の[youtube_evidence]追記、"
            "中期はYouTube証拠DB/occurrence側への分離を推奨。"
        ),
        bullet(
            "参照: data/youtube_active_video_review.md、data/youtube_nationwide_hold_candidates.md、"
            "docs/youtube-evidence-architecture.md。"
        ),
        bullet(f"入口: {YOUTUBE_TASK_PAGE_URL}"),
    ]
    return notion_request("PATCH", f"/blocks/{YOUTUBE_TASK_PAGE_ID}/children", {"children": children})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    current_text = (
        "YouTube次課題: active 7チャンネル収集後の既存追記・公式確認・動画証拠・全国候補保持は一巡。"
        "渋谷公式確認と対象カテゴリ外候補は保留、次は必要時にYouTube証拠DB/occurrence分離へ進む。"
    )

    if args.dry_run:
        print(f"Would update current work block: {CURRENT_WORK_PLAN_BLOCK_ID} -> {current_text}")
        print(f"Would append next task note to: {YOUTUBE_TASK_PAGE_ID}")
        return

    update_bullet(CURRENT_WORK_PLAN_BLOCK_ID, current_text)
    append_next_tasks_note()
    print("NotionへYouTube次課題整理を追記しました")


if __name__ == "__main__":
    main()
