#!/usr/bin/env python3
"""Triage harvested song candidates before sending ambiguous rows to review."""

import argparse
import json
import os
import re
import urllib.request
from pathlib import Path

from notion_support.notion_config import (
    EVENT_DATABASE_ID,
    SONG_MASTER_DATABASE_ID,
    VENUE_DATABASE_ID,
    load_local_env,
)
from song_processing.bon_odori_songs import is_master_song
from song_processing.song_master_registration import classify_song


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
TOKEN = os.environ.get("NOTION_API_TOKEN")
SONG_DB_ID = os.environ.get("SONG_MASTER_DB_ID") or SONG_MASTER_DATABASE_ID
SOURCE = Path("data/weekly_harvest_candidates.json")
OUT = Path("data/weekly_song_triage_result.json")
REVIEW_OUT = Path("data/weekly_song_candidates_review.json")

TITLE_PROPS = {
    EVENT_DATABASE_ID: "イベント名",
    VENUE_DATABASE_ID: "会場名",
    SONG_DB_ID: "曲名",
}

CANONICAL_MAP = {
    "炭鉱節": "炭坑節",
    "今回は難解な炭坑節": "炭坑節",
    "今日は新たに炭鉱節": "炭坑節",
    "先生はやはり炭鉱節": "炭坑節",
    "子供用にドラえもん音頭": "ドラえもん音頭",
    "週末の発表会で急遽東京音頭": "東京音頭",
    "一宮のカーニバルで踊った南中ソーラン": "南中ソーラン",
    "初めての野毛山節": "野毛山節",
    "保存会さん生唄の根尾おどり": "根尾おどり",
    "復活してほしいなあの時は町民で盛り上がってうきは音頭": "うきは音頭",
    "山代音頭輪踊り": "山代音頭",
    "甘味屋さんと戸越音頭": "戸越音頭",
    "ユリが咲いてる中にっぽん花咲か音頭": "にっぽん花咲か音頭",
    "やっぱりイエローサブマリン音頭": "イエローサブマリン音頭",
    "アラメヤ音頭": "よこはまアラメヤ音頭",
}

AMBIGUOUS_TERMS = {
    "郡上おどり",
    "先日の郡上おどり",
    "まんず青山の郡上おどり",
    "山王音頭と千代田踊り",
    "岡崎音頭と五万石おどり",
    "徳島市阿波おどり",
    "飛鳥山公園輪踊り",
    "盆ジョビ",
    "馬鹿おどり",
    "よさこい踊り",
    "夜の踊り",
    # 2026-08-04 追加。曲名かイベント名かジャンル名か判断がつかず、
    # 自動登録も自動棄却もすべきでないもの。
    "BON踊り",
    "ドン踊り",
    "ボン・ジョヴィ踊り",
    "酒クズ音頭",
    "防災神神音頭",
    "風流踊り",
}

