"""
方向案B：Notion「🏮 会場マスタ」DB を Single Source of Truth とし、
その内容を data/venue_master.json にエクスポートするスクリプト。

collector（GitHub Actions）や home-venue-watch が、Notion を直接叩かずに
このローカル JSON を参照できるようにするための連携（こわ作成のDB → こと側の参照口）。

- 標準ライブラリのみ（collect.py の fail-safe 方針を踏襲）
- トークン未設定・DB未共有・取得失敗時は既存 JSON を壊さずスキップして終了
                                                    — こと（Claude Code）2026-05-31

【前提・要対応】GitHub Actions から読むには、Notion インテグレーション
`bon-odori-collector` が「🏮 会場マスタ」DB に共有されている必要がある（CLAUDE.md 参照）。
未共有だと 404/権限エラーになるので、その場合はスキップする。
"""

import json
import os
import re
import urllib.request
import urllib.error

import notion_config

NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")
NOTION_VERSION = "2022-06-28"
NOTION_API = "https://api.notion.com/v1"

MONTH_RE = re.compile(r"(\d{1,2})月")

# 🏮 会場マスタ DB（こわが 2026-05-31 に作成）
VENUE_DB_ID = os.environ.get("VENUE_DB_ID", "cbc56bda225946bf8aacadb7efd691c2")
OUT = os.path.join(os.path.dirname(__file__), "data", "venue_master.json")


def _notion_request(method, path, payload=None, version=NOTION_VERSION):
    url = f"{NOTION_API}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {NOTION_TOKEN}")
    req.add_header("Notion-Version", version)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())


def _plain(rich):
    """rich_text / title 配列を素のテキストに連結。"""
    return "".join(part.get("plain_text", "") for part in (rich or []))


def _prop(props, name):
    """プロパティ値を型に応じて取り出す。未設定は None / False。"""
    p = props.get(name)
    if not p:
        return None
    t = p.get("type")
    if t == "title":
        return _plain(p["title"]) or None
    if t == "rich_text":
        return _plain(p["rich_text"]) or None
    if t == "select":
        return p["select"]["name"] if p.get("select") else None
    if t == "multi_select":
        values = [item.get("name") for item in p.get("multi_select", [])]
        return [value for value in values if value]
    if t == "number":
        return p.get("number")
    if t == "formula":
        formula = p.get("formula") or {}
        return formula.get(formula.get("type"))
    if t == "rollup":
        rollup = p.get("rollup") or {}
        if rollup.get("type") == "array":
            values = []
            for item in rollup.get("array", []):
                item_type = item.get("type")
                if item_type in ("number", "string"):
                    values.append(item.get(item_type))
                elif item_type == "select" and item.get("select"):
                    values.append(item["select"].get("name"))
            return [value for value in values if value is not None]
        return rollup.get(rollup.get("type"))
    if t == "checkbox":
        return bool(p.get("checkbox"))
    if t == "date":
        return (p.get("date") or {}).get("start")
    if t == "url":
        return p.get("url") or None
    return None


def fetch_event_months():
    """イベントDBから venue_page_id -> 例年開催月（"7月,8月" 形式）の対応を作る。

    2026-06-06 のDB分割で「例年開催月」は会場マスタからイベントDBへ移った。
    会場 relation 経由で join し、collection_support/proactive_search.py が読める文字列にして返す。
    """
    months_by_venue = {}
    cursor = None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        res = _notion_request(
            "POST",
            f"/data_sources/{notion_config.EVENT_DATA_SOURCE_ID}/query",
            payload,
            version=notion_config.NOTION_API_VERSION,
        )
        for row in res.get("results", []):
            props = row.get("properties", {})
            months = {
                int(m) for m in MONTH_RE.findall(_prop(props, "例年開催月") or "")
                if 1 <= int(m) <= 12
            }
            start = _prop(props, "開催日")
            if isinstance(start, str) and len(start) >= 7:
                months.add(int(start[5:7]))
            if not months:
                continue
            for venue_id in props.get("会場", {}).get("relation", []):
                months_by_venue.setdefault(venue_id["id"], set()).update(months)
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    return {
        vid: ",".join(f"{m}月" for m in sorted(months))
        for vid, months in months_by_venue.items()
    }


def fetch_venues():
    """会場マスタDBの全ページを取得して dict のリストで返す（ページネーション対応）。"""
    month_by_venue = fetch_event_months()
    venues = []
    cursor = None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        res = _notion_request("POST", f"/databases/{VENUE_DB_ID}/query", payload)
        for row in res.get("results", []):
            props = row.get("properties", {})
            venues.append({
                "venue": _prop(props, "会場名"),
                "region": _prop(props, "所在区・市"),
                "month": month_by_venue.get(row.get("id")),
                "scale": _prop(props, "規模"),
                "access": _prop(props, "アクセス"),
                "in_tsukiji_30min": _prop(props, "築地30分圏内"),
                "source_url": _prop(props, "出典URL"),
                "memo": _prop(props, "過去メモ"),
                "needs_review": _prop(props, "要レビュー"),
                "notion_url": row.get("url"),
            })
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    return venues


def main():
    if not NOTION_TOKEN:
        print("Notion未設定 (NOTION_API_TOKEN) のため会場マスタ同期をスキップ")
        return
    try:
        venues = fetch_venues()
    except urllib.error.HTTPError as e:
        # 404/403 = DBがインテグレーションに未共有の可能性。既存JSONは保持。
        print(f"会場マスタ取得失敗 (HTTP {e.code})：DBが bon-odori-collector に共有されているか確認。スキップ")
        return
    except Exception as e:
        print(f"会場マスタ取得失敗：{e}。スキップ")
        return

    venues.sort(key=lambda v: (not v.get("in_tsukiji_30min"), v.get("venue") or ""))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(venues, f, ensure_ascii=False, indent=2)

    in_range = sum(1 for v in venues if v.get("in_tsukiji_30min"))
    print(f"会場マスタ同期完了: {len(venues)} 件（築地30分圏内: {in_range} 件）→ {OUT}")


if __name__ == "__main__":
    main()
