import os
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

try:
    import feedparser
    _HAS_FEEDPARSER = True
except ImportError:
    _HAS_FEEDPARSER = False

# --- Notion 連携設定 ---
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")
NOTION_PAGE_ID = os.environ.get("NOTION_PAGE_ID")
NOTION_VERSION = "2022-06-28"
NOTION_API = "https://api.notion.com/v1"

QUERIES = ["盆踊り", "盆おどり"]
HOME_KEYWORDS = []

def fetch_news(query):
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=ja&gl=JP&ceid=JP:ja"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            return response.read()
    except Exception as e:
        print(f"Error fetching {query}: {e}")
        return None

def parse_rss(xml_data):
    items = []
    if not xml_data:
        return items
    try:
        root = ET.fromstring(xml_data)
        for item in root.findall('.//item'):
            title = item.find('title').text if item.find('title') is not None else ''
            link = item.find('link').text if item.find('link') is not None else ''
            pub_date = item.find('pubDate').text if item.find('pubDate') is not None else ''
            items.append({'title': title, 'url': link, 'pubDate': pub_date})
    except Exception as e:
        print(f"Error parsing XML: {e}")
    return items

def _notion_request(method, path, payload=None):
    url = f"{NOTION_API}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {NOTION_TOKEN}")
    req.add_header("Notion-Version", NOTION_VERSION)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())


def _chunk_text(text, size=1900):
    """Notion の rich_text 1要素は2000文字上限。分割して返す。"""
    return [text[i:i + size] for i in range(0, len(text), size)] or [""]


def _rich_text(content):
    return [{"type": "text", "text": {"content": c}} for c in _chunk_text(content)]


def push_to_notion(latest_items, updated_at):
    """Notion ページの内容を最新データで全面更新する。"""
    if not NOTION_TOKEN or not NOTION_PAGE_ID:
        print("Notion未設定 (NOTION_API_TOKEN / NOTION_PAGE_ID) のためスキップ")
        return

    try:
        # 1) 既存の子ブロックを全削除
        children = _notion_request("GET", f"/blocks/{NOTION_PAGE_ID}/children?page_size=100")
        for block in children.get("results", []):
            _notion_request("DELETE", f"/blocks/{block['id']}")

        # 2) 最新内容を組み立てて追加
        json_text = json.dumps(latest_items, ensure_ascii=False, indent=2)
        new_blocks = [
            {"object": "block", "type": "callout",
             "callout": {"icon": {"emoji": "🤖"},
                         "rich_text": _rich_text("このページはGitHub Actions（bon-odori-collector）が自動更新します。手動で編集しないでください。")}},
            {"object": "block", "type": "heading_2",
             "heading_2": {"rich_text": _rich_text("最終更新")}},
            {"object": "block", "type": "paragraph",
             "paragraph": {"rich_text": _rich_text(updated_at)}},
            {"object": "block", "type": "heading_2",
             "heading_2": {"rich_text": _rich_text("収集データ（JSON）")}},
            {"object": "block", "type": "code",
             "code": {"language": "json", "rich_text": _rich_text(json_text)}},
            {"object": "block", "type": "heading_2",
             "heading_2": {"rich_text": _rich_text("ステータス")}},
            {"object": "block", "type": "bulleted_list_item",
             "bulleted_list_item": {"rich_text": _rich_text(f"最終実行: {updated_at}")}},
            {"object": "block", "type": "bulleted_list_item",
             "bulleted_list_item": {"rich_text": _rich_text(f"取得件数: {len(latest_items)}件")}},
        ]
        _notion_request("PATCH", f"/blocks/{NOTION_PAGE_ID}/children", {"children": new_blocks})
        print(f"Notion更新完了: {len(latest_items)}件")
    except Exception as e:
        print(f"Notion更新エラー: {e}")
        raise


# --- Voices (人の声) 収集設定 ---
# RSS が取得できない場合でも他ソースの収集は継続する（fail-safe）
VOICE_FEEDS = [
    {
        "source": "youtube",
        "account": "@wadaikoCH",
        "name": "和太鼓お祭りCH",
        "rss_url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCNF_5e3ZvziJueTWvTPATGw",
    },
    {
        "source": "note",
        "account": "@karinchanchanko",
        "name": "りんりん",
        "rss_url": "https://note.com/karinchanchanko/rss",
    },
]

# voices スキーマ:
# { source, account, name, title, text, url, date (ISO8601), tags }

def _parse_voice_entry(entry, feed_meta):
    """feedparser の entry を voices スキーマに変換する。"""
    title = entry.get("title", "")
    url = entry.get("link", "")

    # 本文: summary → content → "" の順
    text = ""
    if "summary" in entry:
        text = entry["summary"]
    elif "content" in entry and entry["content"]:
        text = entry["content"][0].get("value", "")
    # HTMLタグを除去して500字程度に切り詰め
    import re as _re
    text = _re.sub(r"<[^>]+>", "", text).strip()[:500]

    # 日付
    date_str = ""
    if "published_parsed" in entry and entry["published_parsed"]:
        from time import mktime
        dt = datetime.fromtimestamp(mktime(entry["published_parsed"]), tz=timezone.utc)
        date_str = dt.isoformat()
    elif "updated_parsed" in entry and entry["updated_parsed"]:
        from time import mktime
        dt = datetime.fromtimestamp(mktime(entry["updated_parsed"]), tz=timezone.utc)
        date_str = dt.isoformat()

    tags = [t.get("term", "") for t in entry.get("tags", []) if t.get("term")]

    return {
        "source": feed_meta["source"],
        "account": feed_meta["account"],
        "name": feed_meta["name"],
        "title": title,
        "text": text,
        "url": url,
        "date": date_str,
        "tags": tags,
    }