NOISE_EXACT = {
    "ぼんおどり",
    "またその行事内で行われる踊り",
    "団体様の踊り",
    "お前が伝統的な踊り",
    "お囃子と踊り",
    "が楽しくささら踊り",
    "が混ざった日本ぽい踊り",
    "こっちでも踊り",
    "この夏は踊り",
    "ぜひ香信と踊り",
    "だれでも踊り",
    "って思ってたら踊り",
    "って言われてパッとどんな踊り",
    "っぽいあっちゃんの踊り",
    "つぐみ夫妻の踊り",
    "ともくんが馬鹿踊り",
    "どうしてもビートイットがタコ踊り",
    "どうぞ踊り",
    "どの踊り",
    "なんかひとつでも踊り",
    "なんて素敵な曲と踊り",
    "の囃子ことばに合わせてみんなで一緒に踊り",
    "また踊り",
    "ゆくぞ桶狭間も踊り",
    "らしき踊り",
    "アバンギャルディさん達みたいにカッコよく踊り",
    "シーズンインしたばかりで豪華な踊り",
    "シーズン中は踊り",
    "トートに入れてるパソコンがぶんぶん揺れて踊り",
    "ライダーの踊り",
    "ラスト一宮の親友と踊り",
    "上手い人の振りを見ながらすんなりと踊り",
    "今でこそ地味で暗いと言われる相模のささら踊り",
    "今度は東海で一緒に踊り",
    "今日は踊り",
    "今日は電車に揺られて踊り",
    "全員で楽しく踊り",
    "各区の踊り",
    "園庭で大きな輪になって踊り",
    "夏イラストはやはりBON踊り",
    "多様な踊り",
    "太鼓等の鳴り物を使わず長野の山間集落で3日間夜通し踊り",
    "季節",
    "尼崎の踊り",
    "応援歌の生歌",
    "息の合った踊り",
    "愛知県安城市での定番踊り",
    "我が家ルールは踊り",
    "昔ながらの曲から老若男女に人気の曲まで幅広く踊り",
    "昨日は一宮駅の踊り",
    "昨日は早起きだったせいかお姉ちゃん達の踊り",
    "昼から夜までお祭り騒ぎで季節",
    "根尾の踊り",
    "歴史ある踊り",
    "流しから輪踊り",
    "百万石祭り踊り",
    "百万石踊り",
    "私は踊り",
    "突然デコトラと獅子舞だして踊り",
    "老若男女踊り",
    "自分の好きな民謡踊り",
    "自分の踊り",
    "誰かと踊り",
    "誰もどなたも踊り",
    "踊り",
    "隅田公園そよ風ひろばに踊り",
    # 2026-08-04 追加。日次 triage の created 177件を1件ずつ確認して分類した分。
    # 判定基準は内田さんの承認済み（入れたくない例＝多くの踊り／まだまだ踊り／
    # 楽しく歌って踊り／1日目踊り／3日間楽しく踊り／東京音頭と炭坑節）。
    "多くの踊り",
    "まだまだ踊り",
    "楽しく歌って踊り",
    "1日目踊り",
    "3日間楽しく踊り",
    "東京音頭と炭坑節",
    "3人の音頭",
    "いいね暑気払いの踊り",
    "いっぱい踊り",
    "いつかまたあの踊り",
    "こちらの踊り",
    "こちらは踊り",
    "しっかり踊り",
    "ぜひ踊り",
    "ぜーーんぜん踊り",
    "そしたら踊り",
    "ちょうど踊り",
    "つの踊り",
    "てwww踊り",
    "という程お腹一杯踊り",
    "といったご当地踊り",
    "といった復興支援の踊り",
    "とは言え踊り",
    "と地元の踊り",
    "と夜の踊り",
    "どーしても踊り",
    "なんなら踊り",
    "の変な踊り",
    "の風流踊り",
    "はらりはられ今踊り",
    "ひらすら踊り",
    "ほとんどはじめての踊り",
    "みんなと踊り",
    "みんな踊り",
    "もっと踊り",
    "やスカイツリーおどり",
    "ゆったりとした踊り",
    "わたしもまだまだ踊り",
    "アンコールは築地音頭",
    "テンポの早い音頭",
    "ド下手くその踊り",
    "フィナーレの築地音頭",
    "マジ踊り",
    "一番踊り",
    "上手な方の踊り",
    "下手な踊り",
    "中学生の踊り",
    "例年ゆかた音頭",
    "別名盆ジョビ",
    "唄も覚えた踊り",
    "唄も踊り",
    "夏まつりの季節",
    "夏祭りの季節",
    "太鼓の踊り",
    "子どもたちの太鼓や踊り",
    "定番郡上おどり",
    "市の音頭",
    "所変われば踊り",
    "手拭い八木節等楽しく踊り",
    "日本の伝統的な踊り",
    "昭和3年頃よされ節",
    "最後は淀川音頭",
    "最後ウチの町会の踊り",
    "最後踊り",
    "本日はシン煙草音頭",
    "東京音頭など大きな踊り",
    "東京音頭も大東京音頭も盆ジョビ",
    "歌と踊り",
    "水買って来て踊り",
    "港おどりよりもいか踊り",
    "炭坑節とか踊り",
    "皆さんと踊る炭鉱節",
    "知らない踊り",
    "知らない音頭",
    "祭りの季節",
    "私は地元の踊り",
    "良かったらふらっと踊り",
    "諏訪分校跡は踊り",
    "軽くひと踊り",
    "阿澄さんは音頭",
    "雨の中踊り",
    "面白い踊り",
    "高円寺阿波踊りの踊り",
    "生歌の新宿音頭や八木節",
    "生歌コーナーの八木節",
    "獅子ヶ谷音頭 港北音頭",
    "酒田音頭・花笠音頭",
    "英語の炭坑節",
    "Golden・トンカカさん踊り",
    "ハワイ音頭踊り",
    "ちゃっきり節初踊り",
    "本物の津軽手踊り",
    "岐阜の郡上踊り",
}


