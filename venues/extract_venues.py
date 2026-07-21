"""
方向案B Step0：会場マスタの「種」を既存データから自動生成するスクリプト。

data/latest.json（ニュース）と data/voices.json（人の言葉）のタイトル・本文から
会場名を抽出し、data/venues_seed.json を生成する。

抽出はベストエフォート（要・人手レビュー）。各エントリに needs_review=True を付ける。
依存は標準ライブラリのみ（collect.py の fail-safe 方針を踏襲）。
                                                    — こと（Claude Code）2026-05-31
"""

import json
import os
import re

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
LATEST = os.path.join(DATA_DIR, "latest.json")
VOICES = os.path.join(DATA_DIR, "voices.json")
OUT = os.path.join(DATA_DIR, "venues_seed.json")

# 会場名の末尾になりやすいキーワード（長いものを優先）
VENUE_SUFFIXES = [
    "小学校", "中学校", "河川敷", "商店街", "公民館", "区民館", "市民館",
    "神社", "公園", "広場", "団地", "会館", "球場", "校庭", "跡地",
    "グランド", "グラウンド", "弁天", "別院", "本願寺", "寺", "院",
]
# 会場名を構成しうる文字（日本語＋英数＋中黒など）
NAME_CHARS = r"[一-龥ぁ-んァ-ヶー々〆ヶA-Za-z0-9・ヶ]"

# 都道府県・市区町村の抽出用
ADMIN_RE = re.compile(r"([一-龥ぁ-んァ-ヶー]{1,6}?[都道府県])?([一-龥ぁ-んァ-ヶー]{1,5}?[区市町村])")

# 築地（中央区）起点・自転車30分圏内とみなす東京の区（おおよそ 6〜8km 圏）
NEAR_TSUKIJI = {
    "中央区", "港区", "千代田区", "台東区", "墨田区", "江東区",
    "品川区", "文京区", "新宿区", "渋谷区", "目黒区", "荒川区",
}
# 東京23区（区名だけでは神戸市東灘区などと衝突するため、東京判定に使う）
TOKYO_WARDS = NEAR_TSUKIJI | {
    "大田区", "世田谷区", "中野区", "杉並区", "豊島区", "北区",
    "板橋区", "練馬区", "足立区", "葛飾区", "江戸川区",
}


# 会場名として無意味な汎用語（接尾辞そのもの等）
GENERIC = {
    "小学校", "中学校", "公園", "神社", "広場", "会場", "会館", "寺", "院",
    "開放的な公園", "いこいの広場", "中央公園",
}


def _clean(name):
    """前後の記号・助詞・地名接頭辞・日付を落として会場名を整える。"""
    name = name.strip(" 　「」『』【】()（）<>《》、。!！?？#＃-—:：・")
    # 先頭の汎用接頭辞を反復除去：第N回 / 20XX年 / 日付 / 助詞 / in・on
    while True:
        new = re.sub(
            r"^(第?\s*\d+\s*回|20\d{2}年?|\d{1,2}[日月]|in|on|"
            r"[はがをにでのとへやもへ]|[\s　]+)",
            "", name, flags=re.IGNORECASE).strip()
        if new == name:
            break
        name = new
    # 先頭の地名接頭辞「○○都/県…区/市/町の」を除去（会場名の重複防止）
    name = re.sub(r"^([一-龥ぁ-んァ-ヶー]{1,6}?[都道府県])?"
                  r"([一-龥ぁ-んァ-ヶー]{1,5}?[区市町村])の?", "", name).strip()
    return name


# 文（節）の途中を拾った誤検出を弾くための語
CLAUSE_MARKERS = ("して", "から", "集める", "皆様", "という", "ました", "られ", "ている")
# 接尾辞は一致するが会場ではない誤検出
NOT_VENUE = {"少年院"}


def _looks_like_venue(name):
    if not name or len(name) < 3 or len(name) > 16:
        return False
    if name in GENERIC or name in NOT_VENUE:
        return False
    if any(m in name for m in CLAUSE_MARKERS):
        return False
    return any(name.endswith(s) for s in VENUE_SUFFIXES)


def extract_from_text(text):
    """1つのテキストから会場名候補を (venue, method) のリストで返す。"""
    found = []
    if not text:
        return found

    # 方式1: 括弧内に会場キーワードを含むもの （…）/(…)
    for inner in re.findall(r"[（(]([^（）()]{2,30})[）)]", text):
        c = _clean(inner)
        if _looks_like_venue(c):
            found.append((c, "paren"))

    # 方式2: ＠/@ の直後の会場名
    for inner in re.findall(r"[＠@]\s*(" + NAME_CHARS + r"{2,30})", text):
        c = _clean(inner)
        if _looks_like_venue(c):
            found.append((c, "atmark"))

    # 方式3: キーワード末尾アンカー（名前＋接尾辞）
    suffix_alt = "|".join(sorted(VENUE_SUFFIXES, key=len, reverse=True))
    for m in re.finditer(r"(" + NAME_CHARS + r"{1,14}?(?:" + suffix_alt + r"))", text):
        c = _clean(m.group(1))
        # 「盆踊り」自体や一般語を除外
        if _looks_like_venue(c) and c not in ("小学校", "中学校", "公園", "神社"):
            found.append((c, "keyword"))

    return found


def guess_region(text):
    """テキストから市区町村を推定し、(region, in_range_guess) を返す。"""
    for pref, ward in ADMIN_RE.findall(text):
        admin = ward
        if admin in TOKYO_WARDS or pref in ("東京都", ""):
            if admin in NEAR_TSUKIJI:
                return admin, True
            if admin in TOKYO_WARDS:
                return admin, False  # 東京だが圏外寄り
        if admin:
            return (pref + admin if pref else admin), False
    return None, None


def load(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    records = []
    for item in load(LATEST):
        records.append(("latest", item.get("title", ""), item.get("title", ""), item.get("url", "")))
    for item in load(VOICES):
        blob = (item.get("title", "") + "\n" + item.get("text", ""))
        records.append(("voices", item.get("title", ""), blob, item.get("url", "")))

    venues = {}  # venue名 -> seedエントリ
    for source, title, blob, url in records:
        region, in_range = guess_region(blob)
        for venue, method in extract_from_text(blob):
            if venue not in venues:
                venues[venue] = {
                    "venue": venue,
                    "region_hint": region,
                    "in_tsukiji_30min_guess": in_range,
                    "source": source,
                    "source_title": title[:120],
                    "url": url,
                    "method": method,
                    "needs_review": True,
                }

    seed = sorted(venues.values(), key=lambda v: (v["in_tsukiji_30min_guess"] is not True, v["venue"]))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(seed, f, ensure_ascii=False, indent=2)

    in_range = sum(1 for v in seed if v["in_tsukiji_30min_guess"] is True)
    print(f"抽出会場数: {len(seed)} 件（うち築地30分圏内の候補: {in_range} 件）")
    print(f"出力: {OUT}")


if __name__ == "__main__":
    main()
