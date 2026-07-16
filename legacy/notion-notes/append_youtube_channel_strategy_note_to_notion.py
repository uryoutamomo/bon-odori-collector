"""Append the YouTube channel discovery strategy note to the Notion ops page."""

import os
import urllib.request
import json

from notion_config import load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")
NOTION_PAGE_ID = os.environ.get("NOTION_PAGE_ID", "")
FALLBACK_QUERY = "盆踊りデータ統一モデル"


def rich_text(text):
    return [{"type": "text", "text": {"content": text[:2000]}}]


def block_paragraph(text):
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(text)}}


def block_heading(text):
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": rich_text(text)},
    }


def block_bullet(text):
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": rich_text(text)},
    }


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


def plain_title(obj):
    props = obj.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            return "".join(part.get("plain_text", "") for part in prop.get("title", []))
    return "".join(part.get("plain_text", "") for part in obj.get("title") or [])


def search_page_id(query):
    payload = {
        "query": query,
        "filter": {"property": "object", "value": "page"},
        "page_size": 10,
    }
    data = notion_request("POST", "/search", payload)
    results = data.get("results") or []
    if not results:
        return ""
    preferred = [
        item for item in results
        if "統一モデル" in plain_title(item) or "盆踊り" in plain_title(item)
    ]
    return (preferred or results)[0].get("id") or ""


def main():
    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    page_id = NOTION_PAGE_ID or search_page_id(FALLBACK_QUERY)
    if not page_id:
        raise SystemExit("Notion append target page was not found")
    children = [
        block_heading("YouTubeチャンネルDB化・過去イベント発掘方針メモ"),
        block_paragraph(
            "内田さんとの会話メモ。Xの盆踊ラーリスト相当として、価値あるYouTubeチャンネルを発掘・DB化し、"
            "過去イベント、特に前年イベント情報を広く拾う発見ソースにする。曲の練習導線としてYouTubeリンクを使い、"
            "チャンネル運営者への送客にもなる形を目指す。署名: おと（Codex）"
        ),
        block_bullet("YouTubeチャンネルDB: channel_id/title/url/handle/thumbnail_url、収集ステータス、自動スコア、盆踊り動画数、セットリスト成功数、会場日付抽出成功数、曲リンク率、信頼度を持つ。"),
        block_bullet("YouTube動画DB: video_id/url/channel_id/title/description/published_at/thumbnail_url、event_date、venue_hint、event_name_hint、setlist、matched_event、matched_venue、statusを持つ。"),
        block_bullet("動画から occurrence/evidence/event_songs へ接続する。source=youtube_setlist_occurrence、role=result、act=observe。YouTube URLとthumbnail_urlは evidence/公開UIで使う。"),
        block_bullet("発掘は、既存2チャンネルを初期登録し、既存199本からスコアリングを作り、YouTube検索APIで候補動画・候補チャンネルを増やす。"),
        block_bullet("2025年イベント追加は、検索→日付/会場/イベント名抽出→既存DB名寄せ→未登録はレビューJSON→採用後に過去occurrence登録、同時にセットリストをevent_songsへ登録する。"),
        block_bullet("次の作業候補: data/youtube_channels.json、discover_youtube_channels.py、data/youtube_channel_candidates.json、data/youtube_event_candidates.json。"),
    ]
    notion_request("PATCH", f"/blocks/{page_id}/children", {"children": children})
    print("NotionへYouTubeチャンネルDB化方針メモを追記しました")


if __name__ == "__main__":
    main()
