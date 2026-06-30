#!/usr/bin/env python3
"""Fill hiragana readings for the glossary v2 Notion database."""

import argparse
import json
import os
import re
import unicodedata
import urllib.error
import urllib.request

from notion_config import GLOSSARY_V2_DATABASE_ID, NOTION_API_BASE, load_local_env


load_local_env()

NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")
DB_ID = os.environ.get("GLOSSARY_V2_DB_ID") or GLOSSARY_V2_DATABASE_ID
NOTION_VERSION = "2022-06-28"
READING_PROP = "読み"
APPLY_CONFIRMATION = "APPLY GLOSSARY READINGS"

KATAKANA_TO_HIRAGANA_OFFSET = ord("ぁ") - ord("ァ")

MANUAL_READINGS = {
    "AFATH2026": "えーえふえーてぃーえいちにせんにじゅうろく",
    "AFATH26": "えーえふえーてぃーえいちにじゅうろく",
    "BON-ODORI": "ぼんおどり",
    "Bonjū": "ぼんじゅう",
    "DH": "でぃーえいち",
    "Min-Yoi's": "みんよいず",
    "Min-Yoi's盆踊り": "みんよいずぼんおどり",
    "Twitter": "ついったー",
    "URL": "ゆーあーるえる",
    "YouTube": "ゆーちゅーぶ",
    "あのマツケン": "あのまつけん",
    "えびすくい音頭": "えびすくいおんど",
    "お暇": "おいとま",
    "お邪魔する": "おじゃまする",
    "さくら音頭": "さくらおんど",
    "じゃこっぺ踊り": "じゃこっぺおどり",
    "すみジャズ": "すみじゃず",
    "たいとう音頭": "たいとうおんど",
    "なみぼん": "なみぼん",
    "ぼーんとぅ盆踊り": "ぼーんとぅぼんおどり",
    "ぼーんとぅ盆踊り2026夏": "ぼーんとぅぼんおどりにせんにじゅうろくなつ",
    "まめかち": "まめかち",
    "まんまる音頭": "まんまるおんど",
    "みんよいず": "みんよいず",
    "みん盆": "みんぼん",
    "やまぼん": "やまぼん",
    "よこはまアラメヤ音頭": "よこはまあらめやおんど",
    "ろまい会": "ろまいかい",
    "アキバ盆踊り": "あきばぼんおどり",
    "アニメソング盆踊り": "あにめそんぐぼんおどり",
    "アニソン盆踊り": "あにそんぼんおどり",
    "コソ練": "こそれん",
    "トランス状態": "とらんすじょうたい",
    "ドアラONDO": "どあらおんど",
    "ハダ盆": "はだぼん",
    "ボンジャム": "ぼんじゃむ",
    "ミンヨイズ": "みんよいず",
    "ミンヨイズ盆踊り": "みんよいずぼんおどり",
    "ラビドビ": "らびどび",
    "ラビードビー": "らびーどびー",
    "リード": "りーど",
    "一宮盆踊り": "いちのみやぼんおどり",
    "予習": "よしゅう",
    "内側": "うちがわ",
    "初見": "しょけん",
    "初見曲": "しょけんきょく",
    "参戦": "さんせん",
    "後ろにつく": "うしろにつく",
    "後ろに付かせて下さい": "うしろにつかせてください",
    "徹夜踊り": "てつやおどり",
    "所作で捨てる": "しょさですてる",
    "文京音頭": "ぶんきょうおんど",
    "新浅草橋音頭": "しんあさくさばしおんど",
    "新野の盆踊り": "にいののぼんおどり",
    "晴盆": "はれぼん",
    "晴盆様": "はれぼんさま",
    "東京五輪音頭": "とうきょうごりんおんど",
    "東京北都音頭": "とうきょうほくとおんど",
    "東京音頭": "とうきょうおんど",
    "板橋音頭": "いたばしおんど",
    "梯子": "はしご",
    "横浜開港祭BON": "よこはまかいこうさいぼん",
    "江州音頭": "ごうしゅうおんど",
    "沼ぼん": "ぬまぼん",
    "浅草ばし音頭": "あさくさばしおんど",
    "浜っ娘音頭": "はまっこおんど",
    "流し踊り": "ながしおどり",
    "櫓に上がる": "やぐらにあがる",
    "櫓上": "やぐらうえ",
    "盆ジョビ": "ぼんじょび",
    "盆ジョヴィ": "ぼんじょゔぃ",
    "盆ダンス": "ぼんだんす",
    "盆フェス": "ぼんふぇす",
    "盆フェスタ": "ぼんふぇすた",
    "盆友": "ぼんとも",
    "盆女": "ぼんじょ",
    "盆獣": "ぼんじゅう",
    "盆踊らー": "ぼんおどらー",
    "盆踊りオフ会": "ぼんおどりおふかい",
    "盆踊りオフ練": "ぼんおどりおふれん",
    "盆踊りジョヴィ": "ぼんおどりじょゔぃ",
    "盆踊りロス": "ぼんおどりろす",
    "盆踊り巡り": "ぼんおどりめぐり",
    "盆踊り巡る": "ぼんおどりめぐる",
    "盆踊るトーク": "ぼんおどるとーく",
    "盆踊ラー": "ぼんおどらー",
    "直前練習": "ちょくぜんれんしゅう",
    "秦野盆部": "はだのぼんぶ",
    "秋田音頭": "あきたおんど",
    "総本山": "そうほんざん",
    "超ニコニコ盆踊り": "ちょうにこにこぼんおどり",
    "超会ニコニコ盆踊り": "ちょうかいにこにこぼんおどり",
    "練習会": "れんしゅうかい",
    "荒川音頭": "あらかわおんど",
    "見よう見まね": "みようみまね",
    "見学だけ": "けんがくだけ",
    "踊らー": "おどらー",
    "踊りきる": "おどりきる",
    "踊りにくい": "おどりにくい",
    "踊りに行く": "おどりにいく",
    "踊りの輪に入る": "おどりのわにはいる",
    "踊りやすい": "おどりやすい",
    "踊り始め": "おどりはじめ",
    "踊り子": "おどりこ",
    "踊り手": "おどりて",
    "踊り流し": "おどりながし",
    "踊り狂う": "おどりくるう",
    "踊ろまい会": "おどろまいかい",
    "輪の中に入る": "わのなかにはいる",
    "輪の外側": "わのそとがわ",
    "輪踊り": "わおどり",
    "通過": "つうか",
    "遠征": "えんせい",
    "郡上おどり": "ぐじょうおどり",
    "郡上踊り": "ぐじょうおどり",
    "重複": "ちょうふく",
    "開港祭BON-ODORI": "かいこうさいぼんおどり",
    "関東遠征": "かんとうえんせい",
    "飛び入り": "とびいり",
    "飛び入り専門": "とびいりせんもん",
    "飛鳥山公園盆踊り": "あすかやまこうえんぼんおどり",
    "飛鳥山公園輪踊り": "あすかやまこうえんわおどり",
    "飛鳥山音頭": "あすかやまおんど",
    "黒石よされ節": "くろいしよされぶし",
    "平和音頭": "へいわおんど",
}


