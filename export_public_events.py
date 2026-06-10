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
import re
import urllib.error
import urllib.request

import notion_config
from export_public_venues import (
    MONTH_DAY_RE,
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

# 日付未確定イベントの「並び位置」を決めるヒント（内田さん指示 2026-06-10）：
# 旬がわかれば 上旬≒5日 / 中旬≒15日 / 下旬≒25日、それも無ければ昨年実績の
# 月日、最後は月のみ（≒15日）で近似する。
JUN_DAY = {"上旬": 5, "中旬": 15, "下旬": 25, "初": 3, "末": 27}
MONTH_JUN_RE = re.compile(r"(\d{1,2})月(上旬|中旬|下旬|末|初)?")
ISO_DATE_RE = re.compile(r"\d{4}-(\d{1,2})-(\d{1,2})")
# 編集署名・確認日（「（2026-06-10 こと）」「こと2026-06-10追記」「おと（Codex）2026-06-09」）。
# 実イベントの日付と誤認して並び順を壊すため、ヒント抽出前に取り除く。
SIGNATURE_RE = re.compile(
    r"（\d{4}-\d{1,2}-\d{1,2}[^）]*）"
    r"|(?:こと|おと)（?[A-Za-z]*）?\s*\d{4}-\d{1,2}-\d{1,2}(?:追記|時点)?")


def parse_months(text):
    return {int(m) for m in MONTH_RE.findall(text or "") if 1 <= int(m) <= 12}


def hints_from_text(text):
    """テキストから {月: (日, 優先度)} を抽出。旬(1) > 具体日(2) > 月のみ(3)。"""
    text = SIGNATURE_RE.sub(" ", text or "")
    out = {}

    def put(m, d, rank):
        if 1 <= m <= 12 and 1 <= d <= 31 and (m not in out or rank < out[m][1]):
            out[m] = (d, rank)

    for m, jun in MONTH_JUN_RE.findall(text or ""):
        m = int(m)
        if jun:
            put(m, JUN_DAY[jun], 1)
        else:
            put(m, 15, 3)
    for mo, d in ISO_DATE_RE.findall(text or ""):
        put(int(mo), int(d), 2)
    for mo, d in MONTH_DAY_RE.findall(text or ""):
        put(int(mo), int(d), 2)
    return out


def jun_labels(text):
    """例年開催月テキストから {月: 旬ラベル} を抜く（カード表示用）。"""
    out = {}
    for m, jun in MONTH_JUN_RE.findall(text or ""):
        m = int(m)
        if jun in ("上旬", "中旬", "下旬") and 1 <= m <= 12 and m not in out:
            out[m] = jun
    return out


def merge_hints(*hint_dicts, months=()):
    """複数ソースのヒントを優先度で統合し、months の不足分は15日で補う。"""
    merged = {}
    for hints in hint_dicts:
        for m, (d, rank) in hints.items():
            if m not in merged or rank < merged[m][1]:
                merged[m] = (d, rank)
    for m in months:
        merged.setdefault(m, (15, 4))
    return sorted([m, d] for m, (d, _) in merged.items())


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
        memo = _prop(props, "過去メモ")
        venues[row["id"]] = {
            "venue": clean_public_text(name),
            "area": ward,
            "scale": scale if scale in ("大", "中", "小") else None,
            "access": clean_public_text(_prop(props, "アクセス")),
            "address": clean_public_text(_prop(props, "住所")),
            "memo_months": sorted(months_from_memo(memo)),
            "memo_hints": hints_from_text(memo),
            "memo_jun": jun_labels(memo),
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
        month_text = _prop(props, "例年開催月")
        detail_text = _prop(props, "開催パターン詳細")
        months = parse_months(month_text)
        date_obj = props.get("開催日", {}).get("date") or {}
        date = date_obj.get("start")
        date_end = date_obj.get("end")
        if date:
            months.add(int(date[5:7]))
        status = _prop(props, "状態")
        hints = merge_hints(
            hints_from_text(month_text), hints_from_text(detail_text),
            months=months)
        jun = jun_labels(month_text)
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
                "date_end": date_end,
                "status": status,
                # 並び順用の近似月日 [[月, 日], ...] と、表示用の旬ラベル {月: 旬}
                "hints": hints,
                "jun": {str(m): j for m, j in jun.items()},
                # カードに出す特徴文（公開用に書いたものだけ。内部メモは出さない）
                "description": clean_public_text(_prop(props, "公開紹介文")),
                # 詳細モーダル用：直近の開催実績（日時の記録）
                "detail": clean_public_text(detail_text),
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
            "date_end": None,
            "status": None,
            "hints": merge_hints(v["memo_hints"], months=v["memo_months"]),
            "jun": {str(m): j for m, j in v["memo_jun"].items()},
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
