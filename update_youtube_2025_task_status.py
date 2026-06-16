"""Mark completed YouTube 2025 backfill task items in Notion."""

import argparse
import json
import os
import urllib.request

from notion_config import load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")

TASK_UPDATES = {
    "3808be04-e762-8172-859b-d6d3b44243be": (
        True,
        "完了: active 7チャンネルの2025年動画をYouTube Data APIで取得し、RDB内2025動画3938件まで反映。",
    ),
    "3808be04-e762-8131-bbeb-f65a683a2722": (
        True,
        "完了: 動画タイトル・説明欄から event_date、event_name_hint、venue_hint、songs、official_urls を抽出し、youtube_evidence.sqlite / bon_odori.sqlite に集約。",
    ),
    "3808be04-e762-8137-a5fe-e326a394bf19": (
        True,
        "完了: 既存イベントDBと照合し、2025総浚い由来575件を review_batch_2025_backfill としてdry-run化。直接applyはしない。",
    ),
    "3808be04-e762-8123-adee-ecca23afe6e5": (
        False,
        "次: 未一致候補・公式確認候補194件は、公式URLまたは複数信頼ソースで確認できるまで本登録しない。全国展開候補や周辺祭りは hold として別保持する。",
    ),
    "3808be04-e762-8185-b5fb-ec02921b06d2": (
        False,
        "後続: activeチャンネル由来のレビューを処理した後に、検索APIで区名・会場名つきクエリを広げる。",
    ),
    "3808be04-e762-8142-aae6-e11d7dffb400": (
        True,
        "完了: active 7チャンネルの2025年動画をYouTube Data APIで取得し、RDB内2025動画3938件まで反映。",
    ),
    "3808be04-e762-8190-aec6-ddd7aa3c5790": (
        True,
        "完了: 動画タイトル・説明欄から event_date、event_name_hint、venue_hint、songs、official_urls を抽出し、youtube_evidence.sqlite / bon_odori.sqlite に集約。",
    ),
    "3808be04-e762-8125-b663-d1357c2c7e57": (
        True,
        "完了: 既存イベントDB・公開イベントJSONと照合し、安全条件を満たす8イベント/116動画はNotionへ反映。残り437動画は二次分類済み。",
    ),
    "3808be04-e762-8165-94a6-f9be38409801": (
        False,
        "進行中: 未一致候補・公式確認候補194件と二次分類の保留54動画は、公式URLまたは複数信頼ソースで確認できるまで本登録しない。",
    ),
    "3808be04-e762-817d-88a4-c2fa15d35c09": (
        False,
        "後続: activeチャンネル由来の日付補正候補383動画を処理した後に、検索APIで区名・会場名つきクエリを広げる。",
    ),
}


def rich_text(text):
    return [{"type": "text", "text": {"content": str(text or "")[:2000]}}]


def notion_request(method, path, payload):
    data = json.dumps(payload).encode("utf-8")
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    if args.dry_run:
        for block_id, (checked, text) in TASK_UPDATES.items():
            print(f"Would update {block_id}: checked={checked} {text}")
        return
    for block_id, (checked, text) in TASK_UPDATES.items():
        notion_request("PATCH", f"/blocks/{block_id}", {"to_do": {"rich_text": rich_text(text), "checked": checked}})
    print("YouTube 2025バックフィルのNotionタスク状態を更新しました")


if __name__ == "__main__":
    main()
