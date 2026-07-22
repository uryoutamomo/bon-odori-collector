"""Append the X candidate workflow decision to the current work page."""

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone

from notion_support.notion_config import load_local_env


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
        heading("手動/自動の使い分け: X候補workflow"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "X candidate / social graph workflows を深掘りし、定期自動化せず手動維持に確定した。"
        ),
        bullet(
            "discover_x_social_graph.yml はX follow graph探索でAPI quotaを使うため、"
            "workflow_dispatchのみ。実行には DISCOVER X SOCIAL GRAPH が必要。"
        ),
        bullet(
            "review_x_candidate_posts.yml の通常レビューは候補アカウントの最近投稿をX APIで見るため、"
            "実行には REVIEW X CANDIDATES が必要。"
        ),
        bullet(
            "review_x_candidate_posts.yml の sync_only=true はX API課金なしだが、"
            "承認済みpromoteをlegacy Notion Xメンバーリストへ登録するため、"
            "SYNC APPROVED X MEMBERS が必要。"
        ),
        bullet(
            "Notion登録は、x_candidate_post_review.json のpromote行に内田さん承認"
            "（user_approved=true等）がある場合だけ。自動昇格はしない。"
        ),
        bullet(
            "記録先: docs/x-candidate-workflows-operations.md、"
            "docs/x-rss-collection-operations.md、docs/manual-auto-operations-inventory.md。"
        ),
        bullet(
            "次の深掘り候補: Notion queue migration。legacy one-offとして残っている"
            "migrate_notion_queue_to_dynamodb.yml のdry-run/default/冪等性を確認する。"
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
        print(f"Would append X candidate workflow note to current work page: {CURRENT_WORK_PAGE_ID}")
        return
    append_note()
    print("Notionの今やっていることページへX候補workflowの整理を追記しました")


if __name__ == "__main__":
    main()
