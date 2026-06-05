import os
import re
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


def _rich_text(content, link=None):
    out = []
    for c in _chunk_text(content):
        t = {"content": c}
        if link:
            t["link"] = {"url": link}
        out.append({"type": "text", "text": t})
    return out


def push_to_notion(latest_items, updated_at, x_voices=None, x_cost=None):
    """Notion ページの内容を最新データで全面更新する。

    x_voices: X由来の「人の言葉」（一次レポ/関心、直近分）。配信担当(こわ)が
    同じページを読むだけでX情報を配信に組み込めるよう、専用セクションに載せる。
    x_cost: {"today": 今日のX収集コスト$, "month": 今月累計$, "daily_cap": 日上限$,
            "monthly_cap": 月上限$}。デイリーのコスト見える化用。
    """
    x_voices = x_voices or []
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


# --- ホワイトリスト収集 / 会場検知→裏取りキュー（2段構え）---
# 仕様: 盆踊り情報開発 >「🔎 盆踊ラー起点・会場裏取り 2段構え（仕様）」
# A. 既存「X メンバーリスト」DB の from: をバッチ収集（since_time で新規のみ）→ ⭐盆踊ラー最優先
# B. 盆踊ラー声＋ニュースから会場名を検知 →「🔎 裏取りキュー」DB へ（裏取りはこわ）。既出は再投入しない。

X_MEMBER_LIST_DB_ID = os.environ.get("X_MEMBER_LIST_DB_ID", "5c585224465241548b631e4e5d316f3b")
TORIMOCHI_QUEUE_DB_ID = os.environ.get("TORIMOCHI_QUEUE_DB_ID", "f560afee832f4b1084d6e6093d74da16")
VENUE_MASTER_FILE = "data/venue_master.json"
X_WHITELIST_STATE_FILE = "data/x_whitelist_state.json"
QUEUE_SEEN_FILE = "data/torimochi_queue_seen.json"

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


def _clean_regex_venue(name):
    """新規パターン抽出名の前処理。先頭の英字(in等)・ひらがな助詞/接頭句を落とす。"""
    name = re.sub(r'^第?\d+回', '', name).strip()
    name = re.sub(r'^[A-Za-z0-9ぁ-ん]+', '', name).strip()  # 先頭 in/7日/は/に/が… を除去
    return name


def _notion_query_database(db_id, payload=None):
    return _notion_request("POST", f"/databases/{db_id}/query", payload or {})


def load_whitelist_handles():
    """「X メンバーリスト」DB から @ハンドル一覧（@抜き）を返す。失敗時 []（fail-safe）。"""
    if not NOTION_TOKEN:
        print("[whitelist] NOTION_API_TOKEN 未設定のためメンバーリスト読込スキップ")
        return []
    handles = []
    try:
        cursor = None
        while True:
            payload = {"page_size": 100}
            if cursor:
                payload["start_cursor"] = cursor
            data = _notion_query_database(X_MEMBER_LIST_DB_ID, payload)
            for row in data.get("results", []):
                props = row.get("properties", {})
                acc = props.get("アカウント (@)", {}) or {}
                rich = acc.get("rich_text") or acc.get("title") or []
                text = "".join(t.get("plain_text", "") for t in rich).strip()
                if not text:
                    url = (props.get("プロフィールURL", {}) or {}).get("url") or ""
                    if "x.com/" in url or "twitter.com/" in url:
                        text = url.rstrip("/").split("/")[-1]
                h = text.lstrip("@").strip()
                if h:
                    handles.append(h)
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
    except Exception as e:
        print(f"[whitelist] メンバーリスト読込エラー（スキップ）: {e}")
        return []
    seen, out = set(), []
    for h in handles:
        k = h.lower()
        if k not in seen:
            seen.add(k)
            out.append(h)
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
    handles = load_whitelist_handles()
    if not handles:
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

    since_ts = _load_whitelist_since()
    batch_size = cfg.get("whitelist_batch_size", 20)
    new_items, new_seen, run_cost = [], list(seen_urls), 0.0

    for i in range(0, len(handles), batch_size):
        if daily_spent + run_cost >= daily_cap or monthly_spent + run_cost >= monthly_cap:
            print("[whitelist] 走行中に予算上限到達。以降のバッチを打ち切り")
            break
        batch = handles[i:i + batch_size]
        froms = " OR ".join(f"from:{h}" for h in batch)
        query = f"({froms}) since_time:{since_ts}"
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
            v["tags"] = ["⭐盆踊ラー", judgement]
            _append_x_log_row(v, "q-whitelist", judgement, cost_per_tweet)
            new_items.append(v)  # ホワイトリストはノイズでも保持
            new_seen.append(v["url"])
            count += 1
        print(f"[whitelist] バッチ{i // batch_size + 1}: {count} 件採用")
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


