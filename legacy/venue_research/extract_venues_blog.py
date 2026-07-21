"""
方向案B（圏内拡充）：東京盆踊りマップ（minato-bon-odori.blogspot.com）の
「○○区の盆おどり情報」ページ本文から、築地30分圏内の会場名を抽出する。

latest.json はタイトルしか保持しないため圏内会場が拾えなかった（診断済み）。
このスクリプトは blogspot のデフォルトフィードを直接取得し、近接区ページの
本文（予定日/会場/住所…の表）から会場名を抽出して data/venues_seed_blog.json に出力する。

ベストエフォート（要・人手レビュー）。標準ライブラリのみ。
                                                    — こと（Claude Code）2026-05-31
"""

import html
import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET

FEED_URL = "http://minato-bon-odori.blogspot.com/feeds/posts/default?max-results=50"
OUT = os.path.join(os.path.dirname(__file__), "data", "venues_seed_blog.json")
ATOM = {"a": "http://www.w3.org/2005/Atom"}

# 築地（中央区）起点・自転車30分圏内とみなす区（in_tsukiji_30min_guess の推定用）
NEAR_TSUKIJI = [
    "中央区", "港区", "千代田区", "台東区", "墨田区", "江東区",
    "品川区", "文京区", "新宿区", "渋谷区", "目黒区", "荒川区",
]

# 処理対象は東京23区すべて（2026-06-10 Web公開向けに築地30分圏から拡大）
TOKYO_WARDS = NEAR_TSUKIJI + [
    "大田区", "世田谷区", "中野区", "杉並区", "豊島区", "北区",
    "板橋区", "練馬区", "足立区", "葛飾区", "江戸川区",
]

# blogspot 本文に出る会場接尾辞（長いものを優先）
VENUE_SUFFIXES = [
    "社会教育会館", "区民センター", "区民会館", "市民会館", "児童遊園",
    "小学校", "中学校", "公民館", "区民館", "文化会館", "コミュニティ会館",
    "神社", "公園", "広場", "会館", "団地", "河川敷", "商店街", "寺", "学校",
]
NAME_CHARS = r"[一-龥ぁ-んァ-ヶー々〆A-Za-z0-9・]"
GENERIC = {"小学校", "中学校", "公園", "神社", "広場", "会場", "会館", "寺",
           "学校", "公民館", "区民館", "児童遊園", "開放的な公園"}
CLAUSE_MARKERS = ("して", "から", "という", "ました", "られ", "ている", "下さい",
                  "ください", "問い合わせ", "掲載依頼")


def _clean(name):
    name = name.strip(" 　「」『』【】()（）<>《》、。!！?？#＃-—:：・|")
    while True:
        new = re.sub(r"^(第?\s*\d+\s*回|20\d{2}年?|\d{1,2}[/月]\d{0,2}日?|"
                     r"\[[A-Za-z0-9]+\]|[はがをにでのとへやも]|[\s　]+)",
                     "", name).strip()
        if new == name:
            break
        name = new
    name = re.sub(r"^([一-龥]{1,4}?区)", "", name).strip()  # 先頭の区名を除去
    return name


def _looks_like_venue(name):
    if not name or len(name) < 3 or len(name) > 16:
        return False
    if name in GENERIC:
        return False
    if any(m in name for m in CLAUSE_MARKERS):
        return False
    return any(name.endswith(s) for s in VENUE_SUFFIXES)


def extract_venues(body):
    suffix_alt = "|".join(sorted(VENUE_SUFFIXES, key=len, reverse=True))
    found = []
    for m in re.finditer(NAME_CHARS + r"{1,14}?(?:" + suffix_alt + r")", body):
        c = _clean(m.group(0))
        if _looks_like_venue(c):
            found.append(c)
    return list(dict.fromkeys(found))  # 出現順で重複排除


def main():
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": "Mozilla/5.0"})
    try:
        xml = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    except Exception as e:
        print(f"フィード取得失敗：{e}。スキップ")
        return
    root = ET.fromstring(xml)

    venues = {}
    for entry in root.findall("a:entry", ATOM):
        t = entry.find("a:title", ATOM)
        c = entry.find("a:content", ATOM)
        title = (t.text or "") if t is not None else ""
        ward = next((w for w in TOKYO_WARDS if w in title), None)
        if not ward or "情報" not in title:
            continue
        body = html.unescape(re.sub("<[^>]+>", " ", (c.text or ""))) if c is not None else ""
        body = re.sub(r"\s+", " ", body)
        for venue in extract_venues(body):
            if venue not in venues:
                venues[venue] = {
                    "venue": venue,
                    "region_hint": ward,
                    "in_tsukiji_30min_guess": ward in NEAR_TSUKIJI[:7],  # 中核7区は True
                    "source": "blogspot",
                    "source_title": title[:120],
                    "method": "blog_body",
                    "needs_review": True,
                }

    seed = sorted(venues.values(),
                  key=lambda v: (not v["in_tsukiji_30min_guess"], v["region_hint"], v["venue"]))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(seed, f, ensure_ascii=False, indent=2)

    core = sum(1 for v in seed if v["in_tsukiji_30min_guess"])
    print(f"blogspot抽出: {len(seed)} 件（中核7区=圏内True: {core} 件）→ {OUT}")
    by_ward = {}
    for v in seed:
        by_ward.setdefault(v["region_hint"], []).append(v["venue"])
    for ward, vs in by_ward.items():
        print(f"  {ward}: {len(vs)}件  {', '.join(vs[:8])}{' …' if len(vs) > 8 else ''}")


if __name__ == "__main__":
    main()
