"""Create a Notion task-list page for YouTube data handling."""

import json
import os
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from notion_config import load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")
NOTION_PAGE_ID = os.environ.get("NOTION_PAGE_ID", "")
FALLBACK_QUERY = "盆踊りデータ統一モデル"
OUT = Path("data/youtube_notion_task_list.json")


def rich_text(text):
    return [{"type": "text", "text": {"content": str(text or "")[:2000]}}]


def paragraph(text):
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(text)}}


def heading(level, text):
    key = f"heading_{level}"
    return {"object": "block", "type": key, key: {"rich_text": rich_text(text)}}


def bullet(text):
    return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": rich_text(text)}}


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


def search_page_id(query):
    data = notion_request(
        "POST",
        "/search",
        {"query": query, "filter": {"property": "object", "value": "page"}, "page_size": 10},
    )
    results = data.get("results") or []
    preferred = [
        item for item in results
        if "統一モデル" in plain_title(item) or "盆踊り" in plain_title(item)
    ]
    return (preferred or results or [{}])[0].get("id") or ""


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


def task_blocks():
    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return [
        paragraph(
            "YouTubeを、Xの盆踊ラーリスト相当の発見ソースとして扱うための課題リスト。"
            "過去イベント、曲目、会場、YouTubeリンク、サムネイルを安全にDBへ接続する。"
            f"作成: {generated_at} / 署名: おと（Codex）"
        ),
        heading(2, "基本方針"),
        bullet("YouTubeは強い実績証拠として扱う。ただし公式開催情報とは分け、動画単独で新規イベントを即登録しない。"),
        bullet("既存イベントに一致する場合は、過去実績・曲目証拠・動画URL・サムネイルを追記候補にする。"),
        bullet("新規イベント候補は、正式イベント名、会場名、住所、開催日を公式ページまたは複数証拠で確認してから登録する。"),
        bullet("チャンネル運営者への送客になるため、公開UIでは出典としてYouTubeリンクを残す。利用者には曲の予習導線として使う。"),
        bullet("サムネイルはイベント証拠、曲証拠、または動画出典表示の文脈で使う。会場写真として誤用しない。"),
        heading(2, "現在の成果物"),
        bullet("data/youtube_channels.json: 既存YouTube 199本をチャンネル単位に集約。"),
        bullet("data/youtube_channel_candidates.json / .md: YouTube検索からのチャンネル候補。"),
        bullet("data/youtube_event_candidates.json: YouTube検索からのイベント候補。"),
        bullet("data/youtube_event_song_candidates.json / .md: イベント候補と曲候補のレビュー用データ。"),
        bullet("data/youtube_event_update_plan.json / .md: 既存追記、新規候補、対象外、要調査の分類プラン。"),
        heading(2, "課題リスト"),
        todo("既存イベント追記候補2件をdry-run化する: 自由が丘納涼盆踊り大会、歌舞伎町BON ODORI。"),
        todo("既存イベント追記では、2025年実績としてYouTube動画URL、曲目、サムネイルURL、チャンネル名を保存する。"),
        todo("新規候補2件を公式確認する: 渋谷盆踊り2025、東京丸の内盆踊り2025。正式イベント名・会場名・住所・公開対象範囲を確認する。"),
        todo("要調査1件を確認する: Tokyo Hzの奥浅草系動画。既存の奥浅草盆踊りに寄せられるか、日付と会場を確認する。"),
        todo("対象外候補1件を保持する: はかた夏まつり。現状の東京圏公開DBには入れず、将来の全国展開候補として残す。"),
        todo("チャンネルDB候補をレビューする: Urban Walk、Tokyo Lonely Walker、Tokyo Hz、祭りが好き!、shu channel。"),
        todo("YouTube検索クエリを広げる前に、quota消費と重複動画の扱いを決める。"),
        todo("章タイトル型の曲目抽出を改善する。英語併記、アーティスト名つき、曲名だけを正規化する。"),
        todo("動画説明欄から会場名を抽出するルールを強化する。開催場所、場所、Google Mapsリンク周辺を優先する。"),
        todo("Notionスキーマ上でYouTube証拠をどこに置くか決める。候補: イベントの開催パターン詳細、証拠メモ、別DB。"),
        todo("公開UIでYouTubeリンクとサムネイルを表示する場所を決める。イベント詳細、曲詳細、証拠一覧のどこに置くかを分ける。"),
        todo("採用済みYouTubeチャンネルから定期ではなく手動実行で過去イベントを追加できる運用手順を作る。"),
        heading(2, "直近の判断"),
        bullet("すぐNotion本DBを更新してよいのは、既存イベントへの証拠追記候補だけ。"),
        bullet("新規イベント作成は、YouTube候補だけではなく公式確認または複数証拠を待つ。"),
        bullet("この課題リスト自体を、今後YouTubeデータ活用の入口として参照する。"),
    ]


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


def main():
    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    parent_page_id = NOTION_PAGE_ID or search_page_id(FALLBACK_QUERY)
    if not parent_page_id:
        raise SystemExit("Notion parent page was not found")
    title = "今後の課題リスト: YouTubeデータ活用"
    page = create_page(parent_page_id, title)
    append_blocks(page["id"], task_blocks())
    output = {
        "generated_by": "append_youtube_task_list_to_notion.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "title": title,
        "page_id": page["id"],
        "url": page.get("url") or "",
        "parent_page_id": parent_page_id,
    }
    atomic_write_json(OUT, output)
    print(f"NotionにYouTube課題リストを作成しました: {page.get('url') or page['id']}")


if __name__ == "__main__":
    main()