def push_torimochi_queue(detected):
    """検出会場を「🔎 裏取りキュー」DB へ追記。既出(queue_seen)はスキップ。fail-safe。"""
    if not NOTION_TOKEN:
        print("[queue] NOTION_API_TOKEN 未設定のため裏取りキュー追記スキップ")
        return
    if not detected:
        print("[queue] 検出会場なし")
        return
    seen = set()
    if os.path.exists(QUEUE_SEEN_FILE):
        try:
            with open(QUEUE_SEEN_FILE, "r", encoding="utf-8") as f:
                seen = set(json.load(f))
        except Exception:
            pass
    today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    added = 0
    for d in detected:
        key = d["venue"]
        if key in seen:
            continue
        props = {
            "会場名": {"title": [{"text": {"content": d["venue"][:200]}}]},
            "ステータス": {"select": {"name": "要裏取り"}},
            "検知ソース": {"select": {"name": d["source"]}},
            "優先度": {"select": {"name": d["priority"]}},
            "検知元本文": {"rich_text": [{"text": {"content": d["text"][:1900]}}]},
            "検知日": {"date": {"start": today}},
        }
        if d["url"]:
            props["検知元URL"] = {"url": d["url"]}
        try:
            _notion_request("POST", "/pages",
                            {"parent": {"database_id": TORIMOCHI_QUEUE_DB_ID}, "properties": props})
            seen.add(key)
            added += 1
        except Exception as e:
            print(f"[queue] 追記エラー（{key}・継続）: {e}")
    if added:
        try:
            os.makedirs("data", exist_ok=True)
            with open(QUEUE_SEEN_FILE, "w", encoding="utf-8") as f:
                json.dump(sorted(seen), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[queue] queue_seen 保存エラー: {e}")
    print(f"[queue] 裏取りキューに {added} 件追加（既出スキップ・検出 {len(detected)} 件）")


def archive_resolved_queue():
    """掃除ループ: ステータス『該当なし』の行をアーカイブ（ゴミ箱へ）。
    こわが誤検知と判断した行を自動で片付ける。queue_seen からは消さない
    （= 再検知で蒸し返さない）。fail-safe。"""
    if not NOTION_TOKEN:
        return
    archived = 0
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

        print(f"[voices] 完了: 新規 {len(voice_items)} 件、累計 {len(deduped_voices)} 件")
    except Exception as e:
        print(f"[voices] 予期せぬエラー（ニュース収集には影響なし）: {e}")

    # --- B. 会場検知 → 裏取りキュー（fail-safe: 失敗しても他処理に影響しない）---
    try:
        detected = detect_venues_for_queue(deduped_voices, latest_items)
        push_torimochi_queue(detected)
        # 掃除ループ: こわが『該当なし』にした行を自動アーカイブ
        archive_resolved_queue()
    except Exception as e:
        print(f"[queue] 予期せぬエラー（他処理には影響なし）: {e}")

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

    push_to_notion(recent_items if recent_items else latest_items[:30], updated_at, x_voices_recent, x_cost)

if __name__ == '__main__':
    main()
