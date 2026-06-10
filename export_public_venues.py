"""Notion「🏮 会場マスタ」＋「🎆 イベントDB」から、Web一般公開サイト用の
会場データ（東京23区）をエクスポートするスクリプト。

内部運用フィールド（築地30分圏内・過去メモ・要レビュー・Notion URL）は出力しない。
例年開催月は会場マスタには無く、イベントDB側（例年開催月 rich_text / 開催日 date）に
あるため、会場 relation で join して月を導出する。

- 標準ライブラリのみ（collect.py の fail-safe 方針を踏襲）
- 出力:
  - data/public/venues_public.json … 正本（サイト・アプリ共通の元データ）
  - data/public/venues_public.js   … Claude Design の VENUES 配列に貼る用
                                                    — こと（Claude Code）2026-06-10
"""

import json
import os
import re
import urllib.error
import urllib.request

import notion_config

NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")
API = notion_config.NOTION_API_BASE
API_VERSION = notion_config.NOTION_API_VERSION

OUT_DIR = os.path.join(os.path.dirname(__file__), "data", "public")
OUT_JSON = os.path.join(OUT_DIR, "venues_public.json")
OUT_JS = os.path.join(OUT_DIR, "venues_public.js")

# 東京23区（公開サイトの対象範囲）。表示順もこの順に固定する。
TOKYO_WARDS = (
    "千代田区", "中央区", "港区", "新宿区", "文京区", "台東区", "墨田区",
    "江東区", "品川区", "目黒区", "大田区", "世田谷区", "渋谷区", "中野区",
    "杉並区", "豊島区", "北区", "荒川区", "板橋区", "練馬区", "足立区",
    "葛飾区", "江戸川区",
)
WARD_ORDER = {w: i for i, w in enumerate(TOKYO_WARDS)}

MONTH_RE = re.compile(r"(\d{1,2})月")
# 過去メモ中の「8/16」「8/16-17」のような月/日表記（「2025/8/16」の年部分は拾わない）
MONTH_DAY_RE = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?!\d*/)")


def _notion_request(method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {NOTION_TOKEN}")
    req.add_header("Notion-Version", API_VERSION)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())


def _query_all(data_source_id):
    """Data Source の全行を返す（ページネーション対応）。"""
    rows = []
    cursor = None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        res = _notion_request("POST", f"/data_sources/{data_source_id}/query", payload)
        rows.extend(res.get("results", []))
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    return rows


def _plain(rich):
    return "".join(part.get("plain_text", "") for part in (rich or []))


def _prop(props, name):
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
    if t == "date":
        return (p.get("date") or {}).get("start")
    if t == "url":
        return p.get("url") or None
    if t == "relation":
        return [item.get("id") for item in p.get("relation", [])]
    return None


def normalize_ward(region):
    """所在区・市の表記から23区名を取り出す。23区外なら None。

    会場マスタの実データには「東京都」抜きの区名・他県の市区町村・地区名が
    混在しているため、「○○区」が23区名と一致するものだけを東京とみなす
    （extract_venues.py の TOKYO_WARDS と同じ考え方）。
    「神戸市東灘区」のような政令市の区を誤って拾わないよう、区名の前に
    市・郡・県名が付くものは除外する。
    """
    if not region:
        return None
    region = region.replace("東京都", "")
    for ward in TOKYO_WARDS:
        if region == ward:
            return ward
        # 「北区王子」のような後置の地名は許容、「大阪市北区」は不可
        if region.startswith(ward):
            return ward
    return None


def months_from_memo(memo):
    """過去メモの自由文から開催月を推定する（イベントDBに月が無い会場の補完用）。"""
    if not memo:
        return set()
    months = {int(m) for m in MONTH_RE.findall(memo) if 1 <= int(m) <= 12}
    for m, d in MONTH_DAY_RE.findall(memo):
        if 1 <= int(m) <= 12 and 1 <= int(d) <= 31:
            months.add(int(m))
    return months


def fetch_venue_months():
    """イベントDBから venue_page_id -> set(月) の対応を作る。"""
    months_by_venue = {}
    for row in _query_all(notion_config.EVENT_DATA_SOURCE_ID):
        props = row.get("properties", {})
        months = set()
        for text in (_prop(props, "例年開催月") or "",):
            months.update(int(m) for m in MONTH_RE.findall(text) if 1 <= int(m) <= 12)
        start = _prop(props, "開催日")
        if start:
            months.add(int(start[5:7]))
        if not months:
            continue
        for venue_id in _prop(props, "会場") or []:
            months_by_venue.setdefault(venue_id, set()).update(months)
    return months_by_venue


def build_public_venues():
    months_by_venue = fetch_venue_months()
    included, excluded, no_month, dup_check = [], [], [], {}

    for row in _query_all(notion_config.VENUE_DATA_SOURCE_ID):
        props = row.get("properties", {})
        name = _prop(props, "会場名")
        region = _prop(props, "所在区・市")
        if not name:
            continue
        ward = normalize_ward(region)
        if not ward:
            excluded.append(f"{name}（{region or '所在不明'}）")
            continue

        months = sorted(months_by_venue.get(row["id"], ()))
        if not months:
            # イベントDBに月情報が無い会場は、過去メモの日付表記から推定する
            months = sorted(months_from_memo(_prop(props, "過去メモ")))
        if not months:
            no_month.append(name)
        scale = _prop(props, "規模")
        entry = {
            "name": name,
            "area": ward,
            "months": months,
            "scale": scale if scale in ("大", "中", "小") else None,
            "access": _prop(props, "アクセス"),
            "address": _prop(props, "住所"),
        }
        included.append(entry)
        dup_check.setdefault(name, 0)
        dup_check[name] += 1

    included.sort(key=lambda v: (WARD_ORDER[v["area"]], v["name"]))
    dups = [n for n, c in dup_check.items() if c > 1]
    return included, excluded, no_month, dups


def write_outputs(venues):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(venues, f, ensure_ascii=False, indent=2)

    # Claude Design 側の VENUES 配列（name/area/month/scale/access）に合わせた形。
    # month はカード表示用の文字列（複数月は「7月・8月」）。
    site_rows = []
    for v in venues:
        site_rows.append({
            "name": v["name"],
            "area": v["area"],
            "month": "・".join(f"{m}月" for m in v["months"]) or "時期未確認",
            "scale": v["scale"] or "規模未確認",
            "access": v["access"] or "",
        })
    with open(OUT_JS, "w", encoding="utf-8") as f:
        f.write("const VENUES = ")
        f.write(json.dumps(site_rows, ensure_ascii=False, indent=2))
        f.write(";\n")


def main():
    if not NOTION_TOKEN:
        print("Notion未設定 (NOTION_API_TOKEN) のため公開用エクスポートをスキップ")
        return
    try:
        venues, excluded, no_month, dups = build_public_venues()
    except urllib.error.HTTPError as e:
        print(f"公開用エクスポート失敗 (HTTP {e.code})：DB共有を確認。スキップ")
        return

    write_outputs(venues)
    print(f"公開用エクスポート完了: {len(venues)} 件（23区） → {OUT_JSON}")
    print(f"月情報あり: {len(venues) - len(no_month)} 件 / 月不明: {len(no_month)} 件")
    print(f"23区外として除外: {len(excluded)} 件")
    for line in excluded:
        print(f"  - {line}")
    if dups:
        print(f"⚠️ 同名会場の重複: {dups}")


if __name__ == "__main__":
    main()
