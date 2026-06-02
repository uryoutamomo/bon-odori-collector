"""
[実証用・使い捨て] X(Twitter) からの「人の言葉」収集テスト

目的: twitterapi.io 経由で盆踊りの参加者の声がどれだけ・どんな質で取れるかを $0〜少額で確認する。
本番(collect.py)には未統合。質が確認できてから collect_x_voices() として組み込む。

使い方:
    export TWITTERAPI_IO_KEY="自分のキー"
    python3 experiment_x_voices.py

設計:
    - fail-safe: 失敗しても例外で落とさず、何が起きたか表示する
    - 安く試す: 1クエリ最大2ページ(=最大40件)に制限。プリペイド残高を無駄遣いしない
    - レスポンス構造が不明なので、最初の1件は生キーを表示して後でマッピングを微調整できるようにする
"""
import os
import json
import urllib.request
import urllib.parse

API_BASE = "https://api.twitterapi.io/twitter/tweet/advanced_search"
API_KEY = os.environ.get("TWITTERAPI_IO_KEY")

# 「人の言葉」を狙うクエリ案。ニュースbot/RTを除き、個人の感想に寄せる。
QUERIES = [
    "盆踊り lang:ja -filter:retweets -filter:links",          # 個人のつぶやき寄り(リンク無し)
    "盆踊り (楽しかった OR 踊った OR 行ってきた) lang:ja -filter:retweets",  # 体験語に寄せる
]

MAX_PAGES_PER_QUERY = 2   # 1ページ20件 → クエリあたり最大40件で打ち止め(コスト抑制)


def _get(query, cursor=""):
    params = {"query": query, "queryType": "Latest"}
    if cursor:
        params["cursor"] = cursor
    url = f"{API_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"X-API-Key": API_KEY})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _map_to_voice(tw):
    """twitterapi.io のツイートを voices スキーマに best-effort で変換。
    フィールド名が違ってもなるべく拾えるよう複数候補を見る。"""
    author = tw.get("author") or tw.get("user") or {}
    username = author.get("userName") or author.get("screen_name") or ""
    name = author.get("name") or ""
    tw_id = tw.get("id") or tw.get("id_str") or ""
    url = tw.get("url") or (f"https://x.com/{username}/status/{tw_id}" if username and tw_id else "")
    return {
        "source": "x",
        "account": f"@{username}" if username else "",
        "name": name,
        "title": "",
        "text": (tw.get("text") or tw.get("full_text") or "").strip()[:500],
        "url": url,
        "date": tw.get("createdAt") or tw.get("created_at") or "",
        "tags": [],
    }


def run():
    if not API_KEY:
        print("[!] 環境変数 TWITTERAPI_IO_KEY が未設定です。")
        print('    export TWITTERAPI_IO_KEY="あなたのキー" を実行してから再度走らせてください。')
        return

    all_voices = []
    seen_urls = set()
    raw_dumped = False

    for q in QUERIES:
        print(f"\n=== クエリ: {q} ===")
        cursor = ""
        got = 0
        for page in range(MAX_PAGES_PER_QUERY):
            try:
                data = _get(q, cursor)
            except Exception as e:
                print(f"  [エラー] {e}")
                break

            # 初回のみレスポンス構造を確認用にダンプ
            if not raw_dumped:
                print(f"  [debug] レスポンスの top-level keys: {list(data.keys())}")

            tweets = data.get("tweets") or data.get("data") or []
            if not raw_dumped and tweets:
                print(f"  [debug] ツイート1件目の keys: {list(tweets[0].keys())}")
                raw_dumped = True

            if not tweets:
                print("  (このページは0件)")
                break

            for tw in tweets:
                v = _map_to_voice(tw)
                if not v["url"] or v["url"] in seen_urls:
                    continue
                seen_urls.add(v["url"])
                all_voices.append(v)
                got += 1

            cursor = data.get("next_cursor") or data.get("cursor") or ""
            has_next = data.get("has_next_page", bool(cursor))
            if not has_next or not cursor:
                break

        print(f"  → このクエリで {got} 件取得")

    print(f"\n========== 合計 {len(all_voices)} 件（重複除去後）==========\n")
    for i, v in enumerate(all_voices[:15], 1):
        print(f"[{i}] {v['account']} / {v['date']}")
        print(f"    {v['text'][:120]}")
        print(f"    {v['url']}")
        print()

    out = "data/x_voices_experiment.json"
    os.makedirs("data", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(all_voices, f, ensure_ascii=False, indent=2)
    print(f"全件を {out} に保存しました。質を確認してください。")


if __name__ == "__main__":
    run()
