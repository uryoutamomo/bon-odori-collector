#!/usr/bin/env python3
"""Build a YouTube-first song master from event-song occurrence evidence."""

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from song_processing.weekly_song_triage import CANONICAL_MAP, NOISE_EXACT


DATA = Path("data")
SOURCE = DATA / "song_occurrences.json"
OUT = DATA / "youtube_song_master.json"
REPORT = DATA / "youtube_song_master_review.md"
REVIEWED_SONG_IDENTITIES = DATA / "publication_gap_song_identity_llm_decisions.json"

GOOD_RELIABILITY_KEYS = {
    "complete_numbered_video",
    "official_setlist",
    "semi_official_setlist",
    "curated_public_song",
}

GENRE_LABELS = {
    "folk": "民謡・新民謡",
    "local_ondo": "ご当地音頭",
    "anime_kids": "アニメ・子ども向け",
    "jpop_dance": "J-POP・ダンス",
    "showa_kayo": "昭和歌謡・歌謡曲",
    "enka": "演歌",
    "western": "洋楽・海外曲",
    "festival_original": "企画曲・イベント曲",
    "other": "その他",
    "needs_research": "要調査",
}

BON_USAGE_OVERRIDES = {
    "東京音頭": "定番",
    "炭坑節": "定番",
    "大東京音頭": "定番",
    "八木節": "定番",
    "ダンシングヒーロー": "定番",
    "ドンパン節": "定番",
    "花笠音頭": "定番",
    "相馬盆唄": "定番",
    "チャンチキおけさ": "よく使われる",
    "きよしのズンドコ節": "よく使われる",
    "会津磐梯山": "よく使われる",
    "北海盆唄": "よく使われる",
    "河内音頭": "よく使われる",
    "ドラえもん音頭": "よく使われる",
    "マツケンサンバII": "よく使われる",
    "ジャンボリミッキー": "よく使われる",
    "盆ギリ恋歌": "よく使われる",
    "ジンギスカン": "よく使われる",
}

