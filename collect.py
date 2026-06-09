import os
import re
import json
import hashlib
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from proactive_search import (
    build_queries,
    build_report,
    check_official_sources,
    is_target_confirmation,
    load_targets,
    select_due_targets,
)
from queue_store import DynamoQueueStore
from event_evidence import (
    build_history_query,
    build_initial_window,
    classify_event_evidence,
)

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


def _env_or_default(name, default):
    return os.environ.get(name) or default

# --- X(twitterapi.io)収集設定 ---
# キーは GitHub Secrets / 環境変数で渡す。未設定なら X 収集はスキップ（fail-safe）。
TWITTERAPI_IO_KEY = os.environ.get("TWITTERAPI_IO_KEY")
# 「🐦 X収集ログ DB」（盆踊り情報開発 配下）。DB ID は秘匿情報ではないので既定値を持つ。
X_LOG_DB_ID = _env_or_default("X_LOG_DB_ID", "ef2f627d-3ac5-4133-9abd-f5d6d655afa7")
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


def _rich_text(content, link=None):
    out = []
    for c in _chunk_text(content):
        t = {"content": c}
        if link:
            t["link"] = {"url": link}
        out.append({"type": "text", "text": t})
    return out


def push_to_notion(latest_items, updated_at, x_voices=None, x_cost=None,
                   sokuho=None, event_signals=None, proactive_report=None):
    """Notion ページの内容を最新データで全面更新する。

    x_voices: X由来の「人の言葉」（一次レポ/関心、直近分）。
    x_cost: {"today", "month", "daily_cap", "monthly_cap"}。コスト見える化用。
    sokuho: detect_sokuho() の結果。未知イベント速報候補リスト。
    event_signals: detect_x_confidence_signals() の結果。既存イベント確度変化リスト。
    proactive_report: 定番イベントの確認済み/未確認レポート。
    """
    x_voices = x_voices or []
    sokuho = sokuho or []
    event_signals = event_signals or []
    proactive_report = proactive_report or []
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
        ]

        # 📣 速報セクション（未知イベント速報候補）
        new_blocks.append(
            {"object": "block", "type": "heading_2",
             "heading_2": {"rich_text": _rich_text("📣 速報（新イベント候補）")}})
        if sokuho:
            for s in sokuho:
                score = s.get("value_score", 0)
                acct = (s.get("account") or "").lstrip("@")
                text = (s.get("text") or "").replace("\n", " ").strip()[:120]
                line = f"【{s['venue']}】score:{score} @{acct}: {text}"
                new_blocks.append(
                    {"object": "block", "type": "bulleted_list_item",
                     "bulleted_list_item": {"rich_text": _rich_text(line, s.get("url"))}})
        else:
            new_blocks.append(
                {"object": "block", "type": "paragraph",
                 "paragraph": {"rich_text": _rich_text("（本日の新イベント速報はありません）")}})

        # 🔄 イベント更新セクション（既存イベントの確度変化）
        new_blocks.append(
            {"object": "block", "type": "heading_2",
             "heading_2": {"rich_text": _rich_text("🔄 イベント更新（確度変化）")}})
        if event_signals:
            for s in event_signals:
                icon = "✅" if s["signal"] == "confirm" else "⚠️"
                acct = (s.get("account") or "").lstrip("@")
                text = (s.get("text") or "").replace("\n", " ").strip()[:120]
                line = f"{icon}【{s['venue']}】@{acct}: {text}"
                new_blocks.append(
                    {"object": "block", "type": "bulleted_list_item",
                     "bulleted_list_item": {"rich_text": _rich_text(line, s.get("url"))}})
        else:
            new_blocks.append(
                {"object": "block", "type": "paragraph",
                 "paragraph": {"rich_text": _rich_text("（本日のイベント更新情報はありません）")}})

        # 🔎 定番イベント確認（能動検索・公式情報源・抜け漏れ検出）
        new_blocks.append(
            {"object": "block", "type": "heading_2",
             "heading_2": {"rich_text": _rich_text("🔎 定番イベント確認")}})
        if proactive_report:
            for item in proactive_report:
                confirmed = item.get("status") == "confirmed"
                icon = "✅" if confirmed else "⚠️"
                months = "/".join(str(m) for m in item.get("months", []))
                line = (
                    f"{icon}【{item['event_name']}】"
                    f"例年{months}月 "
                    f"{'今年の情報を確認' if confirmed else '今年の情報が未確認'}"
                )
                evidence = item.get("evidence") or []
                link = evidence[0].get("url") if evidence else None
                new_blocks.append(
                    {"object": "block", "type": "bulleted_list_item",
                     "bulleted_list_item": {"rich_text": _rich_text(line, link)}})
        else:
            new_blocks.append(
                {"object": "block", "type": "paragraph",
                 "paragraph": {"rich_text": _rich_text("（現在、確認対象の定番イベントはありません）")}})

        # X由来の「人の言葉」セクション（配信に使う一次レポ/関心）
        new_blocks.append(
            {"object": "block", "type": "heading_2",
             "heading_2": {"rich_text": _rich_text("🗣️ 人の言葉（X由来 / 配信ネタ）")}})
        if x_voices:
            for v in x_voices:
                acct = (v.get("account") or v.get("name") or "").lstrip("@")
                text = (v.get("text") or "").replace("\n", " ").strip()
                if len(text) > 140:
                    text = text[:140] + "…"
                tags = v.get("tags") or []
                label = next((t for t in tags if "一次レポ" in t or "関心" in t), "")
                head = " ".join(x for x in [label, f"@{acct}" if acct else ""] if x)
                line = f"{head}: {text}" if head else text
                new_blocks.append(
                    {"object": "block", "type": "bulleted_list_item",
                     "bulleted_list_item": {"rich_text": _rich_text(line, v.get("url"))}})
        else:
            new_blocks.append(
                {"object": "block", "type": "paragraph",
                 "paragraph": {"rich_text": _rich_text("（直近のX由来の一次レポ/関心はありません）")}})

        new_blocks += [
            {"object": "block", "type": "heading_2",
             "heading_2": {"rich_text": _rich_text("ステータス")}},
            {"object": "block", "type": "bulleted_list_item",
             "bulleted_list_item": {"rich_text": _rich_text(f"最終実行: {updated_at}")}},
            {"object": "block", "type": "bulleted_list_item",
             "bulleted_list_item": {"rich_text": _rich_text(f"取得件数: {len(latest_items)}件")}},
            {"object": "block", "type": "bulleted_list_item",
             "bulleted_list_item": {"rich_text": _rich_text(f"人の言葉(X由来): {len(x_voices)}件")}},
        ]
        if x_cost:
            t = x_cost.get("today", 0.0)
            m = x_cost.get("month", 0.0)
            dcap = x_cost.get("daily_cap", 0.0)
            mcap = x_cost.get("monthly_cap", 0.0)
            new_blocks.append(
                {"object": "block", "type": "bulleted_list_item",
                 "bulleted_list_item": {"rich_text": _rich_text(
                     f"💰 X収集コスト: 本日 ${t:.4f} / 上限 ${dcap:.2f}　｜　今月累計 ${m:.4f} / 上限 ${mcap:.2f}")}})
        _notion_request("PATCH", f"/blocks/{NOTION_PAGE_ID}/children", {"children": new_blocks})
        print(f"Notion更新完了: ニュース{len(latest_items)}件 / X由来{len(x_voices)}件")
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
        "tweet_id": str(tw_id),
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