def collect_voices(seen_urls: set) -> tuple[list, list]:
    """
    VOICE_FEEDS から RSS を取得して voices エントリを返す。
    戻り値: (new_items, all_seen_urls_updated)
    feedparser 未インストール or RSS 取得失敗でも空リストを返す（fail-safe）。
    """
    if not _HAS_FEEDPARSER:
        print("[voices] feedparser がインストールされていないためスキップします")
        return [], list(seen_urls)

    new_items = []
    new_seen = list(seen_urls)

    for feed_meta in VOICE_FEEDS:
        rss_url = feed_meta["rss_url"]
        print(f"[voices] 取得中: {feed_meta['name']} ({rss_url})")
        try:
            parsed = feedparser.parse(rss_url)
            if parsed.bozo and not parsed.entries:
                print(f"[voices] スキップ (取得失敗 or 空): {feed_meta['name']}")
                continue

            count = 0
            for entry in parsed.entries:
                url = entry.get("link", "")
                if not url or url in seen_urls or url in new_seen:
                    continue
                item = _parse_voice_entry(entry, feed_meta)
                new_items.append(item)
                new_seen.append(url)
                count += 1

            print(f"[voices] {feed_meta['name']}: {count} 件追加")

        except Exception as e:
            print(f"[voices] エラー ({feed_meta['name']}): {e}")
            # fail-safe: このソースの失敗は他ソースに影響させない

    return new_items, new_seen


def main():
    seen_file = 'data/seen.json'
    seen_urls = set()
    if os.path.exists(seen_file):
        try:
            with open(seen_file, 'r', encoding='utf-8') as f:
                seen_urls = set(json.load(f))
        except:
            pass

    latest_items = []
    seen_in_run = set()       # この実行内での重複除去用
    new_urls = list(seen_urls)

    for q in QUERIES:
        print(f"Searching for: {q}")
        xml_data = fetch_news(q)
        items = parse_rss(xml_data)

        for item in items:
            # 同一実行内の重複（クエリ間の被り）はスキップ
            if item['url'] in seen_in_run:
                continue
            seen_in_run.add(item['url'])

            is_home = any(k in item['title'] for k in HOME_KEYWORDS) if HOME_KEYWORDS else False
            # 現在取得できた記事は全件 latest に含める（全件スナップショット）
            latest_items.append({
                'title': item['title'],
                'url': item['url'],
                'date': item['pubDate'],
                'is_home': is_home
            })
            # seen.json は履歴として累積（新規URLのみ追加）
            if item['url'] not in seen_urls:
                new_urls.append(item['url'])

    os.makedirs('data', exist_ok=True)

    with open('data/latest.json', 'w', encoding='utf-8') as f:
        json.dump(latest_items, f, ensure_ascii=False, indent=2)

    with open(seen_file, 'w', encoding='utf-8') as f:
        json.dump(new_urls, f, ensure_ascii=False, indent=2)

    print(f"完了: 全 {len(latest_items)} 件を記録しました。")

    # --- voices 収集（fail-safe: 失敗してもニュース収集結果に影響しない）---
    try:
        voices_seen_file = 'data/voices_seen.json'
        voices_seen_urls = set()
        if os.path.exists(voices_seen_file):
            try:
                with open(voices_seen_file, 'r', encoding='utf-8') as f:
                    voices_seen_urls = set(json.load(f))
            except Exception:
                pass

        voice_items, updated_voices_seen = collect_voices(voices_seen_urls)

        # voices.json: 全件スナップショット（seen に入っていない新規のみ追加）
        voices_file = 'data/voices.json'
        existing_voices = []
        if os.path.exists(voices_file):
            try:
                with open(voices_file, 'r', encoding='utf-8') as f:
                    existing_voices = json.load(f)
            except Exception:
                pass

        # 既存 + 新規（新規を先頭に）
        merged_voices = voice_items + existing_voices
        # URL で重複排除（順序を保持）
        seen_in_merge = set()
        deduped_voices = []
        for v in merged_voices:
            if v["url"] not in seen_in_merge:
                deduped_voices.append(v)
                seen_in_merge.add(v["url"])

        with open(voices_file, 'w', encoding='utf-8') as f:
            json.dump(deduped_voices, f, ensure_ascii=False, indent=2)

        with open(voices_seen_file, 'w', encoding='utf-8') as f:
            json.dump(updated_voices_seen, f, ensure_ascii=False, indent=2)

        print(f"[voices] 完了: 新規 {len(voice_items)} 件、累計 {len(deduped_voices)} 件")
    except Exception as e:
        print(f"[voices] 予期せぬエラー（ニュース収集には影響なし）: {e}")

    # Notion へ書き戻し
    jst = timezone(timedelta(hours=9))
    updated_at = datetime.now(jst).strftime("%Y-%m-%d %H:%M JST")
    push_to_notion(latest_items, updated_at)

if __name__ == '__main__':
    main()