KNOWN_GENRES = {
    "東京音頭": ("local_ondo", "代表的なご当地音頭", "高"),
    "大東京音頭": ("local_ondo", "東京系のご当地音頭", "高"),
    "東京みなと音頭": ("local_ondo", "東京系のご当地音頭", "高"),
    "たいとう音頭": ("local_ondo", "地域名を冠した音頭", "高"),
    "新台東音頭": ("local_ondo", "地域名を冠した音頭", "高"),
    "平成新宿音頭": ("local_ondo", "地域名を冠した音頭", "高"),
    "新宿音頭": ("local_ondo", "地域名を冠した音頭", "高"),
    "東京タワー音頭": ("local_ondo", "東京名所を冠した音頭", "中"),
    "炭坑節": ("folk", "盆踊り定番の民謡系", "高"),
    "八木節": ("folk", "民謡系", "高"),
    "ドンパン節": ("folk", "民謡系", "高"),
    "花笠音頭": ("folk", "民謡・新民謡系", "高"),
    "相馬盆唄": ("folk", "民謡系", "高"),
    "チャンチキおけさ": ("showa_kayo", "歌謡曲として流通する盆踊り定番", "中"),
    "会津磐梯山": ("folk", "民謡系", "高"),
    "北海盆唄": ("folk", "民謡系", "高"),
    "津軽甚句": ("folk", "民謡系", "高"),
    "真室川音頭": ("folk", "民謡・新民謡系", "高"),
    "河内音頭": ("folk", "民謡・口説き音頭系", "高"),
    "江州音頭": ("folk", "民謡・口説き音頭系", "高"),
    "デカンショ節": ("folk", "民謡系", "高"),
    "秋田音頭": ("folk", "民謡系", "高"),
    "串本節": ("folk", "民謡系", "高"),
    "そうらん節": ("folk", "民謡系", "高"),
    "りんご節": ("folk", "民謡系", "中"),
    "かわさき": ("folk", "郡上おどりの曲目", "高"),
    "古調かわさき": ("folk", "郡上おどりの曲目", "高"),
    "春駒": ("folk", "郡上おどり等の曲目", "中"),
    "ダンシングヒーロー": ("jpop_dance", "J-POP・ダンス系の盆踊り定番", "高"),
    "きよしのズンドコ節": ("enka", "演歌・歌謡曲系", "高"),
    "マツケンサンバII": ("jpop_dance", "ダンス歌謡系", "高"),
    "365日の紙飛行機": ("jpop_dance", "J-POP系", "高"),
    "ジャンボリミッキー": ("anime_kids", "ディズニー・子ども向け", "高"),
    "ドラえもん音頭": ("anime_kids", "アニメ音頭", "高"),
    "となりのトトロ": ("anime_kids", "アニメ・子ども向け", "高"),
    "オバQ音頭": ("anime_kids", "アニメ音頭", "高"),
    "にんげんっていいな": ("anime_kids", "アニメ・子ども向け", "高"),
    "翔べ!ガンダム": ("anime_kids", "アニメ楽曲", "高"),
    "銀座カンカン娘": ("showa_kayo", "昭和歌謡", "高"),
    "まつのき小唄": ("showa_kayo", "歌謡曲・小唄系", "中"),
    "お富さん": ("showa_kayo", "昭和歌謡", "高"),
    "好きになった人": ("showa_kayo", "昭和歌謡", "高"),
    "一円玉の旅がらす": ("showa_kayo", "歌謡曲", "中"),
    "南国土佐を後にして": ("showa_kayo", "昭和歌謡", "高"),
    "ジンギスカン": ("western", "洋楽由来のダンス曲", "高"),
    "バハマママ": ("western", "洋楽・ダンス曲", "中"),
    "APT": ("western", "海外ポップス", "中"),
    "Love so sweet": ("jpop_dance", "J-POP系", "中"),
    "Happiness": ("jpop_dance", "J-POP系", "中"),
    "シンデレラガール": ("jpop_dance", "J-POP系", "中"),
    "チキチキバンバン": ("jpop_dance", "ダンス系ポップス", "中"),
    "盆ギリ恋歌": ("festival_original", "盆踊り向け企画曲", "中"),
    "これがお江戸の盆ダンス": ("festival_original", "盆踊り向け企画曲", "中"),
    "燃えろ日本の夏祭り": ("festival_original", "祭り・盆踊り向け企画曲", "中"),
    "日本の夏ごよみ": ("festival_original", "祭り・盆踊り向け企画曲", "中"),
}

GENRE_OR_SYSTEM_TERMS = {
    "盆踊り",
    "盆おどり",
    "ぼんおどり",
    "輪踊り",
    "民謡",
    "郡上おどり",
    "郡上踊り",
    "白鳥おどり",
    "白鳥踊り",
    "阿波踊り",
    "阿波おどり",
}

MANUAL_REJECT_SONG_NAMES = {
    # 2026-06-20: public glossary screenshot review.
    # These are setlist fragments, performers, program sections, or non-bon-odori songs
    # that were promoted from one-off YouTube evidence.
    "まとめ1",
    "まとめ2",
    "まとめ3",
    "ムーンライトステーション",
    "ムーンライト伝説",
    "ラジオ体操",
    "阿波踊り「和楽連",
    "阿波踊り「和樂連",
    "一般の部",
    "子どもの部",
    "千本櫻",
    "浅草右近屋",
    "浅草右近屋パフォーマンス",
    "大人の部",
    "川崎おどり",
    "川崎踊り",
}

CANONICAL_FIXES = {
    **CANONICAL_MAP,
    "郡上かわさき": "かわさき",
    "郡上節かわさき": "かわさき",
    "古調かわさき・かわさき": "かわさき",
    "少年八木節": "八木節",
    "ダンシング・ヒーロー": "ダンシングヒーロー",
    "バハマ・ママ": "バハマママ",
    "炭鉱節": "炭坑節",
    "000年音頭": "2000年音頭",
    "２０００年音頭": "2000年音頭",
    "65日の紙飛行機": "365日の紙飛行機",
    "鰺ヶ沢甚句": "鯵ヶ沢甚句",
    "旧 台東音頭": "旧台東音頭",
    "U.S.A": "U.S.A.",
    "USA": "U.S.A.",
}

SUPPRESSED_ALIASES = {
    "000年音頭",
}