def collect_proactive_x(targets, seen_urls, config):
    """開催月が近い定番イベントを会場名で能動検索する。予算は通常X収集と共有。"""
    if not TWITTERAPI_IO_KEY or not targets:
        return [], list(seen_urls)
    x_cfg = _load_x_config() or {}
    budget = x_cfg.get("budget", {})
    cost_per_tweet = budget.get("cost_per_tweet_usd", 0.00015)
    daily_cap = budget.get("daily_usd", 0.3)
    monthly_cap = budget.get("monthly_usd", 5.0)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    month = today[:7]
    state = _x_budget_state()
    daily_spent = state.get(today, 0.0)
    monthly_spent = sum(v for k, v in state.items() if k.startswith(month))
    limit = int(config.get("max_x_queries_per_run", 6))
    year = datetime.now(timezone(timedelta(hours=9))).year
    new_items, new_seen, run_cost = [], list(seen_urls), 0.0

    for target in targets[:limit]:
        if daily_spent + run_cost >= daily_cap or monthly_spent + run_cost >= monthly_cap:
            print("[proactive/x] 予算上限到達。以降の能動検索を打ち切り")
            break
        query = build_queries(target, year)["x"]
        try:
            data = _x_search(query)
        except Exception as exc:
            print(f"[proactive/x] {target['venue']} 検索失敗: {exc}")
            continue
        tweets = data.get("tweets") or data.get("data") or []
        run_cost += max(len(tweets), 1) * cost_per_tweet
        count = 0
        for tweet in tweets:
            voice = _x_map_to_voice(tweet)
            if not voice["url"] or voice["url"] in seen_urls or voice["url"] in new_seen:
                continue
            voice["source"] = "x_proactive"
            voice["tags"] = ["🔎能動検索", target["venue"]]
            new_items.append(voice)
            new_seen.append(voice["url"])
            count += 1
        print(f"[proactive/x] {target['venue']}: {count} 件追加")

    if run_cost:
        state[today] = daily_spent + run_cost
        try:
            with open(X_BUDGET_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            print(f"[proactive/x] 予算記録の保存エラー: {exc}")
    return new_items, new_seen


# --- ホワイトリスト収集 / 会場検知→裏取りキュー（2段構え）---
# 仕様: 盆踊り情報開発 >「🔎 盆踊ラー起点・会場裏取り 2段構え（仕様）」
# A. 既存「X メンバーリスト」DB の from: をバッチ収集（since_time で新規のみ）→ ⭐盆踊ラー最優先
# B. 盆踊ラー声＋ニュースから会場名を検知 →「🔎 裏取りキュー」DB へ（裏取りはこわ）。既出は再投入しない。

X_MEMBER_LIST_DB_ID = _env_or_default("X_MEMBER_LIST_DB_ID", "5c585224465241548b631e4e5d316f3b")
TORIMOCHI_QUEUE_DB_ID = _env_or_default("TORIMOCHI_QUEUE_DB_ID", "f560afee832f4b1084d6e6093d74da16")
GLOSSARY_DB_ID = _env_or_default("GLOSSARY_DB_ID", "989e9effc7fc40db8043a3b8e03090ee")
VENUE_MASTER_FILE = "data/venue_master.json"
X_WHITELIST_STATE_FILE = "data/x_whitelist_state.json"
X_ACCOUNT_SCORES_FILE = "data/x_account_scores.json"
X_EVENT_EVIDENCE_STATE_FILE = "data/x_event_evidence_state.json"
X_EVENT_EVIDENCE_COHORT_FILE = "data/x_event_evidence_cohort.json"
QUEUE_SEEN_FILE = "data/torimochi_queue_seen.json"
QUEUE_STORAGE_MODE = os.environ.get("QUEUE_STORAGE_MODE", "notion").lower()
QUEUE_TYPE_VENUE = "会場"
QUEUE_TYPE_EVENT = "イベント"
QUEUE_TYPES = (QUEUE_TYPE_VENUE, QUEUE_TYPE_EVENT)

# ホーム会場（築地起点・最優先）。会場マスタに無くても確実に拾うための固定リスト。
# X自由文からは「既知会場＋このリスト」との一致だけを拾う（regex自由抽出はニュース限定）。
HOME_VENUES = (
    "築地本願寺", "波除神社", "浜町公園", "鉄砲洲児童公園", "鉄砲洲稲荷神社",
    "月島第二児童公園", "佃公園", "晴海ふ頭公園", "築地社会教育会館",
)

# 盆踊り文脈語（これが無いテキストからは会場抽出しない＝雑音抑制）
_BON_CONTEXT = ("盆踊り", "盆おどり", "納涼", "やぐら", "櫓", "音頭")
# 既知会場に無くても拾う新規会場パターン（○○本願寺/神社/公園 等）
_VENUE_SUFFIX_RE = re.compile(
    r'([一-龥ぁ-んァ-ヶー一-鿐A-Za-z0-9]{2,12}(?:本願寺|八幡宮|神社|稲荷|不動尊|公園|広場|商店街|児童遊園))')
# 単独だと一般名詞すぎて誤検知になる会場名はキューに積まない
_GENERIC_VENUE_BLOCK = {"本願寺", "西本願寺", "神社", "公園", "寺", "会館", "広場", "児童公園", "商店街"}
# 抽出した会場名に文の助詞・記号が残っていたら（=文を巻き込んだ誤抽出）捨てる。
# は/が/を/へ は地名内にほぼ出ないので採用。に/の/と は地名内に出るため除外しない。
_VENUE_REJECT_RE = re.compile(r'[はがをへ、。!！?？「」 　]')

# 「盆踊り」という語が無くても、盆踊り情報として価値が出やすい語。
# ホワイトリスト投稿の採点に使う。キーワード検索そのものを広げすぎると
# ノイズと課金が増えるため、まずはアカウント価値評価に寄せる。
_X_VALUE_KEYWORDS = (
    "音頭", "やぐら", "櫓", "納涼", "夏祭り", "祭り", "まつり", "例大祭",
    "輪踊り", "流し踊り", "踊り", "踊った", "浴衣", "太鼓", "町会", "自治会",
    "商店街", "会場", "開催", "中止", "延期", "日程", "時間", "練習", "稽古",
    "本日", "今日", "明日", "今週", "週末",
)
_X_SCHEDULE_KEYWORDS = (
    "開催", "開催予定", "実施", "予定", "日程", "時間", "会場", "場所",
    "お知らせ", "告知", "ポスター", "チラシ", "申し込み", "申込",
    "雨天", "順延", "延期", "中止", "練習", "稽古", "本日", "今日",
    "明日", "今週", "今週末", "週末", "来週",
)
_X_INFO_RE = re.compile(r'(\d{1,2}[月/]\d{1,2}日?|\d{1,2}:\d{2}|[午前午後]\d{1,2}時|土曜|日曜|雨天|順延|中止|開催)')
_X_MEDIA_HINTS = ("pic.twitter.com", "写真", "画像", "動画", "ポスター", "チラシ")
_X_MD_RE = re.compile(r'(?:(\d{1,2})月(\d{1,2})日?|(\d{1,2})/(\d{1,2}))')


def _clean_regex_venue(name):
    """新規パターン抽出名の前処理。先頭の英字(in等)・ひらがな助詞/接頭句を落とす。"""
    name = re.sub(r'^第?\d+回', '', name).strip()
    name = re.sub(r'^[A-Za-z0-9ぁ-ん]+', '', name).strip()  # 先頭 in/7日/は/に/が… を除去
    return name


def _norm_handle(handle):
    return (handle or "").strip().lstrip("@").lower()


def _voice_datetime(voice):
    date_str = voice.get("date") or ""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except ValueError:
        return None


def _future_date_signal(text, base_dt=None):
    """本文内の日付が base_dt 以降なら未来予定の信号として扱う。"""
    base_dt = base_dt or datetime.now(timezone(timedelta(hours=9)))
    base_date = base_dt.date()
    future_hits = 0
    date_hits = 0
    for m in _X_MD_RE.finditer(text or ""):
        month = int(m.group(1) or m.group(3))
        day = int(m.group(2) or m.group(4))
        try:
            event_date = datetime(base_date.year, month, day).date()
        except ValueError:
            continue
        # 年またぎの告知に備える。90日以上過去に見える日付は翌年扱い。
        if (base_date - event_date).days > 90:
            event_date = datetime(base_date.year + 1, month, day).date()
        date_hits += 1
        if event_date >= base_date:
            future_hits += 1
    relative_future = any(k in (text or "") for k in ("明日", "今週", "今週末", "週末", "来週"))
    today_event = any(k in (text or "") for k in ("本日", "今日")) and any(
        k in (text or "") for k in ("開催", "実施", "あります", "やります")
    )
    return {
        "date_hits": date_hits,
        "future_hits": future_hits,
        "has_future": future_hits > 0 or relative_future or today_event,
        "relative_future": relative_future,
        "today_event": today_event,
    }


def _x_post_value_score(voice, cfg=None, known_venues=None):
    """X投稿1件の情報価値を粗く採点する。

    価値の中心は未来の予定・開催情報。盆踊り語が無い投稿も、
    音頭/櫓/納涼/日付/会場/写真などで拾う。
    画像そのものは見られなくても、写真・ポスター・pic.twitter.com の存在は価値信号にする。
    """
    cfg = cfg or {}
    known_venues = known_venues or {}
    text = (voice.get("text") or "")
    low = text.lower()
    score = 0.0
    reasons = []

    for kw in cfg.get("exclude_keywords", []):
        if kw.lower() in low:
            return -4.0, ["exclude"]

    base_dt = _voice_datetime(voice) or datetime.now(timezone(timedelta(hours=9)))
    schedule = _future_date_signal(text, base_dt)
    schedule_words = any(kw in text for kw in _X_SCHEDULE_KEYWORDS)

    if schedule["has_future"] and schedule_words:
        score += 9
        reasons.append("future_schedule")
    elif schedule_words and _X_INFO_RE.search(text):
        score += 5
        reasons.append("schedule_like")

    if "盆踊り" in text or "盆おどり" in text or "盆踊" in text:
        score += 4
        reasons.append("bon")

    if any(kw in text for kw in _X_VALUE_KEYWORDS):
        score += 3
        reasons.append("context")

    if _X_INFO_RE.search(text):
        score += 3
        reasons.append("date_time")

    if any(h in text for h in _X_MEDIA_HINTS):
        score += 3 if schedule_words else 1
        reasons.append("media_hint")

    matched_venue = next((name for name in known_venues if name and name in text), "")
    if matched_venue:
        score += 5 if known_venues.get(matched_venue) else 3
        reasons.append("venue")

    if any(kw.lower() in low for kw in cfg.get("experience_keywords", [])):
        score += 3
        reasons.append("experience")

    if "http" in low or "t.co/" in low:
        score += 1
        reasons.append("link")

    if score == 0:
        score -= 1
        reasons.append("no_context")

    return score, reasons


def _build_x_account_scores(voices, cfg=None):
    """voices.json などの過去投稿からアカウント価値スコアを作る。"""
    cfg = cfg or {}
    known = _load_known_venues()
    accounts = {}
    for v in voices:
        if v.get("source") not in ("x", "x_whitelist"):
            continue
        handle = _norm_handle(v.get("account"))
        if not handle:
            continue
        row = accounts.setdefault(handle, {
            "handle": f"@{handle}",
            "posts_seen": 0,
            "valuable_posts": 0,
            "noise_posts": 0,
            "value_points": 0.0,
            "last_seen": "",
            "top_reasons": {},
        })
        row["posts_seen"] += 1
        value, reasons = _x_post_value_score(v, cfg, known)
        row["value_points"] += value
        if value >= 4:
            row["valuable_posts"] += 1
        if value < 0:
            row["noise_posts"] += 1
        date = v.get("date") or ""
        if date > row["last_seen"]:
            row["last_seen"] = date
        for r in reasons:
            row["top_reasons"][r] = row["top_reasons"].get(r, 0) + 1

    ranking_cfg = cfg.get("account_ranking", {})
    muted_min_posts = ranking_cfg.get("muted_min_posts", 5)
    muted_max_score = ranking_cfg.get("muted_max_score", 1.5)
    trusted_min_score = ranking_cfg.get("trusted_min_score", 6.0)
    trusted_min_values = ranking_cfg.get("trusted_min_values", 3)

    for row in accounts.values():
        posts = max(row["posts_seen"], 1)
        score = row["value_points"] / posts
        score += min(4.0, row["valuable_posts"] * 0.4)
        score -= min(3.0, row["noise_posts"] * 0.6)
        row["score"] = round(score, 3)
        row["value_ratio"] = round(row["valuable_posts"] / posts, 3)
        if row["posts_seen"] >= muted_min_posts and row["score"] < muted_max_score:
            row["status"] = "muted"
        elif row["score"] >= trusted_min_score and row["valuable_posts"] >= trusted_min_values:
            row["status"] = "trusted"
        elif row["valuable_posts"] > 0:
            row["status"] = "active"
        else:
            row["status"] = "probation"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "accounts": dict(sorted(
            accounts.items(),
            key=lambda kv: (-kv[1].get("score", 0), kv[0])
        )),
    }


