"""Append the manual infrastructure workflow decision to the current work page."""

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
        heading("手動/自動の使い分け: 手動インフラworkflow"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "domain / WAF / contact-form / Master RDB S3 bootstrap の扱いを深掘りし、"
            "通常自動化しない方針に確定した。"
        ),
        bullet(
            "site側 configure-custom-domain / configure-contact-form / configure-waf は手動workflow_dispatchのみ。"
            "dry-runは apply=false のまま軽く実行できる。"
        ),
        bullet(
            "実変更は apply=true に加えて確認文字列を必須化した。"
            "custom domain は APPLY CUSTOM DOMAIN <domain>、contact form は APPLY CONTACT FORM contact@bonsuke.jp、"
            "WAF は APPLY WAF ERA76BJB7WLEN。"
        ),
        bullet(
            "collector側 bootstrap_master_rdb_s3.yml は初期artifact publish用として手動維持。"
            "実行には BOOTSTRAP MASTER RDB S3 の確認文字列が必要。"
        ),
        bullet(
            "verify_master_rdb_s3.yml / verify-aws-queue.yml はread-only検証として手動維持。"
            "通常監査は各定期workflow内のStep Summaryで足りるため、単独の定期化はしない。"
        ),
        bullet(
            "記録先: docs/manual-infra-workflows.md、site側 docs/manual-infra-workflows.md、"
            "docs/manual-auto-operations-inventory.md、docs/master-rdb-s3-artifact.md。"
        ),
        bullet(
            "次の深掘り候補: X candidate / social graph workflows。"
            "X API quota、レビュー成果物、Notion同期の境界を確認する。"
        ),
    ]


def append_note():
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
        print(f"Would append manual infra note to current work page: {CURRENT_WORK_PAGE_ID}")
        return
    append_note()
    print("Notionの今やっていることページへ手動インフラworkflowの整理を追記しました")


if __name__ == "__main__":
    main()