@lru_cache(maxsize=1)
def reviewed_song_identity_rules(path=REVIEWED_SONG_IDENTITIES):
    path = Path(path)
    if not path.exists():
        return {}, set(), set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    canonical = {}
    noise = set()
    candidates = set()
    for row in payload.get("decisions") or []:
        raw_name = clean_name(row.get("raw_song_name"))
        decision = row.get("decision")
        if decision in {"既存曲へ統合", "新規曲候補として維持"}:
            target = clean_name(row.get("target_song_name"))
            if raw_name and target:
                canonical[raw_name] = target
            if decision == "新規曲候補として維持" and target:
                candidates.add(target)
        elif decision == "曲名ノイズとして除外" and raw_name:
            noise.add(raw_name)
    return canonical, noise, candidates

HARD_NOISE_RE = re.compile(
    r"("
    r"https?://|www\.|"
    r"Tokyo|Japan|Ebisu|Asakusa|Shibuya|Shinjuku|"
    r"Bon\s*dance|BON[-\s]?ODORI|"
    r"全曲|全曲ver|前編|後編|中編|ダイジェスト|"
    r"開催|会場|公園|広場|神社|商店街|駅|周辺|ロータリー|特設|"
    r"大会|フェス|イベント|"
    r"激混み|外国人|有志|季節|"
    r"お囃子|獅子舞|DJタイム|EDM盆踊り"
    r")",
    re.IGNORECASE,
)

SOFT_REVIEW_RE = re.compile(
    r"("
    r"生歌|メドレー|応援歌|"
    r"新曲|練習|講習|"
    r"組み踊り|流し踊り"
    r")"
)

ANIME_KIDS_RE = re.compile(
    r"(ドラえもん|トトロ|ミッキー|オバQ|ガンダム|サザエ|アンパンマン|"
    r"ハム太郎|ポケモン|妖怪|プリキュア|アニメ)"
)
JPOP_DANCE_RE = re.compile(
    r"(ダンシング|ヒーロー|サンバ|J-POP|LOVE|Love|Happiness|"
    r"シンデレラ|チキチキ|フォーチュン|さくらんぼ|APT|RPG|USA|U\.S\.A)"
)
WESTERN_RE = re.compile(
    r"(YMCA|Y\.M\.C\.A|U\.S\.A|USA|APT|Bahama|Boney|Beat It|"
    r"Jingle|Christmas|Santa|Dinosaur|Funk|Toca|September|"
    r"Love|Happiness)"
)
SHOWA_KAYO_RE = re.compile(
    r"(カンカン娘|お富さん|小唄|ズンドコ|旅がらす|ブギウギ|"
    r"好きになった人|南国土佐|東京ばやし)"
)
FOLK_RE = re.compile(
    r"(民謡|甚句|節|盆唄|おけさ|ソーラン|そうらん|ハイヤ|"
    r"かわさき|春駒|ドダレバチ|木遣り|浮立|音頭口説)"
)
LOCAL_ONDO_RE = re.compile(
    r"(東京|台東|新宿|葛飾|文京|すみだ|上野|大山|高輪|白浜|"
    r"日本橋|丸の内|浅草橋|町|市|区|村|郷|ふるさと|故郷|音頭)$"
)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def norm(value):
    return re.sub(r"\s+", "", str(value or "")).casefold()


def clean_name(value):
    value = str(value or "").strip()
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"[（(]\s*生歌\s*[）)]?$", "", value)
    value = re.sub(r"^終\s*", "", value)
    value = value.strip(" ・/／-–—:：,，.。()（）[]【】「」『』")
    return value


def canonical_name(value):
    name = clean_name(value)
    reviewed_fixes, _, _ = reviewed_song_identity_rules()
    return reviewed_fixes.get(name, CANONICAL_FIXES.get(name, name))