def _load_x_account_scores(cfg=None):
    try:
        with open(X_ACCOUNT_SCORES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        pass
    try:
        with open("data/voices.json", "r", encoding="utf-8") as f:
            voices = json.load(f)
        return _build_x_account_scores(voices, cfg)
    except Exception:
        return {"generated_at": "", "accounts": {}}


def _save_x_account_scores(voices, cfg=None):
    try:
        scores = _build_x_account_scores(voices, cfg)
        os.makedirs("data", exist_ok=True)
        with open(X_ACCOUNT_SCORES_FILE, "w", encoding="utf-8") as f:
            json.dump(scores, f, ensure_ascii=False, indent=2)
        stats = scores.get("accounts", {})
        muted = sum(1 for r in stats.values() if r.get("status") == "muted")
        trusted = sum(1 for r in stats.values() if r.get("status") == "trusted")
        print(f"[rank] Xアカウントスコア更新: {len(stats)}件（trusted {trusted} / muted {muted}）")
    except Exception as e:
        print(f"[rank] Xアカウントスコア保存エラー（継続）: {e}")


def _ensure_x_member_score_props():
    """XメンバーリストDBにスコア確認・手動調整用のプロパティを用意する。fail-safe。"""
    if not NOTION_TOKEN:
        return False
    payload = {
        "properties": {
            "収集ステータス": {
                "select": {
                    "options": [
                        {"name": "優先", "color": "green"},
                        {"name": "通常", "color": "blue"},
                        {"name": "休止", "color": "red"},
                    ]
                }
            },
            "手動重み": {"number": {"format": "number"}},
            "自動スコア": {"number": {"format": "number"}},
            "収集ランク": {
                "select": {
                    "options": [
                        {"name": "trusted", "color": "green"},
                        {"name": "active", "color": "blue"},
                        {"name": "probation", "color": "yellow"},
                        {"name": "muted", "color": "red"},
                    ]
                }
            },
            "投稿数": {"number": {"format": "number"}},
            "価値投稿数": {"number": {"format": "number"}},
            "未来予定投稿数": {"number": {"format": "number"}},
            "最終評価日時": {"date": {}},
            "評価理由": {"rich_text": {}},
        }
    }
    try:
        _notion_request("PATCH", f"/databases/{X_MEMBER_LIST_DB_ID}", payload)
        return True
    except Exception as e:
        print(f"[rank] XメンバーリストDBのスコア用プロパティ作成をスキップ: {e}")
        return False


def _update_page_props_best_effort(page_id, props):
    """Notionページプロパティを更新。失敗時だけ1つずつフォールバックする。"""
    try:
        _notion_request("PATCH", f"/pages/{page_id}", {"properties": props})
        return
    except Exception as e:
        print(f"[rank] Notionスコア一括書き戻し失敗、個別更新へフォールバック: {e}")
    for name, value in props.items():
        try:
            _notion_request("PATCH", f"/pages/{page_id}", {"properties": {name: value}})
        except Exception as e:
            print(f"[rank] Notionスコア書き戻しスキップ ({name}): {e}")


def _sync_x_account_scores_to_notion(accounts, cfg=None):
    """XメンバーリストDBへ自動スコアを書き戻す。人間の微調整欄も用意する。"""
    if not NOTION_TOKEN or not accounts:
        return
    cfg = cfg or {}
    _ensure_x_member_score_props()
    scores = _load_x_account_scores(cfg).get("accounts", {})
    now = datetime.now(timezone.utc).isoformat()
    updated = 0
    for account in accounts:
        page_id = account.get("page_id")
        row = scores.get(_norm_handle(account.get("handle")))
        if not page_id or not row:
            continue
        reasons = row.get("top_reasons", {})
        reason_text = ", ".join(f"{k}:{v}" for k, v in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))[:6])
        props = {
            "自動スコア": {"number": row.get("score", 0)},
            "収集ランク": {"select": {"name": row.get("status", "probation")}},
            "投稿数": {"number": row.get("posts_seen", 0)},
            "価値投稿数": {"number": row.get("valuable_posts", 0)},
            "未来予定投稿数": {"number": reasons.get("future_schedule", 0)},
            "最終評価日時": {"date": {"start": now}},
            "評価理由": {"rich_text": [{"text": {"content": reason_text[:1900]}}]},
        }
        _update_page_props_best_effort(page_id, props)
        updated += 1
    print(f"[rank] Notion Xメンバーリストへスコア書き戻し: {updated} 件")


def _rank_whitelist_accounts(accounts, cfg=None):
    """ホワイトリストをアカウント価値順に並べ、低価値アカウントを自動的に休ませる。"""
    cfg = cfg or {}
    ranking_cfg = cfg.get("account_ranking", {})
    if not ranking_cfg.get("enabled", True):
        return [{
            "handle": a["handle"],
            "page_id": a.get("page_id", ""),
            "since": _load_whitelist_since(),
            "reason": "disabled",
        } for a in accounts]

    scores = _load_x_account_scores(cfg).get("accounts", {})
    regular_since = _load_whitelist_since()
    backfill_since = int((datetime.now(timezone.utc) - timedelta(
        days=ranking_cfg.get("backfill_days", 30)
    )).timestamp())
    max_backfill = ranking_cfg.get("max_backfill_accounts_per_run", 8)
    include_muted_probe = ranking_cfg.get("probe_muted_accounts_per_run", 0)

    ranked = []
    muted = []
    unknown_count = 0
    for account in accounts:
        h = account["handle"]
        key = _norm_handle(h)
        row = scores.get(key)
        manual_status = account.get("manual_status", "")
        manual_weight = account.get("manual_weight", 0) or 0
        if not row:
            since = backfill_since if unknown_count < max_backfill else regular_since
            unknown_count += 1
            reason = "manual_priority" if manual_status == "優先" else "unknown"
            if manual_status == "休止":
                muted.append({"handle": h, "page_id": account.get("page_id", ""), "since": regular_since, "reason": "manual_muted", "score": -999})
            else:
                ranked.append({"handle": h, "page_id": account.get("page_id", ""), "since": since, "reason": reason, "score": manual_weight})
            continue
        status = row.get("status")
        score = row.get("score", 0) + manual_weight
        if manual_status == "優先":
            status = "manual_priority"
            score += 100
        elif manual_status == "休止":
            status = "manual_muted"
            score = -999
        item = {"handle": h, "page_id": account.get("page_id", ""), "since": regular_since, "reason": status, "score": score}
        if status in ("muted", "manual_muted"):
            muted.append(item)
        else:
            ranked.append(item)

    ranked.sort(key=lambda x: (
        0 if x["reason"] == "manual_priority" else 1,
        0 if x["reason"] == "trusted" else 1,
        -x.get("score", 0),
        x["handle"].lower()
    ))
    if include_muted_probe:
        muted.sort(key=lambda x: (-x.get("score", 0), x["handle"].lower()))
        ranked.extend(muted[:include_muted_probe])

    skipped = len(muted) - min(len(muted), include_muted_probe)
    if skipped:
        print(f"[rank] 低スコアのためホワイトリスト収集を休止: {skipped} アカウント")
    print(f"[rank] ホワイトリスト収集対象: {len(ranked)} / 元リスト {len(accounts)}")
    return ranked


def _notion_query_database(db_id, payload=None):
    return _notion_request("POST", f"/databases/{db_id}/query", payload or {})


def _prop_plain(prop):
    if not prop:
        return ""
    vals = prop.get("rich_text") or prop.get("title") or []
    return "".join(t.get("plain_text", "") for t in vals).strip()


def _prop_select(prop):
    if not prop:
        return ""
    sel = prop.get("select")
    return sel.get("name", "") if sel else ""


def _prop_number(prop):
    if not prop:
        return None
    return prop.get("number")


def _x_member_handle_from_props(props):
    text = _prop_plain(props.get("アカウント (@)", {}) or {})
    if not text:
        url = (props.get("プロフィールURL", {}) or {}).get("url") or ""
        if "x.com/" in url or "twitter.com/" in url:
            text = url.rstrip("/").split("/")[-1]
    return _norm_handle(text)


def _notion_text_property(prop_type, content):
    value = [{"text": {"content": (content or "")[:1900]}}]
    if prop_type == "title":
        return {"title": value}
    if prop_type == "rich_text":
        return {"rich_text": value}
    return None


