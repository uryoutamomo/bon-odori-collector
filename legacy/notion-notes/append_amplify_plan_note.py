"""Append the AWS Amplify hosting plan note to the shared current-location page."""

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
CURRENT_LOCATION = Path("data/notion_current_location.json")


def rich_text(text):
    return [{"type": "text", "text": {"content": str(text or "")[:2000]}}]


def notion_request(method, path, payload=None):
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        NOTION_API + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def heading(level, text):
    key = f"heading_{level}"
    return {"object": "block", "type": key, key: {"rich_text": rich_text(text)}}


def paragraph(text):
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(text)}}


def bullet(text):
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": rich_text(text)},
    }


def todo(text, checked=False):
    return {
        "object": "block",
        "type": "to_do",
        "to_do": {"rich_text": rich_text(text), "checked": checked},
    }


def note_blocks():
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return [
        heading(2, "AWS Amplify公開計画（計画段階）"),
        paragraph(f"更新: {now} / 署名: おと（Codex）。まだ実装・設定は開始しない。方針決定の記録。"),
        bullet("公開先は AWS 学習を兼ねて AWS Amplify Hosting を第一候補にする。Cloudflare Pages ではなく、AWS運用を学ぶことを優先する。"),
        bullet("bon-odori-site は GitHub repo `uryoutamomo/bon-odori-site` に push 済み。Amplify はこの repo を接続する想定。"),
        bullet("Amplify の公開対象は repo 全体ではなく、`python3 scripts/build_public_snapshot.py dist` で作る公開スナップショットだけにする。preview/ や作業用ファイルを配信しない。"),
        bullet("現時点の公開スナップショットは約2.0MB。概算コストは通常 $0〜$2/月、盆踊りシーズンに伸びても $3〜$15/月程度を初期目安にする。5万PVで約$15/月は、毎回2MB近く転送される上振れ寄りの見積もり。"),
        bullet("コスト対策として、AWS Budgets で $5 / $15 / $30 の通知を先に入れる。公開設定より先に予算アラートを作る。"),
        bullet("将来の赤字対策候補: 支援リンク、地域店舗/協賛枠、広告ではなく地図の価値に沿ったスポンサー表示を検討する。"),
        heading(3, "次にやること"),
        todo("Amplify Hosting のアプリ作成手順を確認し、GitHub repo 接続と build spec を決める。"),
        todo("AWS Budgets の月額アラートを先に設定する。"),
        todo("Amplify build spec は `python3 scripts/build_public_snapshot.py dist`、artifact baseDirectory は `dist` とする。"),
        todo("独自ドメインを使うか、まず amplifyapp.com の仮URLで公開するか決める。"),
    ]


def append_blocks(page_id, blocks):
    for idx in range(0, len(blocks), 90):
        notion_request("PATCH", f"/blocks/{page_id}/children", {"children": blocks[idx:idx + 90]})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--current-location-json", default=str(CURRENT_LOCATION))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    current = json.loads(Path(args.current_location_json).read_text(encoding="utf-8"))
    page_id = current["page_id"]
    if args.dry_run:
        print(f"Would append AWS Amplify plan note to current-location page: {page_id}")
        return
    append_blocks(page_id, note_blocks())
    print(f"Notion現在地にAWS Amplify公開計画を追記しました: {current['url']}")


if __name__ == "__main__":
    main()