def hard_reject_reason(name):
    _, reviewed_noise, reviewed_candidates = reviewed_song_identity_rules()
    if not name:
        return "空の曲名"
    if name in reviewed_noise:
        return "LLMレビューで曲名ノイズとして除外"
    if name in reviewed_candidates:
        return ""
    if name in MANUAL_REJECT_SONG_NAMES:
        return "手動レビューで曲マスター除外"
    if name in NOISE_EXACT:
        return "既知の文章断片"
    if "おどりはだり" in name or "踊りはだり" in name:
        return "曲ではなく用語・動画見出し"
    if name in GENRE_OR_SYSTEM_TERMS:
        return "曲ではなく体系・総称"
    if re.fullmatch(r"[0-9０-９]+", name):
        return "番号だけ"
    if len(name) > 36:
        return "曲名として長すぎる"
    if re.search(r"[。]", name):
        return "文章記号を含む"
    if HARD_NOISE_RE.search(name):
        return "動画タイトル・会場名由来の断片"
    return ""


def review_reason(name, stats):
    _, _, reviewed_candidates = reviewed_song_identity_rules()
    if name in reviewed_candidates:
        return "LLMレビュー済み新規曲候補"
    if SOFT_REVIEW_RE.search(name):
        return "曲名か体系名か確認が必要"
    if stats["good_evidence_count"] == 1 and stats["speaker_count"] <= 1:
        return "YouTube証拠が1件のみ"
    if len(name) <= 1:
        return "短すぎる"
    return ""


def source_label(row):
    labels = []
    if row["reliability_counts"].get("complete_numbered_video"):
        labels.append("YouTubeセットリスト")
    if row["reliability_counts"].get("official_setlist"):
        labels.append("公式曲目")
    if row["reliability_counts"].get("semi_official_setlist"):
        labels.append("準公式曲目")
    if row["reliability_counts"].get("curated_public_song"):
        labels.append("公開イベント曲目")
    return " / ".join(labels) or "曲目証拠"


def bon_usage_rank(row):
    occurrence_count = int(row.get("occurrence_count") or 0)
    good_count = int(row.get("good_evidence_count") or 0)
    speaker_count = int(row.get("speaker_count") or 0)
    year_count = len(row.get("years") or [])
    reliability = row.get("reliability_counts", {})
    official_count = reliability.get("official_setlist", 0)
    semi_official_count = reliability.get("semi_official_setlist", 0)
    public_count = reliability.get("curated_public_song", 0)
    curated_count = official_count + semi_official_count + public_count
    score = (
        min(occurrence_count, 60)
        + min(good_count, 80) // 4
        + speaker_count * 25
        + year_count * 20
        + official_count * 16
        + semi_official_count * 12
        + public_count * 10
    )

    override = BON_USAGE_OVERRIDES.get(row.get("song_name"))
    if override:
        return override, score

    # 同一投稿者・同一年の大量動画は「広く使われる」根拠として扱わない。
    if speaker_count <= 1 and year_count <= 1:
        if curated_count >= 2 and occurrence_count >= 40:
            return "ときどき使われる", score
        if occurrence_count >= 3:
            return "地域・会場固有", score
        return "要確認", score

    if occurrence_count < 20:
        if occurrence_count >= 3:
            return "地域・会場固有", score
        return "要確認", score

    if speaker_count >= 5 and year_count >= 3 and curated_count >= 4:
        rank = "定番"
    elif speaker_count >= 4 and year_count >= 2 and curated_count >= 1:
        rank = "よく使われる"
    elif speaker_count >= 3 and year_count >= 2:
        rank = "ときどき使われる"
    elif speaker_count >= 2 and (year_count >= 2 or curated_count >= 1):
        rank = "ときどき使われる"
    elif occurrence_count >= 3:
        rank = "地域・会場固有"
    else:
        rank = "要確認"
    return rank, score


