"""Append the fixed-date and GA4 deployment wrap-up report to Notion."""

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone

from notion_config import load_local_env


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
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": rich_text(text)},
    }


def paragraph(text):
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": rich_text(text)},
    }


def bullet(text):
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": rich_text(text)},
    }


def note_blocks():
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return [
        heading("固定日DB対応・GA4デプロイ 作業レポート"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "花園神社の固定日見落とし対策から、公開サイトのGA4デプロイまで一区切り。"
        ),
        bullet("固定日DB対応: NotionイベントDBに 固定日開始月/開始日/終了月/終了日/固定日根拠URL を追加。花園神社 盆踊り=毎年8/1〜8/2、山王音頭と民踊大会=毎年6/13〜6/15 を記録済み。"),
        bullet("予測ロジック: 公開エクスポートがNotion固定日カラムを読み、履歴予測では同曜日スライドより固定日ルールを優先するよう変更。花園神社の2026予測は 2026-08-01〜2026-08-02。"),
        bullet("YouTube照合: 日付なしの弱い会場一致だけでは既存イベントへ紐付けないよう修正。花園神社の酉の市動画を盆踊り扱いしない。"),
        bullet("Web解析: analytics.js をGA4対応へ切替。測定IDは G-NGJFQPFSPH。bonsuke.jp / www.bonsuke.jp / CloudFront URL のみ送信し、localhostでは送信しない。"),
        bullet("プライバシー: 問い合わせ本文、メールアドレス、検索語そのものは解析イベントとして送信しない。terms.html と docs/web-analytics.md もGA4表記へ更新。"),
        bullet("公開デプロイ: bon-odori-site commit cfa7cfb（固定日修正+解析導入）と 191bcc0（GA4切替）を push。GitHub Actions Deploy static site は成功。最新 run: https://github.com/uryoutamomo/bon-odori-site/actions/runs/27866997064"),
        bullet("検証: node --check app.js / analytics.js、scripts/build_public_snapshot.py、snapshot hygiene check、CloudFront上の analytics.js とHTML参照を確認済み。"),
        bullet("本番確認メモ: この端末では一時的に bonsuke.jp のDNS解決が失敗したが、CloudFront配信元では反映確認済み。"),
        bullet("残件: bon-odori-collector側の固定日DB対応コード・データ差分は未整理。次の区切りで関連差分だけcommit対象として整理する。"),
    ]


def append_report():
    return notion_request(
        "PATCH",
        f"/blocks/{CURRENT_WORK_PAGE_ID}/children",
        {"children": note_blocks()},
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    if args.dry_run:
        for block in note_blocks():
            print(json.dumps(block, ensure_ascii=False))
        return
    append_report()
    print("Notionの現在地ページへ固定日DB対応・GA4デプロイ作業レポートを追記しました")


if __name__ == "__main__":
    main()
