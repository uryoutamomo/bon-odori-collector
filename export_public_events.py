"""Notion「🎆 イベントDB」＋「🏮 会場マスタ」から、Web一般公開サイト用の
イベント一覧（東京23区）をエクスポートするスクリプト。

公開サイトのメインカードは会場ではなく**イベント名**（内田さん指示 2026-06-10）。
- イベントDBの各行（東京23区の会場に紐づくもの）を1カードとして出力
- イベントが未整備の公開会場は「○○の盆踊り」のフォールバックカードを出力
  （name_confirmed=false。イベント登録が進むと自動的に置き換わる）

23区判定・区名正規化・文字化け置換・内部フィールド除去は
export_public_venues.py と同じ方針。出力は data/public/events_public.json。
                                                    — こと（Claude Code）2026-06-10
"""

import json
import os
import urllib.error
import urllib.request

import notion_config
from export_public_venues import (
    MONTH_RE,
    clean_public_text,
    months_from_memo,
    normalize_ward,
    WARD_ORDER,
    _notion_request,  # noqa: F401  (同一API利用)
    _prop,
    _query_all,
)

OUT_DIR = os.path.join(os.path.dirname(__file__), "data", "public")
OUT_JSON = os.path.join(OUT_DIR, "events_public.json")


def parse_months(text):
    return {int(m) for m in MONTH_RE.findall(text or "") if 1 <= int(m) <= 12}


def fetch_public_venues():
    """23区の公開対象会場を venue_page_id -> dict で返す。"""
    venues = {}
    for row in _query_all(notion_config.VENUE_DATA_SOURCE_ID):
        props = row.get("properties", {})
        name = _prop(props, "会場名")
        ward = normalize_ward(_prop(props, "所在区・市"))
        if not name or not ward:
            continue
        scale = _prop(props, "規模")
        venues[row["id"]] = {
            "venue": clean_public_text(name),
            "area": ward,
            "scale": scale if scale in ("大", "中", "小") else None,
            "access": clean_public_text(_prop(props, "アクセス")),
            "address": clean_public_text(_prop(props, "住所")),
            "memo_months": sorted(months_from_memo(_prop(props, "過去メモ"))),
            "intro": clean_public_text(_prop(props, "公開紹介文")),
        }
    return venues


def build_public_events():
    venues = fetch_public_venues()
    events, covered, skipped = [], set(), 0

    for row in _query_all(notion_config.EVENT_DATA_SOURCE_ID):
        props = row.get("properties", {})
        name = _prop(props, "イベント名")
        venue_ids = [v for v in (_prop(props, "会場") or []) if v in venues]
        if not name or not venue_ids:
            skipped += 1
            continue
        months = parse_months(_prop(props, "例年開催月"))
        date = _prop(props, "開催日")
        if date:
            months.add(int(date[5:7]))
        status = _prop(props, "状態")
        for vid in venue_ids:
            v = venues[vid]
            covered.add(vid)
            events.append({
                "name": clean_public_text(name),
                "name_confirmed": True,
                "venue": v["venue"],
                "area": v["area"],
                "months": sorted(months) or v["memo_months"],
                "scale": v["scale"],
                "access": v["access"],
                "address": v["address"],
                "date": date,
                "status": status,
                # カードに出す特徴文（公開用に書いたものだけ。内部メモは出さない）
                "description": clean_public_text(_prop(props, "公開紹介文")),
                # 詳細モーダル用：直近の開催実績（日時の記録）
                "detail": clean_public_text(_prop(props, "開催パターン詳細")),
            })

    # イベント未整備の会場はフォールバックカード（名称確認中）
    fallback = 0
    for vid, v in venues.items():
        if vid in covered:
            continue
        fallback += 1
        events.append({
            "name": f"{v['venue']}の盆踊り",
            "name_confirmed": False,
            "venue": v["venue"],
            "area": v["area"],
            "months": v["memo_months"],
            "scale": v["scale"],
            "access": v["access"],
            "address": v["address"],
            "date": None,
            "status": None,
            "description": v["intro"],
            "detail": None,
        })

    events.sort(key=lambda e: (WARD_ORDER[e["area"]], e["venue"], e["name"]))
    return events, len(covered), fallback, skipped


def main():
    if not os.environ.get("NOTION_API_TOKEN"):
        print("Notion未設定 (NOTION_API_TOKEN) のためイベント公開エクスポートをスキップ")
        return
    try:
        events, covered, fallback, skipped = build_public_events()
    except urllib.error.HTTPError as e:
        print(f"イベント公開エクスポート失敗 (HTTP {e.code})。スキップ")
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False, indent=2)

    named = sum(1 for e in events if e["name_confirmed"])
    no_month = sum(1 for e in events if not e["months"])
    print(f"イベント公開エクスポート完了: {len(events)} 件 → {OUT_JSON}")
    print(f"  イベント名あり: {named} 件（{covered} 会場）/ 名称確認中フォールバック: {fallback} 件")
    print(f"  月情報なし: {no_month} 件 / 23区外・会場なしで除外したイベント: {skipped} 件")


if __name__ == "__main__":
    main()
