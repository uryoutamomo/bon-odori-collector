import os
import json
import urllib.request
import urllib.parse
import urllib.error
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

# --- X(twitterapi.io)収集設定 ---
# キーは GitHub Secrets / 環境変数で渡す。未設定なら X 収集はスキップ（fail-safe）。
TWITTERAPI_IO_KEY = os.environ.get("TWITTERAPI_IO_KEY")
# 「🐦 X収集ログ DB」（盆踊り情報開発 配下）。DB ID は秘匿情報ではないので既定値を持つ。
X_LOG_DB_ID = os.environ.get("X_LOG_DB_ID", "ef2f627d-3ac5-4133-9abd-f5d6d655afa7")
TWITTERAPI_IO_BASE = "https://api.twitterapi.io/twitter/tweet/advanced_search"
X_QUERIES_FILE = "x_queries.json"
X_BUDGET_FILE = "data/x_budget.json"

QUERIES = ["盆踊り", "盆おどり"]
HOME_KEYWORDS = []

# --- blogspot / 外部ブログRSS設定 ---
# feedparser で取得して latest.json に統合する
# タグフィードはメインのサブセットなので de-dup で重複を自動排除
BLOG_FEEDS = [
    {
        "source": "blogspot",
        "name": "東京盆踊りマップ",
        "rss_url": "http://minato-bon-odori.blogspot.com/feeds/posts/default",
    },
    {
        "source": "blogspot",
        "name": "東京盆踊りマップ（中央区）",
        "rss_url": "http://minato-bon-odori.blogspot.com/feeds/posts/default/-/%E4%B8%AD%E5%A4%AE%E5%8C%BA",
    },
    {
        "source": "blogspot",
        "name": "東京盆踊りマップ（台東区）",
        "rss_url": "http://minato-bon-odori.blogspot.com/feeds/posts/default/-/%E5%8F%B0%E6%9D%B1%E5%8C%BA",
    },
    {
        "source": "blogspot",
        "name": "東京盆踊りマップ（墨田区）",
        "rss_url": "http://minato-bon-odori.blogspot.com/feeds/posts/default/-/%E5%A2%A8%E7%94%B0%E5%8C%BA",
    },
    {
        "source": "blogspot",
        "name": "東京盆踊りマップ（江東区）",
        "rss_url": "http://minato-bon-odori.blogspot.com/feeds/posts/default/-/%E6%B1%9F%E6%9D%B1%E5%8C%BA",
    },
    {
        "source": "bonmaru",
        "name": "盆まる",
        "rss_url": "https://bonmaru.zenmin-odori.jp/feed",
    },
]

def fetch_news(query):
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=ja&gl=JP&ceid=JP:ja"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            return response.read()
    except Exception as e:
        print(f"Error fetching {query}: {e}")
        return None

