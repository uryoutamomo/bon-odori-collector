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
            "active 7チャンネル収集と動画レビュー表作成後の次アクション整理。"
            "YouTube関連作業は引き続きこのページを入口にする。"
        ),
        bullet(
            "優先1: append_existing_event 17件のうち、山王音頭と民踊大会は既存イベントへ反映済み。"
            "4グループを1つの[youtube_evidence]に集約し、動画16件・曲目候補13件を追記した。"
        ),
        bullet(
            "優先1 dry-run結果: data/youtube_active_existing_event_update_dry_run.json / .md を追加。"
            "5グループに集約され、山王音頭と民踊大会4件はapply済み。"
            "国立旭通りジューンフェスタ盆踊り1件はNotionイベントページ未発見でblocked。"
        ),
        bullet(
            "優先1 apply結果: data/youtube_active_existing_event_update_apply_result.json / .md を追加。"
            "再dry-runで山王音頭と民踊大会はchanged=0となり、重複追記されないことを確認済み。"
        ),
        bullet(
            "優先2: needs_official_confirmation 6件を確認する。丸の内は公式URLありで既存/登録済み扱いへ寄せやすい。"
            "渋谷は公式ページの本文取得問題が残るため、YouTube単独登録はしない。"
        ),
        bullet(
            "優先3: review_video_evidence 10件は、自由が丘・丸の内・渋谷の短尺動画中心。"
            "曲目/動画証拠として残すか、既存イベント証拠へ寄せるかを確認する。"
        ),
        bullet(
            "保留: out_of_scope 18件は横浜など現行公開DB範囲外。全国展開候補として保持し、東京23区公開DBには入れない。"
        ),
        bullet(
            "設計判断: Notion本DBでYouTube証拠をどこに置くかを決める。短期はイベント詳細欄の[youtube_evidence]追記、"
            "中期は証拠DB/occurrence側への分離が候補。"
        ),
        bullet("参照: data/youtube_active_video_review.md と data/youtube_active_video_review.json。"),
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
        "YouTube次課題: 山王音頭と民踊大会はYouTube証拠反映済み。次は国立旭通りblocked解消、"
        "needs_official_confirmation 6件、review_video_evidence 10件を順に処理する。"
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