def notion_request(method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{NOTION_API_BASE}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {NOTION_TOKEN}")
    req.add_header("Notion-Version", NOTION_VERSION)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as response:
        if response.status == 204:
            return {}
        return json.loads(response.read())


def plain_text(prop):
    if not prop:
        return ""
    values = prop.get("title") or prop.get("rich_text") or []
    return "".join(item.get("plain_text", "") for item in values).strip()


def query_all_pages(db_id):
    rows = []
    cursor = None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        data = notion_request("POST", f"/databases/{db_id}/query", payload)
        rows.extend(data.get("results", []))
        if not data.get("has_more"):
            return rows
        cursor = data.get("next_cursor")


def to_hiragana(text):
    chars = []
    for ch in unicodedata.normalize("NFKC", text):
        code = ord(ch)
        if ord("ァ") <= code <= ord("ヶ"):
            chars.append(chr(code + KATAKANA_TO_HIRAGANA_OFFSET))
        elif ch == "ヴ":
            chars.append("ゔ")
        else:
            chars.append(ch)
    return "".join(chars)


def normalize_reading(text):
    text = to_hiragana(text).lower()
    text = re.sub(r"[ \t\r\n]+", "", text)
    text = text.replace("ー", "ー")
    return text


def fallback_reading(term):
    """Return a reading only when the term is already kana/alnum/punctuation."""
    if term in MANUAL_READINGS:
        return MANUAL_READINGS[term]
    normalized = normalize_reading(term)
    if normalized in MANUAL_READINGS:
        return MANUAL_READINGS[normalized]
    if not re.search(r"[一-龯々〆ヵヶ]", normalized):
        key = re.sub(r"[^a-z0-9]+", "", normalized)
        return MANUAL_READINGS.get(key, normalized)
    return ""


def ensure_reading_property(database, apply):
    props = database.get("properties", {})
    if READING_PROP in props:
        return False
    if not apply:
        return True
    notion_request(
        "PATCH",
        f"/databases/{DB_ID}",
        {"properties": {READING_PROP: {"rich_text": {}}}},
    )
    return True


def patch_reading(page_id, reading):
    notion_request(
        "PATCH",
        f"/pages/{page_id}",
        {
            "properties": {
                READING_PROP: {
                    "rich_text": [{"type": "text", "text": {"content": reading}}]
                }
            }
        },
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write readings to Notion")
    parser.add_argument(
        "--confirm",
        default="",
        help=f"Required with --apply: {APPLY_CONFIRMATION}",
    )
    parser.add_argument(
        "--include-unknown",
        action="store_true",
        help="Print rows whose reading cannot be inferred safely",
    )
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    if args.apply and args.confirm != APPLY_CONFIRMATION:
        raise SystemExit(f'--apply requires --confirm "{APPLY_CONFIRMATION}"')

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    try:
        database = notion_request("GET", f"/databases/{DB_ID}")
        needs_schema = ensure_reading_property(database, args.apply)
        rows = query_all_pages(DB_ID)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Notion request failed (HTTP {exc.code}): {body}") from exc

    updates = []
    unknown = []
    existing = 0
    for row in rows:
        props = row.get("properties", {})
        term = plain_text(props.get("使用語"))
        if not term:
            continue
        current = plain_text(props.get(READING_PROP))
        if current:
            existing += 1
            continue
        reading = fallback_reading(term)
        if reading:
            updates.append((row["id"], term, reading))
        else:
            unknown.append((row["id"], term))

    if args.limit:
        updates = updates[: args.limit]

    if args.apply:
        for page_id, _term, reading in updates:
            patch_reading(page_id, reading)

    print(
        f"glossary readings: rows={len(rows)} existing={existing} "
        f"updates={len(updates)} unknown={len(unknown)} "
        f"schema_added_or_needed={needs_schema} apply={args.apply}"
    )
    for _page_id, term, reading in updates[:50]:
        print(f"update\t{term}\t{reading}")
    if len(updates) > 50:
        print(f"... {len(updates) - 50} more updates")
    if args.include_unknown:
        for _page_id, term in unknown[:200]:
            print(f"unknown\t{term}")
        if len(unknown) > 200:
            print(f"... {len(unknown) - 200} more unknown")


if __name__ == "__main__":
    main()