def add_promoted_x_members(review_results):
    """投稿レビューでpromoteになった候補をXメンバーリストへ通常メンバーとして追加する。

    既存アカウントは大文字小文字と@の有無を無視して重複排除する。
    既存ページの手動設定は変更しない。Notion未設定時はfail-safeでスキップする。
    """
    promoted = [
        row for row in (review_results or [])
        if row.get("recommendation") == "promote" and _norm_handle(row.get("handle"))
    ]
    summary = {"promoted": len(promoted), "added": 0, "existing": 0, "errors": 0}
    if not promoted:
        print("[review->notion] promote候補なし")
        return summary
    if not NOTION_TOKEN:
        summary["skipped"] = "NOTION_API_TOKEN missing"
        print("[review->notion] NOTION_API_TOKEN 未設定のため追加スキップ")
        return summary

    try:
        _ensure_x_member_score_props()
        database = _notion_request("GET", f"/databases/{X_MEMBER_LIST_DB_ID}")
        schema = database.get("properties", {})
        title_name = next(
            (name for name, prop in schema.items() if prop.get("type") == "title"),
            None,
        )
        if not title_name:
            raise RuntimeError("Xメンバーリストにtitleプロパティがありません")

        existing = set()
        cursor = None
        while True:
            payload = {"page_size": 100}
            if cursor:
                payload["start_cursor"] = cursor
            data = _notion_query_database(X_MEMBER_LIST_DB_ID, payload)
            for page in data.get("results", []):
                handle = _x_member_handle_from_props(page.get("properties", {}))
                if handle:
                    existing.add(handle)
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
    except Exception as e:
        summary["errors"] = len(promoted)
        summary["error"] = str(e)
        print(f"[review->notion] メンバーリスト確認失敗、追加中止: {e}")
        return summary

    now = datetime.now(timezone.utc).isoformat()
    account_schema = schema.get("アカウント (@)", {})
    for row in promoted:
        handle = _norm_handle(row.get("handle"))
        if handle in existing:
            summary["existing"] += 1
            continue

        display_handle = f"@{handle}"
        display_name = (row.get("name") or "").strip()
        title_content = display_handle if title_name == "アカウント (@)" else (display_name or display_handle)
        props = {
            title_name: _notion_text_property("title", title_content),
        }
        if account_schema and title_name != "アカウント (@)":
            account_value = _notion_text_property(account_schema.get("type"), display_handle)
            if account_value:
                props["アカウント (@)"] = account_value
        if schema.get("プロフィールURL", {}).get("type") == "url":
            props["プロフィールURL"] = {"url": f"https://x.com/{handle}"}
        if schema.get("収集ステータス", {}).get("type") == "select":
            props["収集ステータス"] = {"select": {"name": "通常"}}
        if schema.get("自動スコア", {}).get("type") == "number":
            props["自動スコア"] = {"number": row.get("promote_score", 0)}
        if schema.get("収集ランク", {}).get("type") == "select":
            props["収集ランク"] = {"select": {"name": "active"}}
        if schema.get("投稿数", {}).get("type") == "number":
            props["投稿数"] = {"number": row.get("tweets_checked", 0)}
        if schema.get("価値投稿数", {}).get("type") == "number":
            props["価値投稿数"] = {"number": row.get("valuable_posts", 0)}
        if schema.get("未来予定投稿数", {}).get("type") == "number":
            props["未来予定投稿数"] = {"number": row.get("future_schedule_posts", 0)}
        if schema.get("最終評価日時", {}).get("type") == "date":
            props["最終評価日時"] = {"date": {"start": now}}
        if schema.get("評価理由", {}).get("type") == "rich_text":
            reasons = ", ".join(
                f"{key}:{value}" for key, value in sorted(
                    row.get("reason_counts", {}).items(),
                    key=lambda item: (-item[1], item[0]),
                )[:6]
            )
            reason_text = (
                f"候補レビュー自動追加; promote_score:{row.get('promote_score', 0)}; "
                f"{reasons}"
            ).rstrip("; ")
            props["評価理由"] = _notion_text_property("rich_text", reason_text)

        try:
            _notion_request(
                "POST",
                "/pages",
                {"parent": {"database_id": X_MEMBER_LIST_DB_ID}, "properties": props},
            )
            existing.add(handle)
            summary["added"] += 1
            print(f"[review->notion] 収集メンバー追加: {display_handle}")
        except Exception as e:
            summary["errors"] += 1
            print(f"[review->notion] 追加失敗 ({display_handle}): {e}")

    print(
        f"[review->notion] 完了: 追加 {summary['added']} / "
        f"既存 {summary['existing']} / エラー {summary['errors']}"
    )
    return summary


def load_whitelist_accounts():
    """「X メンバーリスト」DB から収集対象アカウントを返す。

    任意プロパティ:
    - 収集ステータス: 優先 / 通常 / 休止
    - 手動重み: number（スコアに加算）
    既存DBに無ければ無視する。
    """
    if not NOTION_TOKEN:
        print("[whitelist] NOTION_API_TOKEN 未設定のためメンバーリスト読込スキップ")
        return []
    accounts = []
    try:
        cursor = None
        while True:
            payload = {"page_size": 100}
            if cursor:
                payload["start_cursor"] = cursor
            data = _notion_query_database(X_MEMBER_LIST_DB_ID, payload)
            for row in data.get("results", []):
                props = row.get("properties", {})
                h = _x_member_handle_from_props(props)
                if h:
                    accounts.append({
                        "handle": h,
                        "page_id": row.get("id", ""),
                        "manual_status": _prop_select(props.get("収集ステータス", {})),
                        "manual_weight": _prop_number(props.get("手動重み", {})) or 0,
                    })
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
    except Exception as e:
        print(f"[whitelist] メンバーリスト読込エラー（スキップ）: {e}")
        return []
    seen, out = set(), []
    for account in accounts:
        k = _norm_handle(account.get("handle"))
        if k not in seen:
            seen.add(k)
            out.append(account)
    print(f"[whitelist] メンバーリスト {len(out)} アカウント取得")
    return out


def _load_whitelist_since():
    """前回実行の since_time(UNIX秒)。無ければ過去3日。"""
    try:
        with open(X_WHITELIST_STATE_FILE, "r", encoding="utf-8") as f:
            return int(json.load(f).get("since_time"))
    except Exception:
        return int((datetime.now(timezone.utc) - timedelta(days=3)).timestamp())


def _save_whitelist_since(ts):
    try:
        os.makedirs("data", exist_ok=True)
        with open(X_WHITELIST_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"since_time": int(ts)}, f)
    except Exception as e:
        print(f"[whitelist] since_time 保存エラー: {e}")


