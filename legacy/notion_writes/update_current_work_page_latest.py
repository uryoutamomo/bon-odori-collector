"""Update the Notion current-work entry page with the latest YouTube status."""

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
YOUTUBE_TASK_URL = "https://app.notion.com/p/YouTube-37f8be04e762814ca63fdff18fe6cf35"


def rich_text(text, href=None):
    text_obj = {"content": str(text or "")[:2000]}
    if href:
        text_obj["link"] = {"url": href}
    return [{"type": "text", "text": text_obj}]


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


def update_paragraph(block_id, text):
    return notion_request("PATCH", f"/blocks/{block_id}", {"paragraph": {"rich_text": rich_text(text)}})


def update_bullet(block_id, text, href=None):
    return notion_request(
        "PATCH",
        f"/blocks/{block_id}",
        {"bulleted_list_item": {"rich_text": rich_text(text, href)}},
    )


def update_todo(block_id, text, checked):
    return notion_request(
        "PATCH",
        f"/blocks/{block_id}",
        {"to_do": {"rich_text": rich_text(text), "checked": checked}},
    )


def heading(text):
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": rich_text(text)}}


def paragraph(text):
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(text)}}


def bullet(text, href=None):
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": rich_text(text, href)},
    }


def append_after_note():
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    children = [
        heading("更新メモ"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "YouTube課題リストの全チェック完了と、保留案件の掲載基準確定を反映。"
        ),
        bullet("YouTube課題リストは全チェック済み。未実装にした方が安全な項目は、代替方針を記載して完了扱い。", YOUTUBE_TASK_URL),
        bullet("渋谷盆踊り2025は公式本文取得不可のため本登録せず、未公式実績候補として保持。"),
        bullet("横浜開港祭 BON ODORIは全国展開候補として保持し、現行の東京23区公開DBには入れない。"),
        bullet("次に進めるなら、YouTube証拠DB/occurrence分離をRDB集約設計の入口にする。"),
    ]
    return notion_request("PATCH", f"/blocks/{CURRENT_WORK_PAGE_ID}/children", {"children": children})


def updates():
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return [
        (
            "paragraph",
            "37f8be04-e762-8168-a312-d1ab55db0096",
            "このページを、盆踊りプロジェクトで最初に見る作業入口にする。"
            "今動いているもの、少しだけ休止しているもの、次に判断が必要なものをここへ集める。"
            f"更新: {now} / 署名: おと（Codex）",
            None,
        ),
        (
            "bullet",
            "37f8be04-e762-81de-a817-fea98e430d33",
            "YouTubeデータ活用: 課題リストは全チェック完了。既存追記、公式確認、動画証拠、全国候補保持、公開UI方針まで一巡。",
            YOUTUBE_TASK_URL,
        ),
        (
            "bullet",
            "37f8be04-e762-814a-9463-dabca26c86e0",
            "YouTube次課題: YouTube単体は一旦停止可。次に進めるなら、YouTube証拠DB/occurrence分離をRDB集約設計の入口にする。",
            None,
        ),
        (
            "bullet",
            "37f8be04-e762-8195-9286-e5295f7254d8",
            "YouTubeチャンネル運用: activeチャンネルRSSを手動実行で扱う。検索拡張はquota消費を避け、必要時のみ検討。",
            None,
        ),
        (
            "bullet",
            "37f8be04-e762-81df-ab98-f0ae97142a12",
            "曲 occurrence / event_songs 接続: YouTube setlist evidence は song_occurrences に接続済み。深い正規化は証拠DB分離時に扱う。",
            None,
        ),
        (
            "bullet",
            "37f8be04-e762-81c4-a50b-e08d0c2d31fa",
            "RDB集約の設計検討: 次の再開候補。イベント・会場・曲・YouTube証拠/occurrenceの正本化として進める。",
            None,
        ),
        (
            "bullet",
            "37f8be04-e762-819c-863b-e464e9591824",
            "新規イベント候補の本登録: 丸の内de盆踊りは登録済み。渋谷盆踊り2025は公式本文取得不可のため本登録せず、未公式実績候補として保持。",
            None,
        ),
        (
            "bullet",
            "37f8be04-e762-81ef-bae7-ed8486ed08cc",
            "奥浅草系YouTube動画の照合: 2025-06-28の過去年実績として既存の奥浅草盆踊りへ追記済み。",
            None,
        ),
        (
            "bullet",
            "37f8be04-e762-81a9-ad0f-e912542e7eab",
            "全国展開候補: はかた夏まつり方針を継承。横浜開港祭 BON ODORI 18動画を候補保持し、現行の東京23区公開DBには入れない。",
            None,
        ),
        (
            "todo",
            "37f8be04-e762-81a7-a81d-ebebcf6fa1f2",
            "完了: YouTube課題リストを確認し、既存イベント追記のdry-run/適用/再dry-runまで完了。",
            True,
        ),
        (
            "todo",
            "37f8be04-e762-8141-a010-d8d888f19252",
            "完了/代替: 丸の内は公式確認済みで反映。渋谷盆踊り2025は公式本文取得不可のため、本登録せず未公式実績候補として保持。",
            True,
        ),
        (
            "todo",
            "37f8be04-e762-81d8-a510-d068a8f4c476",
            "完了: YouTubeリンクとサムネイルは公開UIでは youtube_evidence を使い、動画リンクを出典、サムネイルを詳細内任意表示とする。",
            True,
        ),
        (
            "todo",
            "37f8be04-e762-8144-8921-e2114703a4b4",
            "次に再開: RDB集約設計を、イベント・会場・曲・YouTube証拠/occurrenceの正本化方針として進める。",
            False,
        ),
        (
            "bullet",
            "37f8be04-e762-8133-8b1b-cf63f4aea250",
            "今後の課題リスト: YouTubeデータ活用（全チェック完了）",
            YOUTUBE_TASK_URL,
        ),
        (
            "bullet",
            "37f8be04-e762-81ce-bb7b-cd50d94f9944",
            "ローカル成果物: data/youtube_next_session_handoff.md",
            None,
        ),
        (
            "bullet",
            "37f8be04-e762-810b-9700-c339b8483341",
            "ローカル成果物: docs/youtube-evidence-architecture.md",
            None,
        ),
        (
            "bullet",
            "37f8be04-e762-81be-9268-c8ccee5c4dc8",
            "ローカル成果物: data/youtube_nationwide_hold_candidates.md / data/youtube_user_confirmation_queue.md",
            None,
        ),
        (
            "bullet",
            "37f8be04-e762-8116-a043-ce6fbc05964d",
            "ローカル運用メモ: docs/youtube-channel-db.md / docs/youtube-public-ui.md",
            None,
        ),
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    items = updates()
    if args.dry_run:
        for kind, block_id, text, href_or_checked in items:
            print(f"Would update {kind} {block_id}: {text} ({href_or_checked})")
        print(f"Would append update note to: {CURRENT_WORK_PAGE_ID}")
        return

    for kind, block_id, text, href_or_checked in items:
        if kind == "paragraph":
            update_paragraph(block_id, text)
        elif kind == "bullet":
            update_bullet(block_id, text, href_or_checked)
        elif kind == "todo":
            update_todo(block_id, text, bool(href_or_checked))
        else:
            raise ValueError(kind)
    append_after_note()
    print(f"updated current work page: {CURRENT_WORK_PAGE_ID}")


if __name__ == "__main__":
    main()