def notion_request(method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{NOTION_API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Notion-Version", NOTION_VERSION)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())


def rich_text(value, limit=1900):
    value = str(value or "")[:limit]
    return [{"type": "text", "text": {"content": value}}] if value else []


def plain_text(prop):
    if not prop:
        return ""
    prop_type = prop.get("type")
    if prop_type in ("title", "rich_text"):
        return "".join(item.get("plain_text", "") for item in prop.get(prop_type, [])).strip()
    return ""


def number_value(prop):
    return prop.get("number") if prop and prop.get("type") == "number" else None


def norm(value):
    return re.sub(r"\s+", "", str(value or "")).casefold()


def query_database(db_id):
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


def title_index(db_id):
    prop = TITLE_PROPS[db_id]
    index = {}
    for page in query_database(db_id):
        name = plain_text(page.get("properties", {}).get(prop, {}))
        if name:
            index[norm(name)] = {"id": page["id"], "name": name, "page": page}
    return index


def relation_ids(prop):
    if not prop or prop.get("type") != "relation":
        return []
    return [item["id"] for item in prop.get("relation", [])]


def matched_page_ids(text, index, limit=8):
    matches = []
    for item in sorted(index.values(), key=lambda value: len(value["name"]), reverse=True):
        name = item["name"]
        if len(name) >= 3 and name in text:
            matches.append(item["id"])
        if len(matches) >= limit:
            break
    return matches


SONG_SUFFIX_RE = (
    r"(?:音頭|おどり|踊り|小唄|甚句|節|盆唄|盆ジョビ|ソーラン|"
    r"ダンシングヒーロー|ビューティフルサンデー)"
)
# Particles that end a phrase right before the suffix in running prose
# (多くの踊り / みんなと踊り / 唄も踊り).  か and ら are deliberately absent:
# they occur inside real titles (いか踊り, ふるさと音頭, らら音頭, 越中おわら節,
# 秦野ささら踊り, 鹿児島おはら節) and cost us those if treated as particles.
SUFFIX_PARTICLE_CHARS = "のとやもがをにへで"


def is_song_like(term):
    if len(term) < 2 or len(term) > 18:
        return False
    if re.search(r"[。、！？!?「」]", term):
        return False
    if re.search(r"(が|を|に|へ|で|から|まで|でも|ながら|みたい|らしき|っぽい|今日は|昨日|今回|先日|週末)", term):
        return False
    # A date or a count never belongs to a title here (1日目踊り, 3人の音頭).
    if re.search(r"[0-9０-９]", term):
        return False
    # Two titles joined by prose (東京音頭と炭坑節) must be reviewed, not split
    # blindly, so reject rather than guess which half is meant.
    if len(re.findall(SONG_SUFFIX_RE, term)) >= 2:
        return False
    match = re.search(SONG_SUFFIX_RE + r"$", term)
    if match and match.start() > 0 and term[match.start() - 1] in SUFFIX_PARTICLE_CHARS:
        return False
    return bool(re.search(SONG_SUFFIX_RE + r"$", term))


def classify_candidate(row):
    term = row["term"]
    if term in CANONICAL_MAP:
        return "direct", CANONICAL_MAP[term], "既知曲を含む文章候補を正規曲名へ寄せた"
    if term in NOISE_EXACT:
        return "reject", term, "曲名ではなく文章断片または一般語"
    if term in AMBIGUOUS_TERMS:
        return "review", term, "多義語・イベント名・ジャンル名の可能性がある"
    # The accumulated song master outranks the shape heuristics: titles such as
    # ふるさと音頭 look like prose to is_song_like() (と before the suffix) but
    # are already confirmed songs. Check the accumulation before guessing.
    #
    # PROVISIONAL (2026-08-04): is_master_song() currently reads a static
    # "known song" provider that includes all 743 rows of
    # data/rdb_song_review_source.json, every one of which carries
    # status=needs_song_master_review -- i.e. unreviewed. That provider is
    # not a safe "verified" signal on its own; it happened not to promote a
    # sentence fragment here only because AMBIGUOUS_TERMS/NOISE_EXACT already
    # catch the known bad cases checked above. Do not extend this priority
    # to any new caller, and do not treat it as a template for other checks.
    # Replace with song_processing.song_catalog.SongCatalog.is_verified(),
    # which distinguishes verified/candidate/rejected/unknown by RDB status,
    # once the P2 runtime switch lands (see
    # bon-odori-song-pipeline-design-20260804 thread).
    if is_master_song(term):
        return "direct", term, "曲マスタに登録済みの曲名"
    if is_song_like(term):
        return "direct", term, "曲名として明白な接尾辞/既知パターン"
    return "reject", term, "曲名としての形が弱い"


def song_props(row, canonical, venue_ids, event_ids, existing_page=None):
    props = existing_page.get("properties", {}) if existing_page else {}
    current_venues = relation_ids(props.get("会場", {}))
    current_events = relation_ids(props.get("イベント", {}))
    current_evidence = number_value(props.get("証拠数", {})) or 0
    merged_venues = [{"id": page_id} for page_id in sorted(set(current_venues + venue_ids))]
    merged_events = [{"id": page_id} for page_id in sorted(set(current_events + event_ids))]
    evidence_count = max(int(current_evidence), int(row.get("evidence_count") or 0))
    memo = (
        "日次X収穫候補からおと判断で明白曲として処理。\n"
        f"元候補: {row['term']}\n"
        f"理由: {row.get('triage_reason', '')}\n"
        f"証拠URL: {row.get('evidence_url', '')}\n"
        f"証拠抜粋: {row.get('evidence_text', '')[:900]}"
    )
    out = {
        "分類": {"select": {"name": classify_song(canonical)}},
        "状態": {"select": {"name": "有効"}},
        "証拠数": {"number": evidence_count},
        "メモ": {"rich_text": rich_text(memo)},
    }
    if not existing_page:
        out["曲名"] = {"title": rich_text(canonical[:200])}
    if row.get("evidence_url"):
        out["出典・音源URL"] = {"url": row["evidence_url"]}
    if merged_venues:
        out["会場"] = {"relation": merged_venues}
    if merged_events:
        out["イベント"] = {"relation": merged_events}
    return out


def write_review_output(source, review_rows):
    payload = {
        "generated_by": "triage_weekly_song_candidates.py",
        "source": str(source),
        "count": len(review_rows),
        "rows": review_rows,
    }
    REVIEW_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    if not SONG_DB_ID:
        raise SystemExit("SONG_MASTER_DB_ID is not set")

    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    song_rows = [row for row in data.get("rows", []) if row.get("category") == "曲候補"]
    songs = title_index(SONG_DB_ID)
    venues = title_index(VENUE_DATABASE_ID)
    events = title_index(EVENT_DATABASE_ID)

    direct = []
    rejected = []
    review = []
    for row in song_rows:
        decision, canonical, reason = classify_candidate(row)
        row = dict(row)
        row["canonical_song_name"] = canonical
        row["triage_reason"] = reason
        if decision == "reject":
            rejected.append(row)
        elif decision == "review":
            review.append(row)
        else:
            direct.append(row)

    created = []
    updated = []
    for row in direct:
        canonical = row["canonical_song_name"]
        key = norm(canonical)
        evidence_text = row.get("evidence_text") or ""
        venue_ids = matched_page_ids(evidence_text, venues)
        event_ids = matched_page_ids(evidence_text, events)
        existing = songs.get(key)
        if args.dry_run:
            target = "update" if existing else "create"
            (updated if existing else created).append(
                {
                    "song_name": canonical,
                    "source_term": row["term"],
                    "target": target,
                    "venue_relations": len(venue_ids),
                    "event_relations": len(event_ids),
                    "dry_run": True,
                }
            )
            continue
        if existing:
            notion_request(
                "PATCH",
                f"/pages/{existing['id']}",
                {"properties": song_props(row, canonical, venue_ids, event_ids, existing["page"])},
            )
            updated.append({"song_name": canonical, "source_term": row["term"], "page_id": existing["id"]})
        else:
            page = notion_request(
                "POST",
                "/pages",
                {
                    "parent": {"database_id": SONG_DB_ID},
                    "properties": song_props(row, canonical, venue_ids, event_ids),
                },
            )
            created.append({"song_name": canonical, "source_term": row["term"], "page_id": page["id"]})
            songs[key] = {"id": page["id"], "name": canonical, "page": page}

    write_review_output(SOURCE, review)
    result = {
        "dry_run": args.dry_run,
        "source": str(SOURCE),
        "song_candidate_count": len(song_rows),
        "direct_count": len(direct),
        "created_count": len(created),
        "updated_count": len(updated),
        "rejected_noise_count": len(rejected),
        "review_count": len(review),
        "created": created,
        "updated": updated,
        "rejected_noise": [
            {"term": row["term"], "reason": row["triage_reason"]}
            for row in rejected
        ],
        "review": [
            {
                "term": row["term"],
                "evidence_count": row.get("evidence_count"),
                "reason": row["triage_reason"],
                "evidence_url": row.get("evidence_url", ""),
            }
            for row in review
        ],
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "done: songs={song_candidate_count} direct={direct_count} "
        "created={created_count} updated={updated_count} "
        "noise={rejected_noise_count} review={review_count} dry_run={dry_run}".format(**result)
    )
    print(f"wrote {OUT}")
    print(f"wrote {REVIEW_OUT}")


if __name__ == "__main__":
    main()