def genre_from_name(name):
    if name in KNOWN_GENRES:
        genre_key, basis, confidence = KNOWN_GENRES[name]
        return genre_key, GENRE_LABELS[genre_key], confidence, basis
    if ANIME_KIDS_RE.search(name):
        return "anime_kids", GENRE_LABELS["anime_kids"], "中", "アニメ・子ども向け語を含む"
    if WESTERN_RE.search(name):
        return "western", GENRE_LABELS["western"], "低", "英語曲名・海外曲らしい語を含む"
    if JPOP_DANCE_RE.search(name):
        return "jpop_dance", GENRE_LABELS["jpop_dance"], "低", "J-POP・ダンス曲らしい語を含む"
    if SHOWA_KAYO_RE.search(name):
        return "showa_kayo", GENRE_LABELS["showa_kayo"], "低", "歌謡曲らしい語を含む"
    if FOLK_RE.search(name):
        return "folk", GENRE_LABELS["folk"], "中", "民謡系の接尾辞・語を含む"
    if name.endswith("音頭"):
        if LOCAL_ONDO_RE.search(name):
            return "local_ondo", GENRE_LABELS["local_ondo"], "中", "地域名・場所名を冠した音頭らしい"
        return "local_ondo", GENRE_LABELS["local_ondo"], "低", "音頭名だが由来未確認"
    if name.endswith(("小唄", "甚句", "節", "盆唄")):
        return "folk", GENRE_LABELS["folk"], "中", "民謡系の接尾辞を持つ"
    if re.search(r"(祭り|まつり|盆ダンス|盆ギリ|おはやし)", name):
        return "festival_original", GENRE_LABELS["festival_original"], "低", "祭り・盆踊り向け企画曲らしい語を含む"
    return "needs_research", GENRE_LABELS["needs_research"], "低", "曲名だけでは判定不能"


def aggregate_occurrences(payload):
    by_key = {}
    reject_counter = Counter()
    rejected_samples = defaultdict(list)

    for occurrence in payload.get("occurrences", []):
        event_name = occurrence.get("event_name") or ""
        venue = occurrence.get("venue") or ""
        year = occurrence.get("year")
        occurrence_id = occurrence.get("occurrence_id") or ""
        for song in occurrence.get("songs", []):
            raw_name = clean_name(song.get("song_name") or "")
            name = canonical_name(raw_name)
            reason = hard_reject_reason(name)
            if reason:
                reject_counter[reason] += 1
                if len(rejected_samples[reason]) < 20:
                    rejected_samples[reason].append(raw_name)
                continue

            key = norm(name)
            row = by_key.setdefault(
                key,
                {
                    "song_name": name,
                    "aliases": set(),
                    "evidence_count": 0,
                    "good_evidence_count": 0,
                    "occurrence_ids": set(),
                    "event_names": Counter(),
                    "venues": Counter(),
                    "years": set(),
                    "speakers": set(),
                    "urls": Counter(),
                    "reliability_counts": Counter(),
                    "source_counts": Counter(),
                },
            )
            if raw_name and raw_name != name and raw_name not in SUPPRESSED_ALIASES:
                row["aliases"].add(raw_name)
            row["occurrence_ids"].add(occurrence_id)
            if event_name:
                row["event_names"][event_name] += 1
            if venue:
                row["venues"][venue] += 1
            if year:
                row["years"].add(int(year))

            for evidence in song.get("evidence", []):
                rel_key = evidence.get("reliability_key") or "unknown"
                source = evidence.get("source") or "unknown"
                row["evidence_count"] += 1
                row["reliability_counts"][rel_key] += 1
                row["source_counts"][source] += 1
                if rel_key in GOOD_RELIABILITY_KEYS:
                    row["good_evidence_count"] += 1
                if evidence.get("speaker"):
                    row["speakers"].add(evidence["speaker"])
                if evidence.get("url"):
                    row["urls"][evidence["url"]] += 1

    rows = []
    for row in by_key.values():
        row["speaker_count"] = len(row["speakers"])
        row["occurrence_count"] = len(row["occurrence_ids"])
        row["evidence_url_count"] = len(row["urls"])
        reason = review_reason(row["song_name"], row)
        row["status"] = "要確認" if reason else "有効"
        row["public_ready"] = not reason and row["good_evidence_count"] > 0
        row["review_reason"] = reason
        row["source_label"] = source_label(row)
        row["description"] = "盆踊り会場の曲目として確認されている曲です。"
        row["bon_usage_rank"], row["bon_usage_score"] = bon_usage_rank(row)
        (
            row["song_genre_key"],
            row["song_genre"],
            row["genre_confidence"],
            row["genre_basis"],
        ) = genre_from_name(row["song_name"])
        row["genre_review_status"] = (
            "要調査" if row["song_genre_key"] == "needs_research" or row["genre_confidence"] == "低" else "仮分類"
        )
        row["aliases"] = sorted(row["aliases"])
        row["years"] = sorted(row["years"])
        row["sample_events"] = [name for name, _ in row["event_names"].most_common(5)]
        row["sample_venues"] = [name for name, _ in row["venues"].most_common(5)]
        row["youtube_urls"] = [
            url for url, _ in row["urls"].most_common(5) if "youtube.com" in url or "youtu.be" in url
        ]
        row["reliability_counts"] = dict(row["reliability_counts"])
        row["source_counts"] = dict(row["source_counts"])
        del row["occurrence_ids"]
        del row["event_names"]
        del row["venues"]
        del row["speakers"]
        del row["urls"]
        rows.append(row)

    rows.sort(
        key=lambda row: (
            0 if row["public_ready"] else 1,
            -(row["good_evidence_count"]),
            row["song_name"],
        )
    )
    return rows, reject_counter, rejected_samples


