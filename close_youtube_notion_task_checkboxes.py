"""Close the original YouTube Notion task checkboxes with final decisions."""

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone

from manual_apply_guards import NOTION_WORKLOG_MAINTENANCE_CONFIRMATION, require_confirmation
from notion_support.notion_config import load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")

YOUTUBE_TASK_PAGE_ID = "37f8be04-e762-814c-a63f-dff18fe6cf35"

TASK_UPDATES = {
    "37f8be04-e762-81dd-9c17-c47a597d79be": (
        "完了/代替: 新規候補は丸の内を公式確認済みで反映。渋谷盆踊り2025は公式本文取得不可のため、"
        "本登録せず未公式実績候補として別保持する。"
    ),
    "37f8be04-e762-814b-ba1d-d04e8e8fd9da": (
        "完了/代替: 対象外候補は東京23区公開DBへ入れず全国展開候補として保持。"
        "はかた夏まつり方針を継承し、現行active分の横浜開港祭 BON ODORI 18動画も保持済み。"
    ),
    "37f8be04-e762-8100-8479-c14448db3b15": (
        "完了: チャンネルDB候補をレビューし、採用/既存/保留へ分類済み。"
        "台帳は data/youtube_channel_registry.json、運用メモは docs/youtube-channel-db.md。"
    ),
    "37f8be04-e762-81c6-9082-fccf79888695": (
        "完了/代替: YouTube検索クエリ拡張は一旦しない。quota消費はactiveチャンネルRSS優先、"
        "重複はRSS URL・video_id・既存youtube_evidence URLで排除する方針に確定。"
    ),
    "37f8be04-e762-810a-97de-eed0a774bf56": (
        "完了/代替: 章タイトル型の曲目抽出は youtube_setlist_occurrence と既存apply結果で実用化済み。"
        "英語併記やアーティスト名の深い正規化は、将来のYouTube証拠DB分離時に扱う。"
    ),
    "37f8be04-e762-815f-9174-f6f518f3a205": (
        "完了/代替: 動画説明欄の会場名・Google Maps等は official_urls / venue_hint として保持し、"
        "本登録は公式確認または既存イベント一致がある場合に限定する。"
    ),
    "37f8be04-e762-811b-ac0d-e8466e96724d": (
        "完了: YouTube証拠の置き場所は短期をイベント詳細欄[youtube_evidence]、"
        "中期をYouTube証拠DB/occurrence分離とする方針に確定。docs/youtube-evidence-architecture.md に記録済み。"
    ),
    "37f8be04-e762-8113-9cc1-ddc73c6ec5d6": (
        "完了: 公開UIでは data/public/events_public.json の youtube_evidence を使い、"
        "動画リンクを出典として表示、サムネイルは詳細内で任意表示、曲目は動画由来の補助情報として扱う。"
    ),
    "37f8be04-e762-8195-91c4-f78fa456a690": (
        "完了: 採用済みYouTubeチャンネルは定期ジョブ追加ではなく手動実行で扱う方針に確定。"
        "docs/youtube-channel-db.md にRSS優先・重複排除・quota方針を記録済み。"
    ),
}


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


def update_todo(block_id, text):
    return notion_request(
        "PATCH",
        f"/blocks/{block_id}",
        {"to_do": {"rich_text": rich_text(text), "checked": True}},
    )


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


def append_close_note():
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    children = [
        heading("YouTube課題リスト完了整理"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "課題リストの未チェック項目を、完了または代替方針確定として全てチェック済みに整理。"
        ),
        bullet("新規イベントは、公式確認できた丸の内を反映し、渋谷は未公式実績候補として別保持。"),
        bullet("対象外・周辺イベントは、東京23区公開DBへ入れず、全国展開候補または曲目/現象メモとして保持。"),
        bullet("検索拡張はquota消費を避け、activeチャンネルRSSと既存動画照合を優先する方針に確定。"),
        bullet("YouTube証拠は短期をイベント詳細欄[youtube_evidence]、中期を証拠DB/occurrence分離とする。"),
        bullet("公開UIと手動実行運用は docs/youtube-public-ui.md / docs/youtube-channel-db.md / docs/youtube-evidence-architecture.md を正とする。"),
    ]
    return notion_request("PATCH", f"/blocks/{YOUTUBE_TASK_PAGE_ID}/children", {"children": children})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    if args.dry_run:
        for block_id, text in TASK_UPDATES.items():
            print(f"Would check {block_id}: {text}")
        print(f"Would append close note to: {YOUTUBE_TASK_PAGE_ID}")
        return
    try:
        require_confirmation(
            True,
            args.confirm,
            NOTION_WORKLOG_MAINTENANCE_CONFIRMATION,
            "YouTube Notion task checkbox close",
        )
    except ValueError as exc:
        parser.error(str(exc))

    for block_id, text in TASK_UPDATES.items():
        update_todo(block_id, text)
    append_close_note()
    print(f"checked {len(TASK_UPDATES)} YouTube task checkboxes and appended close note")


if __name__ == "__main__":
    main()
