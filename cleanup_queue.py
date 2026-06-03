"""🔎 裏取りキュー DB の全行をアーカイブ（ゴミ箱へ）する使い捨てクリーンアップ。
状態ファイル永続化漏れ時代に溜まった重複＋誤抽出のテストゴミを一掃するため。
GitHub Actions 上で NOTION_API_TOKEN を使って実行する。冪等・fail-safe。
"""
import os
import json
import urllib.request

NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")
NOTION_VERSION = "2022-06-28"
NOTION_API = "https://api.notion.com/v1"
QUEUE_DB_ID = os.environ.get("TORIMOCHI_QUEUE_DB_ID", "f560afee832f4b1084d6e6093d74da16")


def _req(method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{NOTION_API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {NOTION_TOKEN}")
    req.add_header("Notion-Version", NOTION_VERSION)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def main():
    if not NOTION_TOKEN:
        print("NOTION_API_TOKEN 未設定。中止。")
        return
    archived = 0
    cursor = None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        data = _req("POST", f"/databases/{QUEUE_DB_ID}/query", payload)
        results = data.get("results", [])
        for row in results:
            pid = row.get("id")
            try:
                _req("PATCH", f"/pages/{pid}", {"archived": True})
                archived += 1
            except Exception as e:
                print(f"アーカイブ失敗 {pid}: {e}")
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    print(f"アーカイブ完了: {archived} 行")


if __name__ == "__main__":
    main()