def report_markdown(payload):
    rows = payload["songs"]
    accepted = [row for row in rows if row["public_ready"]]
    review = [row for row in rows if not row["public_ready"]]
    usage_counts = Counter(row.get("bon_usage_rank") or "未分類" for row in accepted)
    genre_counts = Counter(row.get("song_genre") or "未分類" for row in accepted)
    lines = [
        "# YouTube曲マスター レビュー",
        "",
        f"- 生成日時: {payload['generated_at']}",
        f"- 入力occurrence数: {payload['source_occurrence_count']}",
        f"- 公開候補: {len(accepted)}",
        f"- 要確認: {len(review)}",
        f"- 除外行: {payload['rejected_song_row_count']}",
        "",
        "## 盆踊り利用頻度",
        "",
    ]
    for label in ("定番", "よく使われる", "ときどき使われる", "地域・会場固有", "要確認"):
        if usage_counts.get(label):
            lines.append(f"- {label}: {usage_counts[label]}曲")
    lines.extend([
        "",
        "## 仮ジャンル",
        "",
    ])
    for label, count in genre_counts.most_common():
        lines.append(f"- {label}: {count}曲")
    lines.extend([
        "",
        "## 公開候補 上位",
        "",
    ])
    for row in accepted[:80]:
        lines.append(
            f"- {row['song_name']} "
            f"(証拠 {row['good_evidence_count']} / 会場回 {row['occurrence_count']} / "
            f"{row.get('bon_usage_rank')} / {row.get('song_genre')})"
        )
    lines.extend(["", "## 要確認 上位", ""])
    for row in review[:80]:
        lines.append(
            f"- {row['song_name']} "
            f"(理由: {row['review_reason']} / 証拠 {row['good_evidence_count']})"
        )
    lines.extend(["", "## 除外理由", ""])
    for reason, count in payload["rejected_reasons"].items():
        samples = " / ".join(payload["rejected_samples"].get(reason, [])[:8])
        lines.append(f"- {reason}: {count}件 例: {samples}")
    return "\n".join(lines) + "\n"


def build(source=SOURCE):
    payload = load_json(source)
    rows, reject_counter, rejected_samples = aggregate_occurrences(payload)
    public_count = sum(1 for row in rows if row["public_ready"])
    return {
        "generated_by": "build_youtube_song_master.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "source_occurrence_count": len(payload.get("occurrences", [])),
        "source_song_relation_count": payload.get("song_relation_count"),
        "song_count": len(rows),
        "public_ready_count": public_count,
        "review_count": len(rows) - public_count,
        "rejected_song_row_count": sum(reject_counter.values()),
        "rejected_reasons": dict(reject_counter),
        "rejected_samples": {key: sorted(set(values)) for key, values in rejected_samples.items()},
        "songs": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(SOURCE), help="song_occurrences.json path")
    parser.add_argument("--out", default=str(OUT), help="output JSON path")
    parser.add_argument("--report", default=str(REPORT), help="review markdown path")
    args = parser.parse_args()

    payload = build(Path(args.source))
    write_json(Path(args.out), payload)
    Path(args.report).write_text(report_markdown(payload), encoding="utf-8")
    print(
        "YouTube曲マスター生成完了: "
        f"public_ready={payload['public_ready_count']} "
        f"review={payload['review_count']} "
        f"rejected_rows={payload['rejected_song_row_count']} -> {args.out}"
    )


if __name__ == "__main__":
    main()