def fetch_blog_feeds(seen_in_run: set) -> list:
    """
    BLOG_FEEDS から feedparser で記事を取得して latest.json 形式のリストを返す。
    seen_in_run で同一実行内の重複（タグフィード間の重複含む）を除去。
    失敗しても空リストを返す（fail-safe）。
    """
    if not _HAS_FEEDPARSER:
        print("[blog] feedparser 未インストールのためスキップ")
        return []

    items = []
    for feed_meta in BLOG_FEEDS:
        try:
            parsed = feedparser.parse(feed_meta["rss_url"])
            if parsed.bozo and not parsed.entries:
                print(f"[blog] スキップ (取得失敗 or 空): {feed_meta['name']}")
                continue

            count = 0
            for entry in parsed.entries:
                url = entry.get("link", "")
                if not url or url in seen_in_run:
                    continue
                seen_in_run.add(url)

                title = entry.get("title", "")
                date_str = ""
                if "published_parsed" in entry and entry["published_parsed"]:
                    from time import mktime
                    dt = datetime.fromtimestamp(mktime(entry["published_parsed"]), tz=timezone.utc)
                    date_str = dt.isoformat()
                elif "updated_parsed" in entry and entry["updated_parsed"]:
                    from time import mktime
                    dt = datetime.fromtimestamp(mktime(entry["updated_parsed"]), tz=timezone.utc)
                    date_str = dt.isoformat()

                items.append({
                    "title": title,
                    "url": url,
                    "date": date_str,
                    "is_home": False,
                    "source": feed_meta["source"],
                })
                count += 1

            print(f"[blog] {feed_meta['name']}: {count} 件追加")

        except Exception as e:
            print(f"[blog] エラー ({feed_meta['name']}): {e}")

    return items


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
        "source": "youtube",
        "account": "@matsuribonodori",
        "name": "祭のきせき 盆踊り",
        "rss_url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCLSZK_q5ma6aeIrVRUEpkNw",
    },
    {
        "source": "ameba",
        "account": "@karinchanchanko",
        "name": "りんりん",
        "rss_url": "https://rssblog.ameba.jp/karinchanchanko/rss20.xml",
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


# --- X(twitterapi.io) 収集：改善ループの最小ループ(A+B) ---
# 設計: 盆踊り情報開発 >「X収集 改善ループ 設計アイデア」
# A. クエリ設定は x_queries.json に外出し（コードを触らず実験できる）
# B. 取得→ルールベース自動仕分け→「🐦 X収集ログ DB」へ1行ずつ蓄積
# 安全装置: 予算上限ガード／429ウェイト／例外で他収集に影響させない fail-safe

def _load_x_config():
    """x_queries.json を読む。無ければ None（=X収集スキップ）。"""
    try:
        with open(X_QUERIES_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if cfg.get("enabled", True) else None
    except FileNotFoundError:
        print(f"[x] {X_QUERIES_FILE} が無いため X 収集をスキップ")
        return None
    except Exception as e:
        print(f"[x] 設定読み込みエラー（X収集スキップ）: {e}")
        return None


def _score_voice(text, cfg):
    """ルールベース自動仕分け。🟢一次レポ / 🟡関心 / 🔴ノイズ を返す。
    除外語(比喩・曲名・ゲーム系)が含まれれば🔴、体験語があれば🟢、それ以外は🟡。"""
    low = text.lower()
    for kw in cfg.get("exclude_keywords", []):
        if kw.lower() in low:
            return "🔴ノイズ"
    for kw in cfg.get("experience_keywords", []):
        if kw.lower() in low:
            return "🟢一次レポ"
    return "🟡関心"


def _x_budget_state():
    """data/x_budget.json から {日付: 当日コスト} を読む。"""
    try:
        with open(X_BUDGET_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _x_search(query, cursor=""):
    """twitterapi.io advanced_search を1ページ取得。429は呼び出し側で扱う。"""
    params = {"query": query, "queryType": "Latest"}
    if cursor:
        params["cursor"] = cursor
    url = f"{TWITTERAPI_IO_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"X-API-Key": TWITTERAPI_IO_KEY})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _x_map_to_voice(tw):
    """twitterapi.io のツイートを voices スキーマに変換（best-effort）。"""
    author = tw.get("author") or tw.get("user") or {}
    username = author.get("userName") or author.get("screen_name") or ""
    name = author.get("name") or ""
    tw_id = tw.get("id") or tw.get("id_str") or ""
    url = tw.get("url") or (f"https://x.com/{username}/status/{tw_id}" if username and tw_id else "")
    raw_date = tw.get("createdAt") or tw.get("created_at") or ""
    # Twitter形式 "Tue Jun 03 12:34:56 +0000 2026" を ISO8601 へ（失敗時は生値のまま）
    date_iso = raw_date
    if raw_date:
        try:
            date_iso = datetime.strptime(raw_date, "%a %b %d %H:%M:%S %z %Y").isoformat()
        except ValueError:
            pass
    return {
        "source": "x",
        "account": f"@{username}" if username else "",
        "name": name,
        "title": "",
        "text": (tw.get("text") or tw.get("full_text") or "").strip()[:500],
        "url": url,
        "date": date_iso,
        "tags": [],
    }


def _append_x_log_row(voice, query_id, judgement, cost):
    """「🐦 X収集ログ DB」に1行追記。Notion未設定なら静かにスキップ。"""
    if not NOTION_TOKEN or not X_LOG_DB_ID:
        return
    text = voice["text"] or "(本文なし)"
    props = {
        "本文": {"title": [{"text": {"content": text[:1900]}}]},
        "クエリID": {"select": {"name": query_id}},
        "自動判定": {"select": {"name": judgement}},
        "正解ラベル": {"select": {"name": "未評価"}},
        "アカウント": {"rich_text": [{"text": {"content": voice["account"][:200]}}]},
        "コスト": {"number": round(cost, 6)},
    }
    if voice["url"]:
        props["URL"] = {"url": voice["url"]}
    if voice["date"]:
        try:
            datetime.fromisoformat(voice["date"])
            props["日付"] = {"date": {"start": voice["date"]}}
        except ValueError:
            pass
    try:
        _notion_request("POST", "/pages",
                        {"parent": {"database_id": X_LOG_DB_ID}, "properties": props})
    except Exception as e:
        print(f"[x] ログDB追記エラー（収集は継続）: {e}")


def collect_x_voices(seen_urls: set) -> tuple[list, list]:
    """X(twitterapi.io)から「人の言葉」を収集。
    戻り値: (new_items, all_seen_urls_updated) — collect_voices と同じ形。
    キー未設定・設定欠如・予算超過のいずれも空で返す fail-safe。"""
    if not TWITTERAPI_IO_KEY:
        print("[x] TWITTERAPI_IO_KEY 未設定のため X 収集をスキップ")
        return [], list(seen_urls)
    cfg = _load_x_config()
    if not cfg:
        return [], list(seen_urls)

    budget = cfg.get("budget", {})
    cost_per_tweet = budget.get("cost_per_tweet_usd", 0.00015)
    daily_cap = budget.get("daily_usd", 0.05)
    monthly_cap = budget.get("monthly_usd", 0.5)

    import time as _time
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    month = today[:7]
    state = _x_budget_state()
    daily_spent = state.get(today, 0.0)
    monthly_spent = sum(v for k, v in state.items() if k.startswith(month))
    if daily_spent >= daily_cap or monthly_spent >= monthly_cap:
        print(f"[x] 予算上限に到達のためスキップ（日 ${daily_spent:.4f}/{daily_cap} 月 ${monthly_spent:.4f}/{monthly_cap}）")
        return [], list(seen_urls)

    max_pages = cfg.get("max_pages_per_query", 2)
    page_sleep = cfg.get("page_sleep_sec", 2)
    new_items = []
    new_seen = list(seen_urls)
    run_cost = 0.0

    for q in cfg.get("queries", []):
        qid, query = q.get("id", "q-?"), q.get("query", "")
        if not query:
            continue
        print(f"[x] {qid}: {query}")
        cursor = ""
        for page in range(max_pages):
            # 予算の最終ガード（クエリ途中でも止まる）
            if daily_spent + run_cost >= daily_cap or monthly_spent + run_cost >= monthly_cap:
                print("[x] 走行中に予算上限到達。以降のページを打ち切り")
                break
            try:
                data = _x_search(query, cursor)
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    print("[x] 429（QPS制限）。5秒待って1回だけ再試行")
                    _time.sleep(5)
                    try:
                        data = _x_search(query, cursor)
                    except Exception as e2:
                        print(f"[x] 再試行も失敗、このクエリを打ち切り: {e2}")
                        break
                else:
                    print(f"[x] HTTPエラー {e.code}、このクエリを打ち切り")
                    break
            except Exception as e:
                print(f"[x] 取得エラー、このクエリを打ち切り: {e}")
                break

            tweets = data.get("tweets") or data.get("data") or []
            if not tweets:
                break
            run_cost += len(tweets) * cost_per_tweet

            count = 0
            for tw in tweets:
                v = _x_map_to_voice(tw)
                if not v["url"] or v["url"] in seen_urls or v["url"] in new_seen:
                    continue
                judgement = _score_voice(v["text"], cfg)
                v["tags"] = [judgement, qid]
                _append_x_log_row(v, qid, judgement, cost_per_tweet)
                # voices.json には一次レポ/関心のみ流す（ノイズは除外）
                if judgement != "🔴ノイズ":
                    new_items.append(v)
                new_seen.append(v["url"])
                count += 1
            print(f"[x] {qid}: {count} 件処理（うち voices 採用 {sum(1 for x in new_items if qid in x.get('tags', []))} 件累計）")

            cursor = data.get("next_cursor") or data.get("cursor") or ""
            if not (data.get("has_next_page", bool(cursor)) and cursor):
                break
            _time.sleep(page_sleep)

    # 予算消費を記録
    if run_cost > 0:
        state[today] = daily_spent + run_cost
        try:
            os.makedirs("data", exist_ok=True)
            with open(X_BUDGET_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[x] 予算記録の保存エラー: {e}")

    print(f"[x] 完了: voices採用 {len(new_items)} 件、今回コスト 約${run_cost:.5f}")
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

    # --- blogspot / bonmaru 収集（fail-safe）---
    try:
        blog_items = fetch_blog_feeds(seen_in_run)
        for item in blog_items:
            latest_items.append(item)
            if item['url'] not in seen_urls:
                new_urls.append(item['url'])
        if blog_items:
            print(f"[blog] 合計 {len(blog_items)} 件を latest.json に追加しました")
    except Exception as e:
        print(f"[blog] 予期せぬエラー（ニュース収集には影響なし）: {e}")

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

        # X(twitterapi.io) からの「人の言葉」も同じ voices_seen を共有して収集（fail-safe）
        try:
            x_items, updated_voices_seen = collect_x_voices(set(updated_voices_seen))
            voice_items = voice_items + x_items
        except Exception as e:
            print(f"[x] 予期せぬエラー（他収集には影響なし）: {e}")

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

    # Notion へ書き戻し（直近7日分のみ）
    jst = timezone(timedelta(hours=9))
    updated_at = datetime.now(jst).strftime("%Y-%m-%d %H:%M JST")
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    def _parse_date(date_str):
        if not date_str:
            return None
        for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
            except ValueError:
                pass
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            return None

    recent_items = [
        item for item in latest_items
        if (_parse_date(item.get("date")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
    ]
    push_to_notion(recent_items if recent_items else latest_items[:30], updated_at)

if __name__ == '__main__':
    main()