def collect_x_whitelist(seen_urls):
    """A. ホワイトリスト(from:)をバッチ収集（since_timeで新規のみ）。
    戻り値: (new_items, new_seen)。source=x_whitelist / tag ⭐盆踊ラー。
    ノイズ仕分けされても voices には残す（重視ソースのため）。fail-safe。"""
    if not TWITTERAPI_IO_KEY:
        print("[whitelist] TWITTERAPI_IO_KEY 未設定のためスキップ")
        return [], list(seen_urls)
    accounts = load_whitelist_accounts()
    if not accounts:
        print("[whitelist] ホワイトリストが空のためスキップ")
        return [], list(seen_urls)

    cfg = _load_x_config() or {}
    budget = cfg.get("budget", {})
    cost_per_tweet = budget.get("cost_per_tweet_usd", 0.00015)
    daily_cap = budget.get("daily_usd", 0.3)
    monthly_cap = budget.get("monthly_usd", 5.0)

    import time as _time
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    month = today[:7]
    state = _x_budget_state()
    daily_spent = state.get(today, 0.0)
    monthly_spent = sum(v for k, v in state.items() if k.startswith(month))
    if daily_spent >= daily_cap or monthly_spent >= monthly_cap:
        print(f"[whitelist] 予算上限到達のためスキップ（日 ${daily_spent:.4f} 月 ${monthly_spent:.4f}）")
        return [], list(seen_urls)

    batch_size = cfg.get("whitelist_batch_size", 20)
    _sync_x_account_scores_to_notion(accounts, cfg)
    ranked_handles = _rank_whitelist_accounts(accounts, cfg)
    new_items, new_seen, run_cost = [], list(seen_urls), 0.0
    known_venues = _load_known_venues()

    search_batches = []
    current = []
    current_since = None
    for item in ranked_handles:
        if current and (item["since"] != current_since or len(current) >= batch_size):
            search_batches.append(current)
            current = []
        current.append(item)
        current_since = item["since"]
    if current:
        search_batches.append(current)

    for batch_index, batch_items in enumerate(search_batches, start=1):
        if daily_spent + run_cost >= daily_cap or monthly_spent + run_cost >= monthly_cap:
            print("[whitelist] 走行中に予算上限到達。以降のバッチを打ち切り")
            break
        batch = [item["handle"] for item in batch_items]
        since_ts = min(item["since"] for item in batch_items)
        froms = " OR ".join(f"from:{h}" for h in batch)
        query = f"({froms}) since_time:{since_ts}"
        reason_counts = {}
        for item in batch_items:
            reason_counts[item["reason"]] = reason_counts.get(item["reason"], 0) + 1
        print(f"[whitelist] バッチ{batch_index}: {reason_counts} since_time:{since_ts}")
        try:
            data = _x_search(query)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print("[whitelist] 429。5秒待って1回だけ再試行")
                _time.sleep(5)
                try:
                    data = _x_search(query)
                except Exception as e2:
                    print(f"[whitelist] 再試行も失敗、このバッチを飛ばす: {e2}")
                    continue
            else:
                print(f"[whitelist] HTTPエラー {e.code}、このバッチを飛ばす")
                continue
        except Exception as e:
            print(f"[whitelist] 取得エラー、このバッチを飛ばす: {e}")
            continue

        tweets = data.get("tweets") or data.get("data") or []
        run_cost += max(len(tweets), 1) * cost_per_tweet  # 空振りも1件課金
        count = 0
        for tw in tweets:
            v = _x_map_to_voice(tw)
            v["source"] = "x_whitelist"
            if not v["url"] or v["url"] in seen_urls or v["url"] in new_seen:
                continue
            judgement = _score_voice(v["text"], cfg) if cfg else "🟡関心"
            value_score, value_reasons = _x_post_value_score(v, cfg, known_venues)
            tags = ["⭐盆踊ラー", judgement]
            if "future_schedule" in value_reasons:
                tags.insert(1, "📅未来予定")
            elif "schedule_like" in value_reasons:
                tags.insert(1, "📌予定候補")
            v["tags"] = tags
            v["value_score"] = round(value_score, 3)
            _append_x_log_row(v, "q-whitelist", judgement, cost_per_tweet)
            # ホワイトリストでも、盆踊り文脈がほぼ無い日常投稿はログDBだけに残す。
            # 未来予定は強く加点するが、感想・写真・参加レポも配信価値があるので残す。
            if value_score >= cfg.get("account_ranking", {}).get("min_keep_post_score", 0.0):
                new_items.append(v)
            new_seen.append(v["url"])
            count += 1
        print(f"[whitelist] バッチ{batch_index}: {count} 件処理")
        _time.sleep(cfg.get("page_sleep_sec", 2))

    if run_cost > 0:
        state[today] = daily_spent + run_cost
        try:
            os.makedirs("data", exist_ok=True)
            with open(X_BUDGET_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[whitelist] 予算記録の保存エラー: {e}")
    _save_whitelist_since(datetime.now(timezone.utc).timestamp())
    print(f"[whitelist] 完了: {len(new_items)} 件採用、今回コスト 約${run_cost:.5f}")
    return new_items, new_seen


def _load_event_evidence_state():
    try:
        with open(X_EVENT_EVIDENCE_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_event_evidence_state(state):
    os.makedirs("data", exist_ok=True)
    with open(X_EVENT_EVIDENCE_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _clear_pending_event_evidence():
    state = _load_event_evidence_state()
    if state.get("pending_evidence"):
        state["pending_evidence"] = []
        state["pending_cleared_at"] = datetime.now(timezone.utc).isoformat()
        _save_event_evidence_state(state)


def _event_evidence_accounts(accounts, cfg):
    evidence_cfg = cfg.get("event_evidence", {})
    cohort_file = evidence_cfg.get(
        "cohort_file", X_EVENT_EVIDENCE_COHORT_FILE
    )
    try:
        with open(cohort_file, "r", encoding="utf-8") as f:
            cohort = json.load(f)
    except (OSError, json.JSONDecodeError, TypeError):
        cohort = {}
    handles = sorted(set(cohort.get("handles") or []), key=str.casefold)
    expected_count = cohort.get("expected_count")
    if handles and expected_count and len(handles) != int(expected_count):
        raise ValueError(
            f"event evidence cohort count mismatch: "
            f"{len(handles)} != {expected_count}"
        )
    if handles:
        return handles

    min_score = float(evidence_cfg.get("min_account_score", -0.6))
    scores = _load_x_account_scores(cfg).get("accounts", {})
    selected = []
    for account in accounts:
        handle = account.get("handle") or ""
        manual_status = account.get("manual_status") or ""
        if manual_status == "休止":
            continue
        score = scores.get(_norm_handle(handle), {}).get("score")
        if manual_status == "優先" or (score is not None and score >= min_score):
            selected.append(handle)
    return sorted(set(selected), key=str.casefold)


def collect_event_evidence_history():
    """前年同日から2週間分を全対象アカウントで収集する再開可能なパイロット。"""
    cfg = _load_x_config() or {}
    evidence_cfg = cfg.get("event_evidence", {})
    if not evidence_cfg.get("enabled", False):
        return []
    if not TWITTERAPI_IO_KEY:
        print("[evidence] TWITTERAPI_IO_KEY 未設定のためスキップ")
        return []

    accounts = load_whitelist_accounts()
    handles = _event_evidence_accounts(accounts, cfg)
    selection_id = hashlib.sha256(
        "\n".join(handles).encode("utf-8")
    ).hexdigest()
    state = _load_event_evidence_state()
    if state and state.get("selection_id") != selection_id:
        print(
            f"[evidence] 対象コホート変更 "
            f"{len(state.get('selected_handles') or [])}件→{len(handles)}件。"
            "同じ2週間を新コホートで再開始"
        )
        state = {}
    if state.get("status") == "awaiting_review" and evidence_cfg.get("pilot_only", True):
        print("[evidence] 初回2週間パイロット完了済み。評価待ちのため追加収集を停止")
        return []

    if not state:
        if not handles:
            print("[evidence] 対象アカウントなし")
            return []
        start, end = build_initial_window(
            days=int(evidence_cfg.get("initial_window_days", 14))
        )
        state = {
            "status": "in_progress",
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "selected_handles": handles,
            "selection_id": selection_id,
            "batch_index": 0,
            "batch_cursors": {},
            "completed_batches": [],
            "pages_completed": 0,
            "tweets_scanned": 0,
            "evidence_detected": 0,
            "pending_evidence": [],
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        _save_event_evidence_state(state)
    else:
        handles = state.get("selected_handles") or []
        start = datetime.fromisoformat(state["window_start"])
        end = datetime.fromisoformat(state["window_end"])

    batch_size = int(evidence_cfg.get("batch_size", 20))
    max_pages = int(evidence_cfg.get("max_pages_per_run", 40))
    max_evidence = int(evidence_cfg.get("max_evidence_per_run", 300))
    page_sleep = float(cfg.get("page_sleep_sec", 2))
    batches = [
        handles[index:index + batch_size]
        for index in range(0, len(handles), batch_size)
    ]

    budget = cfg.get("budget", {})
    cost_per_tweet = float(budget.get("cost_per_tweet_usd", 0.00015))
    daily_cap = float(budget.get("daily_usd", 0.3))
    monthly_cap = float(budget.get("monthly_usd", 5.0))
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    month = today[:7]
    budget_state = _x_budget_state()
    daily_spent = float(budget_state.get(today, 0))
    monthly_spent = sum(float(value) for key, value in budget_state.items() if key.startswith(month))

    import time as _time
    detected = []
    run_cost = 0.0
    pages = 0
    batch_index = int(state.get("batch_index", 0))
    batch_cursors = state.get("batch_cursors") or {}
    completed_batches = set(state.get("completed_batches") or [])
    while len(completed_batches) < len(batches) and pages < max_pages and len(detected) < max_evidence:
        if daily_spent + run_cost >= daily_cap or monthly_spent + run_cost >= monthly_cap:
            print("[evidence] 予算上限到達。進捗を保存して停止")
            break
        for _ in range(len(batches)):
            if batch_index not in completed_batches:
                break
            batch_index = (batch_index + 1) % len(batches)
        cursor = batch_cursors.get(str(batch_index), "")
        query = build_history_query(batches[batch_index], start, end)
        try:
            data = _x_search(query, cursor)
        except Exception as exc:
            state["last_error"] = str(exc)[:500]
            state["updated_at"] = datetime.now(timezone.utc).isoformat()
            _save_event_evidence_state(state)
            print(f"[evidence] バッチ{batch_index + 1}取得失敗。次回再開: {exc}")
            break

        tweets = data.get("tweets") or data.get("data") or []
        run_cost += max(len(tweets), 1) * cost_per_tweet
        state["tweets_scanned"] = int(state.get("tweets_scanned", 0)) + len(tweets)
        page_evidence = []
        for tweet in tweets:
            voice = _x_map_to_voice(tweet)
            voice["source"] = "x_event_history"
            evidence = classify_event_evidence(voice, cfg)
            if evidence:
                detected.append(evidence)
                page_evidence.append(evidence)

        pages += 1
        state["pages_completed"] = int(state.get("pages_completed", 0)) + 1
        next_cursor = data.get("next_cursor") or data.get("cursor") or ""
        has_next = bool(data.get("has_next_page", bool(next_cursor)) and next_cursor)
        if has_next:
            batch_cursors[str(batch_index)] = next_cursor
        else:
            completed_batches.add(batch_index)
            batch_cursors.pop(str(batch_index), None)
        batch_index = (batch_index + 1) % len(batches)
        state["batch_index"] = batch_index
        state["batch_cursors"] = batch_cursors
        state["completed_batches"] = sorted(completed_batches)
        state["evidence_detected"] = int(state.get("evidence_detected", 0)) + len(page_evidence)
        state.setdefault("pending_evidence", []).extend(page_evidence)
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        _save_event_evidence_state(state)
        if len(completed_batches) < len(batches):
            _time.sleep(page_sleep)

    if run_cost:
        budget_state[today] = daily_spent + run_cost
        with open(X_BUDGET_FILE, "w", encoding="utf-8") as f:
            json.dump(budget_state, f, ensure_ascii=False, indent=2)
    if len(completed_batches) >= len(batches):
        state["status"] = "awaiting_review"
        state["completed_at"] = datetime.now(timezone.utc).isoformat()
        state["covered_until"] = end.isoformat()
        _save_event_evidence_state(state)
    print(
        f"[evidence] 対象 {len(handles)}件 / 完了バッチ {len(completed_batches)}/{len(batches)} / "
        f"今回 {len(detected)}断片 / 約${run_cost:.5f}"
    )
    return state.get("pending_evidence") or detected


def _load_known_venues():
    """venue_master.json から {会場名: in_tsukiji_30min(bool)} を返す。"""
    out = {}
    try:
        with open(VENUE_MASTER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data if isinstance(data, list) else data.get("venues", [])
        for v in items:
            name = (v.get("venue") or "").strip()
            if len(name) >= 3 and name not in _GENERIC_VENUE_BLOCK:
                out[name] = bool(v.get("in_tsukiji_30min"))
    except Exception as e:
        print(f"[queue] 会場マスタ読込エラー（既知会場なしで継続）: {e}")
    # ホーム会場は会場マスタに無くても必ず既知扱い（in_tsukiji_30min=True）
    for hv in HOME_VENUES:
        out[hv] = True
    return out


def detect_venues_for_queue(voices, news_items):
    """B. ホワイトリスト声＋ニュースから会場候補を検出。実行内で会場名dedup。
    戻り: [{venue,url,text,source,priority}]。"""
    known = _load_known_venues()
    found = {}

    def consider(venue, url, text, source, in_range_known=None):
        venue = (venue or "").strip()
        venue = re.sub(r'^第?\d+回', '', venue).strip()  # 「第79回築地本願寺」→「築地本願寺」
        if not venue or venue in _GENERIC_VENUE_BLOCK or venue in found:
            return
        if in_range_known is None:
            in_range_known = known.get(venue)
        priority = "ホーム" if "築地本願寺" in venue else ("近隣" if in_range_known else "通常")
        found[venue] = {"venue": venue, "url": url or "",
                        "text": (text or "")[:300], "source": source, "priority": priority}

    def scan(text, url, source, allow_regex):
        if not text or not any(c in text for c in _BON_CONTEXT):
            return
        # 既知会場マスタ＋ホーム会場との一致（クリーンな会場名）
        for name, in_range in known.items():
            if name in text:
                consider(name, url, text, source, in_range)
        # 新規会場の発見（正規表現）はニュースタイトル限定。
        # X自由文は「○○の築地本願寺」等で文を巻き込むため regex 抽出しない。
        if allow_regex:
            for m in _VENUE_SUFFIX_RE.findall(text):
                cv = _clean_regex_venue(m)
                if len(cv) < 3 or _VENUE_REJECT_RE.search(cv):
                    continue
                consider(cv, url, text, source)

    # 全X声（x_whitelist＋キーワードのx）を走査。告知は「盆踊り」語を含み x で
    # 収集されがちなので x_whitelist 限定にしない（築地本願寺のケース）。
    # ただし X 自由文は既知/ホーム一致のみ（regexなし）で雑音を抑える。
    for v in voices:
        if v.get("source") in ("x_whitelist", "x"):
            scan(v.get("text"), v.get("url"), v.get("source"), allow_regex=False)
    for it in news_items:
        scan(it.get("title"), it.get("url"), "news", allow_regex=True)

    return list(found.values())


def _load_queue_seen():
    """種別ごとの既出候補を読み込む。旧配列形式は会場として扱う。"""
    empty = {candidate_type: set() for candidate_type in QUEUE_TYPES}
    if not os.path.exists(QUEUE_SEEN_FILE):
        return empty
    try:
        with open(QUEUE_SEEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            empty[QUEUE_TYPE_VENUE] = set(data)
            return empty
        if isinstance(data, dict):
            for candidate_type in QUEUE_TYPES:
                values = data.get(candidate_type, [])
                if isinstance(values, list):
                    empty[candidate_type] = set(values)
    except Exception as e:
        print(f"[queue] queue_seen 読み込みエラー（空として継続）: {e}")
    return empty


def _save_queue_seen(seen):
    os.makedirs("data", exist_ok=True)
    serializable = {
        candidate_type: sorted(seen.get(candidate_type, set()))
        for candidate_type in QUEUE_TYPES
    }
    with open(QUEUE_SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)


def _ensure_torimochi_queue_type_property():
    """Notionキューに種別とイベント断片レビュー用プロパティを用意する。"""
    if not NOTION_TOKEN:
        return False
    try:
        database = _notion_request(
            "GET", f"/databases/{TORIMOCHI_QUEUE_DB_ID}"
        )
        def merged_select_options(property_name, additions):
            current = (
                database.get("properties", {})
                .get(property_name, {})
                .get("select", {})
                .get("options", [])
            )
            by_name = {option.get("name"): option for option in current}
            for option in additions:
                by_name.setdefault(option["name"], option)
            return list(by_name.values())

        properties = {
            "種別": {
                "select": {
                    "options": merged_select_options("種別", [
                        {"name": QUEUE_TYPE_VENUE, "color": "blue"},
                        {"name": QUEUE_TYPE_EVENT, "color": "purple"},
                    ])
                }
            },
            "ステータス": {
                "select": {
                    "options": merged_select_options("ステータス", [
                        {"name": "未確認", "color": "gray"},
                        {"name": "関連候補あり", "color": "yellow"},
                        {"name": "確認済み", "color": "green"},
                    ])
                }
            },
            "検知ソース": {
                "select": {
                    "options": merged_select_options("検知ソース", [
                        {"name": "x_event_evidence", "color": "purple"},
                    ])
                }
            },
            "優先度": {
                "select": {
                    "options": merged_select_options("優先度", [
                        {"name": "高", "color": "red"},
                    ])
                }
            },
            "証拠ID": {"rich_text": {}},
            "発言者": {"rich_text": {}},
            "発言日時": {"date": {}},
            "検知パターン": {
                "multi_select": {
                    "options": [
                        {"name": code, "color": color}
                        for code, color in zip(
                            ("A", "B", "C", "D", "E"),
                            ("blue", "yellow", "green", "purple", "orange"),
                        )
                    ]
                }
            },
            "時期ヒント": {"rich_text": {}},
            "場所ヒント": {"rich_text": {}},
            "曲・団体ヒント": {"rich_text": {}},
            "年次信号": {"multi_select": {}},
            "推定イベント名": {"rich_text": {}},
            "推定会場": {"rich_text": {}},
            "関連候補キー": {"rich_text": {}},
            "検知スコア": {"number": {"format": "number"}},
            "スコア根拠": {"rich_text": {}},
            "担当者": {"rich_text": {}},
            "次回確認日": {"date": {}},
            "最終確認日": {"date": {}},
            "会場候補状態": {
                "select": {
                    "options": [
                        {"name": "未検出", "color": "gray"},
                        {"name": "候補", "color": "yellow"},
                        {"name": "既知会場と一致", "color": "green"},
                        {"name": "新規会場・要裏取り", "color": "orange"},
                        {"name": "確認済み", "color": "blue"},
                    ]
                }
            },
        }
        missing = {
            name: definition
            for name, definition in properties.items()
            if name not in database.get("properties", {})
        }
        for select_name in ("種別", "ステータス", "検知ソース", "優先度"):
            current_names = {
                option.get("name")
                for option in (
                    database.get("properties", {})
                    .get(select_name, {})
                    .get("select", {})
                    .get("options", [])
                )
            }
            desired_names = {
                option.get("name")
                for option in properties[select_name]["select"]["options"]
            }
            if not desired_names.issubset(current_names):
                missing[select_name] = properties[select_name]
        if missing:
            _notion_request(
                "PATCH",
                f"/databases/{TORIMOCHI_QUEUE_DB_ID}",
                {"properties": missing},
            )

        cursor = None
        while True:
            payload = {
                "page_size": 100,
                "filter": {"property": "種別", "select": {"is_empty": True}},
            }
            if cursor:
                payload["start_cursor"] = cursor
            data = _notion_query_database(TORIMOCHI_QUEUE_DB_ID, payload)
            for row in data.get("results", []):
                _notion_request(
                    "PATCH",
                    f"/pages/{row['id']}",
                    {
                        "properties": {
                            "種別": {
                                "select": {"name": QUEUE_TYPE_VENUE}
                            }
                        }
                    },
                )
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return True
    except Exception as e:
        print(f"[queue] 種別プロパティ準備エラー（追記をスキップ）: {e}")
        return False


def _notion_rich_text_value(value):
    if isinstance(value, (list, tuple)):
        value = " / ".join(str(item) for item in value if item)
    value = str(value or "")
    return {"rich_text": [{"text": {"content": value[:1900]}}]} if value else {"rich_text": []}


def _event_evidence_notion_props(evidence):
    props = {
        "証拠ID": _notion_rich_text_value(evidence.get("identity")),
        "発言者": _notion_rich_text_value(evidence.get("account")),
        "検知パターン": {
            "multi_select": [{"name": value} for value in evidence.get("patterns", [])]
        },
        "時期ヒント": _notion_rich_text_value(evidence.get("time_hints")),
        "場所ヒント": _notion_rich_text_value(
            (evidence.get("place_hints") or []) + (evidence.get("venue_hints") or [])
        ),
        "曲・団体ヒント": _notion_rich_text_value(
            (evidence.get("song_hints") or []) + (evidence.get("group_hints") or [])
        ),
        "年次信号": {
            "multi_select": [{"name": value} for value in evidence.get("year_signals", [])]
        },
        "推定イベント名": _notion_rich_text_value(evidence.get("estimated_event")),
        "推定会場": _notion_rich_text_value(evidence.get("estimated_venue")),
        "関連候補キー": _notion_rich_text_value(evidence.get("related_key")),
        "検知スコア": {"number": evidence.get("score", 0)},
        "スコア根拠": _notion_rich_text_value(evidence.get("score_reasons")),
        "会場候補状態": {
            "select": {
                "name": "候補" if evidence.get("estimated_venue") else "未検出"
            }
        },
    }
    spoken_at = evidence.get("spoken_at")
    if spoken_at:
        try:
            datetime.fromisoformat(spoken_at.replace("Z", "+00:00"))
            props["発言日時"] = {"date": {"start": spoken_at}}
        except ValueError:
            pass
    return props


def push_torimochi_queue(detected):
    """検出会場を裏取りキューへ追記。既出はスキップ。fail-safe。"""
    use_notion = QUEUE_STORAGE_MODE in ("notion", "dual")
    use_dynamodb = QUEUE_STORAGE_MODE in ("dynamodb", "dual")
    if use_notion and not NOTION_TOKEN:
        print("[queue] NOTION_API_TOKEN 未設定のため裏取りキュー追記スキップ")
        return {"added": 0, "failed": len(detected), "skipped": 0}
    if use_dynamodb and not os.environ.get("DYNAMODB_QUEUE_TABLE"):
        print("[queue] DYNAMODB_QUEUE_TABLE 未設定のため裏取りキュー追記スキップ")
        return {"added": 0, "failed": len(detected), "skipped": 0}
    if not detected:
        print("[queue] 検出会場なし")
        return {"added": 0, "failed": 0, "skipped": 0}
    if use_notion and not _ensure_torimochi_queue_type_property():
        return {"added": 0, "failed": len(detected), "skipped": 0}
    dynamodb = DynamoQueueStore() if use_dynamodb else None
    seen = _load_queue_seen()
    today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    added = 0
    failed = 0
    skipped = 0
    for d in detected:
        candidate_type = d.get("type") or QUEUE_TYPE_VENUE
        if candidate_type not in QUEUE_TYPES:
            print(f"[queue] 未対応の種別をスキップ: {candidate_type}")
            continue
        key = d.get("identity") or d["venue"]
        if key in seen[candidate_type]:
            skipped += 1
            continue
        if dynamodb:
            created = dynamodb.add_candidate(d)
            if not created:
                if (
                    not use_notion
                    or dynamodb.is_notion_synced(key, candidate_type)
                ):
                    seen[candidate_type].add(key)
                    skipped += 1
                    continue
        props = {
            "会場名": {"title": [{"text": {"content": d["venue"][:200]}}]},
            "種別": {"select": {"name": candidate_type}},
            "ステータス": {
                "select": {"name": d.get("status") or "要裏取り"}
            },
            "検知ソース": {"select": {"name": d["source"]}},
            "優先度": {"select": {"name": d["priority"]}},
            "検知元本文": {"rich_text": [{"text": {"content": d["text"][:1900]}}]},
            "検知日": {"date": {"start": today}},
        }
        if d["url"]:
            props["検知元URL"] = {"url": d["url"]}
        if candidate_type == QUEUE_TYPE_EVENT:
            props.update(_event_evidence_notion_props(d))
        try:
            if use_notion:
                _notion_request(
                    "POST",
                    "/pages",
                    {"parent": {"database_id": TORIMOCHI_QUEUE_DB_ID}, "properties": props},
                )
                if dynamodb:
                    dynamodb.mark_notion_synced(key, candidate_type)
            seen[candidate_type].add(key)
            added += 1
        except Exception as e:
            failed += 1
            print(f"[queue] 追記エラー（{key}・継続）: {e}")
    if added:
        try:
            _save_queue_seen(seen)
        except Exception as e:
            print(f"[queue] queue_seen 保存エラー: {e}")
    print(
        f"[queue] 裏取りキューに {added} 件追加"
        f"（保存先 {QUEUE_STORAGE_MODE}・既出スキップ・検出 {len(detected)} 件）"
    )
    return {"added": added, "failed": failed, "skipped": skipped}


def archive_resolved_queue():
    """掃除ループ: ステータス『該当なし』の行をアーカイブ（ゴミ箱へ）。
    こわが誤検知と判断した行を自動で片付ける。queue_seen からは消さない
    （= 再検知で蒸し返さない）。fail-safe。"""
    if not NOTION_TOKEN:
        return
    archived = 0
    dynamodb = None
    if (
        QUEUE_STORAGE_MODE == "dual"
        and os.environ.get("DYNAMODB_QUEUE_TABLE")
    ):
        dynamodb = DynamoQueueStore()
    try:
        cursor = None
        while True:
            payload = {"page_size": 100,
                       "filter": {"property": "ステータス", "select": {"equals": "該当なし"}}}
            if cursor:
                payload["start_cursor"] = cursor
            data = _notion_query_database(TORIMOCHI_QUEUE_DB_ID, payload)
            for row in data.get("results", []):
                try:
                    if dynamodb:
                        title_items = (
                            row.get("properties", {})
                            .get("会場名", {})
                            .get("title", [])
                        )
                        venue = "".join(
                            item.get("plain_text", "") for item in title_items
                        ).strip()
                        candidate_type = _prop_select(
                            row.get("properties", {}).get("種別")
                        ) or QUEUE_TYPE_VENUE
                        identity = _prop_plain(
                            row.get("properties", {}).get("証拠ID")
                        ) or venue
                        if identity:
                            try:
                                dynamodb.update_status(
                                    identity, "該当なし", candidate_type
                                )
                            except Exception as e:
                                print(
                                    f"[queue] DynamoDB状態同期スキップ"
                                    f"（{venue}）: {e}"
                                )
                    _notion_request("PATCH", f"/pages/{row['id']}", {"archived": True})
                    archived += 1
                except Exception as e:
                    print(f"[queue] 該当なしアーカイブ失敗（継続）: {e}")
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
    except Exception as e:
        print(f"[queue] 掃除ループ・クエリエラー（スキップ）: {e}")
        return
    print(f"[queue] 掃除ループ: 該当なし {archived} 件をアーカイブ")


# --- 用語集（表記ゆれ管理）---
# 会場名・イベント名の表記ゆれを Notion「📖 盆踊ラー用語集」DB で一元管理する。
# 確度「公式確認」「複数一致」エントリを自動マッチングに使い、「推察」は候補として蓄積。
# ことが新しい表記ゆれを検知したら register_glossary_alias() で推察登録する。
# 内田さんが Notion 上で確度を昇格させると次の収集から自動マッチングに反映される。

def load_glossary():
    """用語集DBからエントリを読み込む。
    戻り値: (alias_map, confident_set)
    - alias_map: {表記ゆれ: 正規名称} （全確度）
    - confident_set: 「公式確認」「複数一致」の正規名称セット（自動マッチング用）
    fail-safe: 取得失敗時は空で返す。
    """
    if not NOTION_TOKEN or not GLOSSARY_DB_ID:
        return {}, set()
    try:
        alias_map = {}
        confident_set = set()
        cursor = None
        while True:
            payload = {"page_size": 100}
            if cursor:
                payload["start_cursor"] = cursor
            data = _notion_query_database(GLOSSARY_DB_ID, payload)
            for row in data.get("results", []):
                props = row.get("properties", {})
                canonical = _prop_plain(props.get("正規名称", {}))
                if not canonical:
                    continue
                confidence = _prop_select(props.get("確度", {}))
                aliases_raw = _prop_plain(props.get("表記ゆれ", {}))
                aliases = [a.strip() for a in aliases_raw.split(",") if a.strip()] if aliases_raw else []
                alias_map[canonical] = canonical
                for alias in aliases:
                    if alias:
                        alias_map[alias] = canonical
                if confidence in ("公式確認", "複数一致"):
                    confident_set.add(canonical)
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        print(f"[glossary] {len(alias_map)} エントリ読込（正規名称 {len(confident_set)} 件が高確度）")
        return alias_map, confident_set
    except Exception as e:
        print(f"[glossary] 読込エラー（スキップ）: {e}")
        return {}, set()


def register_glossary_alias(alias, canonical, source_url="", confidence="推察"):
    """新出表記ゆれを用語集DBに登録/追記する。fail-safe。
    既存の正規名称エントリがあれば表記ゆれ列に追記。なければ新規作成。
    """
    if not NOTION_TOKEN or not GLOSSARY_DB_ID:
        return
    alias = alias.strip()
    canonical = canonical.strip()
    if not alias or not canonical or alias == canonical:
        return
    try:
        data = _notion_query_database(GLOSSARY_DB_ID, {
            "filter": {"property": "正規名称", "title": {"equals": canonical}}
        })
        rows = data.get("results", [])
        if rows:
            page_id = rows[0]["id"]
            existing_raw = _prop_plain(rows[0].get("properties", {}).get("表記ゆれ", {})) or ""
            existing_set = set(a.strip() for a in existing_raw.split(",") if a.strip())
            if alias in existing_set:
                return
            existing_set.add(alias)
            _notion_request("PATCH", f"/pages/{page_id}", {
                "properties": {
                    "表記ゆれ": {"rich_text": [{"text": {"content": ", ".join(sorted(existing_set))[:1900]}}]}
                }
            })
        else:
            props = {
                "正規名称": {"title": [{"text": {"content": canonical[:200]}}]},
                "表記ゆれ": {"rich_text": [{"text": {"content": alias[:1900]}}]},
                "種別": {"select": {"name": "会場名"}},
                "確度": {"select": {"name": confidence}},
            }
            if source_url:
                props["出典"] = {"url": source_url}
            _notion_request("POST", "/pages",
                            {"parent": {"database_id": GLOSSARY_DB_ID}, "properties": props})
        print(f"[glossary] 追記: 「{alias}」→「{canonical}」（{confidence}）")
    except Exception as e:
        print(f"[glossary] 追記エラー（スキップ）: {e}")


def normalize_venue_name(name, alias_map):
    """会場名を用語集で正規名称に変換。マッチしなければそのまま返す。"""
    return alias_map.get(name, name)


def bootstrap_glossary_if_empty(venue_master):
    """用語集DBが空の場合、会場マスタの会場名を正規名称として初期投入する。
    一度だけ動けば良い処理（2回目以降は entries > 0 でスキップ）。
    """
    if not NOTION_TOKEN or not GLOSSARY_DB_ID:
        return
    try:
        check = _notion_query_database(GLOSSARY_DB_ID, {"page_size": 1})
        if check.get("results"):
            return
        print("[glossary] 用語集が空です。会場マスタから初期投入します…")
        for v in venue_master:
            name = (v.get("venue") or "").strip()
            if not name or len(name) < 2:
                continue
            props = {
                "正規名称": {"title": [{"text": {"content": name[:200]}}]},
                "種別": {"select": {"name": "会場名"}},
                "確度": {"select": {"name": "複数一致"}},
            }
            source_url = v.get("source_url") or v.get("notion_url") or ""
            if source_url:
                props["出典"] = {"url": source_url}
            try:
                _notion_request("POST", "/pages",
                                {"parent": {"database_id": GLOSSARY_DB_ID}, "properties": props})
            except Exception as e:
                print(f"[glossary] 初期投入スキップ ({name}): {e}")
        print(f"[glossary] 初期投入完了: {len(venue_master)} 件")
    except Exception as e:
        print(f"[glossary] 初期投入エラー（スキップ）: {e}")


# --- 速報・確度シグナル検知 ---

_CONFIRM_KEYWORDS = (
    "開催決定", "開催確定", "開催します", "開催予定です", "今年も開催",
    "チラシ", "ポスター", "受付開始", "告知", "日程決定", "日程確定",
    "開催情報", "日程が決まり", "日程が出",
)
_CANCEL_KEYWORDS = re.compile(r'(中止|延期|雨天中止|台風のため|残念ながら中止|開催中止)')


def detect_x_confidence_signals(whitelist_voices, known_venues, alias_map):
    """ホワイトリスト声から既存会場への確度変化シグナルを検知。
    戻り: [{"venue": 正規名称, "signal": "confirm"|"cancel", "text", "url", "account"}]
    ノイズ抑制: ⭐盆踊ラーソース限定 + 盆踊り文脈語必須。
    """
    signals = []
    seen_keys = set()
    for v in whitelist_voices:
        if v.get("source") != "x_whitelist":
            continue
        text = v.get("text") or ""
        if not any(c in text for c in _BON_CONTEXT):
            continue
        url = v.get("url") or ""
        account = v.get("account") or ""
        for raw_name in known_venues:
            if raw_name not in text:
                continue
            canonical = normalize_venue_name(raw_name, alias_map)
            key = f"{canonical}::{url}"
            if key in seen_keys:
                continue
            if any(kw in text for kw in _CONFIRM_KEYWORDS):
                signal = "confirm"
            elif _CANCEL_KEYWORDS.search(text):
                signal = "cancel"
            else:
                continue
            seen_keys.add(key)
            signals.append({
                "venue": canonical,
                "signal": signal,
                "text": text[:200].replace("\n", " "),
                "url": url,
                "account": account,
            })
    return signals


def detect_sokuho(whitelist_voices, known_venues, alias_map):
    """ホワイトリスト声から「未知イベント速報」候補を検出。
    条件: 📅未来予定タグ + 会場マスタに無い会場名らしき語 + value_score >= 7。
    戻り: [{"venue", "text", "url", "account", "value_score"}]
    """
    candidates = []
    seen_venues = set()
    for v in whitelist_voices:
        if v.get("source") != "x_whitelist":
            continue
        tags = v.get("tags") or []
        if "📅未来予定" not in tags:
            continue
        value_score = v.get("value_score", 0)
        if value_score < 7:
            continue
        text = v.get("text") or ""
        if not any(c in text for c in _BON_CONTEXT):
            continue
        # 既知会場への言及があれば速報でなく確度シグナル扱いなのでスキップ
        if any(name in text for name in known_venues):
            continue
        # 新規会場名らしき語を正規表現で抽出
        for m in _VENUE_SUFFIX_RE.findall(text):
            cv = _clean_regex_venue(m)
            if len(cv) < 3 or _VENUE_REJECT_RE.search(cv) or cv in _GENERIC_VENUE_BLOCK:
                continue
            canonical = normalize_venue_name(cv, alias_map)
            if canonical in seen_venues:
                continue
            seen_venues.add(canonical)
            candidates.append({
                "venue": canonical,
                "text": text[:200].replace("\n", " "),
                "url": v.get("url") or "",
                "account": v.get("account") or "",
                "value_score": value_score,
            })
    return candidates


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
    venue_master_raw = []
    proactive_targets = []
    proactive_config = {}
    proactive_report = []

    try:
        with open(VENUE_MASTER_FILE, "r", encoding="utf-8") as f:
            vm = json.load(f)
        venue_master_raw = vm if isinstance(vm, list) else vm.get("venues", [])
        all_targets, proactive_config = load_targets(venue_master_raw)
        lead_months = int(proactive_config.get("lead_months", 1))
        proactive_targets = select_due_targets(
            all_targets, lead_months=lead_months
        )[:int(proactive_config.get("max_targets_per_run", 12))]
        print(
            f"[proactive] 定番イベント {len(all_targets)} 件中、"
            f"今月から{lead_months}か月先まで {len(proactive_targets)} 件を確認"
        )
    except Exception as exc:
        print(f"[proactive] 設定読み込み失敗（スキップ）: {exc}")

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

    # --- 定番イベントの能動ニュース検索（fail-safe）---
    current_year = datetime.now(timezone(timedelta(hours=9))).year
    for target in proactive_targets:
        try:
            query = build_queries(target, current_year)["news"]
            items = parse_rss(fetch_news(query))
            added = 0
            for item in items:
                if not is_target_confirmation(item, target, current_year):
                    continue
                if item["url"] in seen_in_run:
                    continue
                seen_in_run.add(item["url"])
                latest_items.append({
                    "source": "news_proactive",
                    "target_venue": target["venue"],
                    "title": item["title"],
                    "url": item["url"],
                    "date": item["pubDate"],
                    "is_home": False,
                })
                if item["url"] not in seen_urls:
                    new_urls.append(item["url"])
                added += 1
            print(f"[proactive/news] {target['venue']}: {added} 件追加")
        except Exception as exc:
            print(f"[proactive/news] {target['venue']} 検索失敗: {exc}")

    os.makedirs('data', exist_ok=True)

    with open('data/latest.json', 'w', encoding='utf-8') as f:
        json.dump(latest_items, f, ensure_ascii=False, indent=2)

    with open(seen_file, 'w', encoding='utf-8') as f:
        json.dump(new_urls, f, ensure_ascii=False, indent=2)

    print(f"完了: 全 {len(latest_items)} 件を記録しました。")

    # --- voices 収集（fail-safe: 失敗してもニュース収集結果に影響しない）---
    deduped_voices = []  # Notion へ X由来の言葉を載せるため、try の外で確実に定義
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

        # 定番イベントを会場名＋年で能動検索（fail-safe）
        try:
            proactive_x, updated_voices_seen = collect_proactive_x(
                proactive_targets,
                set(updated_voices_seen),
                proactive_config,
            )
            voice_items = proactive_x + voice_items
        except Exception as e:
            print(f"[proactive/x] 予期せぬエラー（他収集には影響なし）: {e}")

        # A. ホワイトリスト（X メンバーリスト）収集。⭐盆踊ラーを最優先ソースとして追加（fail-safe）
        try:
            wl_items, updated_voices_seen = collect_x_whitelist(set(updated_voices_seen))
            voice_items = wl_items + voice_items  # 盆踊ラーを先頭に
        except Exception as e:
            print(f"[whitelist] 予期せぬエラー（他収集には影響なし）: {e}")

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

        _save_x_account_scores(deduped_voices, _load_x_config() or {})

        print(f"[voices] 完了: 新規 {len(voice_items)} 件、累計 {len(deduped_voices)} 件")
    except Exception as e:
        print(f"[voices] 予期せぬエラー（ニュース収集には影響なし）: {e}")

    # --- イベント断片の履歴パイロット → 裏取りキュー ---
    try:
        event_evidence = collect_event_evidence_history()
        queue_result = push_torimochi_queue(event_evidence)
        if event_evidence and queue_result.get("failed", 0) == 0:
            _clear_pending_event_evidence()
    except Exception as e:
        print(f"[evidence] 予期せぬエラー（他処理には影響なし）: {e}")

    # --- B. 会場検知 → 裏取りキュー（fail-safe: 失敗しても他処理に影響しない）---
    try:
        detected = detect_venues_for_queue(deduped_voices, latest_items)
        for candidate in detected:
            candidate["type"] = QUEUE_TYPE_VENUE
        push_torimochi_queue(detected)
        # 掃除ループ: こわが『該当なし』にした行を自動アーカイブ
        archive_resolved_queue()
    except Exception as e:
        print(f"[queue] 予期せぬエラー（他処理には影響なし）: {e}")

    # --- 用語集・速報・確度シグナル検知（fail-safe）---
    sokuho_list = []
    event_signal_list = []
    try:
        # 会場マスタの初期投入（用語集が空の場合のみ実行）
        bootstrap_glossary_if_empty(venue_master_raw)

        glossary_map, confident_set = load_glossary()
        known = _load_known_venues()
        wl_voices = [v for v in deduped_voices if v.get("source") == "x_whitelist"]
        if wl_voices:
            event_signal_list = detect_x_confidence_signals(wl_voices, known, glossary_map)
            sokuho_list = detect_sokuho(wl_voices, known, glossary_map)
            if event_signal_list:
                print(f"[signals] イベント確度変化シグナル {len(event_signal_list)} 件")
            if sokuho_list:
                print(f"[sokuho] 速報候補 {len(sokuho_list)} 件")
    except Exception as e:
        print(f"[sokuho/signals] 予期せぬエラー（他処理には影響なし）: {e}")

    # --- 定番イベントの公式情報源確認・抜け漏れレポート（fail-safe）---
    try:
        official_evidence = []
        for target in proactive_targets:
            official_evidence.extend(
                check_official_sources(target, current_year)
            )
        proactive_report = build_report(
            proactive_targets,
            latest_items + deduped_voices + official_evidence,
            current_year,
        )
        with open(
            "data/proactive_event_report.json", "w", encoding="utf-8"
        ) as f:
            json.dump({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "year": current_year,
                "items": proactive_report,
            }, f, ensure_ascii=False, indent=2)
        unconfirmed = sum(
            1 for item in proactive_report
            if item["status"] == "unconfirmed"
        )
        print(
            f"[proactive/report] 対象 {len(proactive_report)} 件、"
            f"未確認 {unconfirmed} 件"
        )
    except Exception as e:
        print(f"[proactive/report] 作成失敗（スキップ）: {e}")

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

    # X由来の「人の言葉」を直近7日で抽出して配信ネタとしてNotionへ載せる
    # （⭐盆踊ラー→🟢一次レポを優先。deduped_voices は新規が先頭）
    x_voices_all = [
        v for v in deduped_voices
        if v.get("source") in ("x", "x_whitelist")
        and (_parse_date(v.get("date")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
    ]
    x_voices_recent = sorted(
        x_voices_all,
        key=lambda v: (
            0 if any("盆踊ラー" in t for t in (v.get("tags") or [])) else 1,
            0 if any("一次レポ" in t for t in (v.get("tags") or [])) else 1,
        ),
    )[:15]

    # X収集コストの見える化（x_budget.json の日次消費を集計）
    x_cost = None
    try:
        today_str = datetime.now(jst).strftime("%Y-%m-%d")
        month_prefix = today_str[:7]  # YYYY-MM
        budget_state = {}
        if os.path.exists('data/x_budget.json'):
            with open('data/x_budget.json', 'r', encoding='utf-8') as f:
                budget_state = json.load(f)
        month_total = sum(v for k, v in budget_state.items() if k.startswith(month_prefix))
        caps = {}
        if os.path.exists('x_queries.json'):
            with open('x_queries.json', 'r', encoding='utf-8') as f:
                caps = json.load(f).get('budget', {})
        x_cost = {
            "today": budget_state.get(today_str, 0.0),
            "month": month_total,
            "daily_cap": caps.get("daily_usd", 0.0),
            "monthly_cap": caps.get("monthly_usd", 0.0),
        }
    except Exception as e:
        print(f"[cost] コスト集計エラー（表示スキップ）: {e}")

    push_to_notion(recent_items if recent_items else latest_items[:30], updated_at,
                   x_voices_recent, x_cost, sokuho_list, event_signal_list,
                   proactive_report)

if __name__ == '__main__':
    main()
