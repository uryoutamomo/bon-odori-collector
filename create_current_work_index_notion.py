"""Create a Notion index page for current and lightly paused work."""

import argparse
import json
import os
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from manual_apply_guards import NOTION_WORKLOG_MAINTENANCE_CONFIRMATION, require_confirmation
from notion_config import load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")
DEFAULT_PARENT_PAGE_ID = "3708be04-e762-811d-bbb7-c984b14fe452"
OUT = Path("data/notion_current_work_index.json")
YOUTUBE_TASK_LIST = Path("data/youtube_notion_task_list.json")


def rich_text(text, href=None):
    text_obj = {"content": str(text or "")[:2000]}
    if href:
        text_obj["link"] = {"url": href}
    return [{"type": "text", "text": text_obj}]


def paragraph(text, href=None):
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(text, href)}}


def heading(level, text):
    key = f"heading_{level}"
    return {"object": "block", "type": key, key: {"rich_text": rich_text(text)}}


def bullet(text, href=None):
    return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": rich_text(text, href)}}


def todo(text, checked=False):
    return {
        "object": "block",
        "type": "to_do",
        "to_do": {"rich_text": rich_text(text), "checked": checked},
    }


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


def plain_title(obj):
    props = obj.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            return "".join(part.get("plain_text", "") for part in prop.get("title", []))
    return "".join(part.get("plain_text", "") for part in obj.get("title") or [])


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".tmp-", suffix=".json", delete=False
    ) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        tmp_name = handle.name
    Path(tmp_name).replace(path)


def create_page(parent_page_id, title):
    return notion_request(
        "POST",
        "/pages",
        {
            "parent": {"page_id": parent_page_id},
            "properties": {"title": {"title": [{"type": "text", "text": {"content": title}}]}},
        },
    )


def append_blocks(page_id, blocks):
    for idx in range(0, len(blocks), 90):
        notion_request("PATCH", f"/blocks/{page_id}/children", {"children": blocks[idx:idx + 90]})


def page_blocks(youtube_task_url=""):
    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    blocks = [
        paragraph(
            "このページを、盆踊りプロジェクトで最初に見る作業入口にする。"
            "今動いているもの、少しだけ休止しているもの、次に判断が必要なものをここへ集める。"
            f"更新: {generated_at} / 署名: おと（Codex）"
        ),
        heading(2, "運用ルール"),
        bullet("新しい大きめの作業ページや課題リストは、まずこのページから辿れるようにする。"),
        bullet("Notionページを作るときは親ページを明示し、曖昧な検索結果を親にしない。"),
        bullet("本DBを更新する前のレビュー候補、dry-run、調査中メモはここへリンクする。"),
        heading(2, "今動いているもの"),
        bullet("YouTubeデータ活用: チャンネルDB、2025年イベント発掘、曲目候補、YouTubeリンク/サムネイルの扱い。", youtube_task_url or None),
        bullet("YouTubeイベント更新プラン: 既存追記2件、新規候補2件、対象外1件、要調査1件を分類済み。ローカル: data/youtube_event_update_plan.md"),
        bullet("YouTubeチャンネル候補レビュー: Urban Walk、Tokyo Lonely Walker、Tokyo Hz、祭りが好き!、shu channel などを候補として保持。"),
        bullet("曲 occurrence / event_songs 接続: YouTube setlist evidence を song_occurrences に接続済み。"),
        heading(2, "少しだけ休止中"),
        bullet("RDB集約の設計検討: YouTube段階2とレビュー導線が落ち着いた後に再開。"),
        bullet("新規イベント候補の本登録: 渋谷盆踊り2025、東京丸の内盆踊り2025は公式確認待ち。"),
        bullet("奥浅草系YouTube動画の照合: 既存の奥浅草盆踊りへ寄せられるか、日付と会場確認待ち。"),
        bullet("全国展開候補: はかた夏まつりは現状の東京圏公開DBには入れず、将来候補として保持。"),
        heading(2, "次に見る順番"),
        todo("YouTube課題リストを確認し、既存イベント追記2件のdry-runを作る。"),
        todo("渋谷盆踊り2025、東京丸の内盆踊り2025の公式情報を確認する。"),
        todo("YouTubeリンクとサムネイルをNotion/公開UIのどこに置くか決める。"),
        todo("RDB集約設計を、イベント・会場・曲・証拠の正本化方針として再開する。"),
        heading(2, "参照リンク"),
    ]
    if youtube_task_url:
        blocks.append(bullet("今後の課題リスト: YouTubeデータ活用", youtube_task_url))
    blocks.extend([
        bullet("ローカル成果物: data/youtube_channels.json"),
        bullet("ローカル成果物: data/youtube_event_song_candidates.md"),
        bullet("ローカル成果物: data/youtube_event_update_plan.md"),
        bullet("ローカル記憶: /Users/ryotauchida/.agents/memory/bon-odori-youtube-notion-task-list.md"),
    ])
    return blocks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-page-id", default=DEFAULT_PARENT_PAGE_ID)
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    try:
        require_confirmation(
            True,
            args.confirm,
            NOTION_WORKLOG_MAINTENANCE_CONFIRMATION,
            "current work Notion index creation",
        )
    except ValueError as exc:
        parser.error(str(exc))
    parent = notion_request("GET", f"/pages/{args.parent_page_id}")
    parent_title = plain_title(parent)
    title = "今やっていること"
    youtube_task = load_json(YOUTUBE_TASK_LIST, {})
    page = create_page(args.parent_page_id, title)
    append_blocks(page["id"], page_blocks(youtube_task.get("url") or ""))
    output = {
        "generated_by": "create_current_work_index_notion.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "title": title,
        "page_id": page["id"],
        "url": page.get("url") or "",
        "parent_page_id": args.parent_page_id,
        "parent_title": parent_title,
        "youtube_task_list_url": youtube_task.get("url") or "",
    }
    atomic_write_json(args.out, output)
    print(f"Notionに今やっていることページを作成しました: {page.get('url') or page['id']}")


if __name__ == "__main__":
    main()
