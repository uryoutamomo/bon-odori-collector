#!/usr/bin/env python3
"""Merge oto1/oto2/oto3 glossary v2 experiment reports."""

import json
from collections import Counter, defaultdict
from pathlib import Path


SOURCES = [
    ("oto1", "行動・参加スタイル語", Path("data/glossary_v2_action_terms_oto1.json")),
    ("oto2", "感情・評価・界隈ノリ語", Path("data/glossary_v2_o2_emotion_vibe_candidates.json")),
    ("oto2", "感情・評価・界隈ノリ語", Path("data/glossary_v2_o2_emotion_vibe_deep_dive.json")),
    ("oto3", "略語・表記ゆれ・呼び名", Path("data/glossary_v2_oto3_abbrev_report.json")),
    ("oto3", "略語・表記ゆれ・呼び名", Path("data/glossary_v2_oto3_abbrev_additional_report.json")),
]

OUT_JSON = Path("data/glossary_v2_oto123_merged_terms.json")
OUT_MD = Path("data/glossary_v2_oto123_merged_review.md")
OUT_FIRST_MD = Path("data/glossary_v2_oto123_first_review.md")

CONFIDENCE_RANK = {"候補": 0, "弱候補": 1, "保留": 2}
CATEGORY_ORDER = {
    "行動・参加スタイル語": 0,
    "感情・評価・界隈ノリ語": 1,
    "略語・表記ゆれ・呼び名": 2,
}

SYNONYM_GROUPS = [
    {
        "label": "踊りの輪へ入る",
        "terms": ["踊りの輪に入る", "輪の中に入る", "内側"],
        "note": "見物・外側から実際の踊り参加へ入る語群。`内側` は位置取り語として別行も可。",
    },
    {
        "label": "ハシゴ/巡回",
        "terms": ["盆踊り巡り", "盆踊り巡る", "行ったり来たり"],
        "note": "`ハシゴ` の直接証拠は未発見だが、近い行動語群。",
    },
    {
        "label": "流し踊り",
        "terms": ["踊り流し", "流し踊り"],
        "note": "列や通りを進みながら踊る形式語。地域差があるか要確認。",
    },
    {
        "label": "初見難曲への対処",
        "terms": ["初見", "初見曲", "追いやすい", "所作で捨てる", "残す部分"],
        "note": "初めての曲を現地で追う・省略する・残すという参加スキル語群。",
    },
    {
        "label": "櫓/リード",
        "terms": ["リード", "櫓に上がる", "櫓上", "輪の外側", "後ろにつく", "後ろに付かせて下さい"],
        "note": "踊りの見本、見え方、位置取り、後ろで学ぶ行動の語群。",
    },
    {
        "label": "Min-Yoi's/みん盆",
        "terms": ["Min-Yoi's", "ミンヨイズ", "みんよいず", "みん盆"],
        "note": "同一イベント/企画周辺の表記ゆれ・略称候補。",
    },
    {
        "label": "盆ジョヴィ",
        "terms": ["盆ジョヴィ", "盆ジョビ", "盆踊りジョヴィ"],
        "note": "盆ジョヴィ系の呼び名・表記ゆれ。",
    },
    {
        "label": "ラビドビ",
        "terms": ["ラビドビ", "ラビードビー"],
        "note": "同一名称の略称/表記ゆれ候補。",
    },
    {
        "label": "盆踊ラー",
        "terms": ["盆踊ラー", "盆踊らー", "踊らー"],
        "note": "盆踊り参加者・界隈人の呼称ゆれ。",
    },
    {
        "label": "盆フェス",
        "terms": ["盆フェス", "盆フェスタ"],
        "note": "イベント名/呼び名の表記ゆれ候補。",
    },
    {
        "label": "超ニコニコ盆踊り",
        "terms": ["超ニコニコ盆踊り", "超会ニコニコ盆踊り", "AFATH2026", "AFATH26"],
        "note": "イベント呼称と開催文脈の略称群。AFATHは盆踊り語というよりイベント略称。",
    },
]

FIRST_REVIEW_TERMS = {
    # oto1: action / participation style
    "遠征",
    "飛び入り",
    "飛び入り専門",
    "踊りの輪に入る",
    "見よう見まね",
    "初見",
    "予習",
    "練習会",
    "音出し",
    "リード",
    "盆踊り巡り",
    "踊り流し",
    "徹夜踊り",
    "後ろにつく",
    "輪の外側",
    "櫓に上がる",
    "追いやすい",
    "所作で捨てる",
    "途中から参加",
    "盆踊りオフ会",
    # oto2: emotion / vibe
    "トランス状態",
    "後半ちょっとトランス入った",
    "盆踊りロス",
    "盆踊りはじめ",
    "楽しみに生きる",
    "雨の盆踊りの高揚感",
    "盆踊り好き界隈に耽溺",
    "成仏できぬ魂",
    "今日から夏です",
    "盆踊り仲間が増えた",
    "震源地",
    "革命",
    "盆踊りバズれ",
    "盆踊りフィーバー",
    "踊り狂う",
    # oto3: abbreviations / names
    "ハダ盆",
    "晴盆",
    "みん盆",
    "ミンヨイズ",
    "Min-Yoi's",
    "盆ジョヴィ",
    "盆ジョビ",
    "盆踊りジョヴィ",
    "盆フェス",
    "盆フェスタ",
    "盆踊ラー",
    "盆踊らー",
    "踊らー",
    "盆女",
    "盆友",
    "盆獣",
    "沼ぼん",
    "ろまい会",
    "秦野盆部",
    "盆踊りオフ練",
    "ぼーんとぅ盆踊り",
    "アニソン盆踊り",
    "アニメソング盆踊り",
    "BON-ODORI",
    "開港祭BON-ODORI",
}


def load_rows():
    rows = []
    for source, category, path in SOURCES:
        data = json.loads(path.read_text(encoding="utf-8"))
        for index, raw in enumerate(data.get("candidates", []), 1):
            term = (raw.get("term") or "").strip()
            if not term:
                continue
            row = {
                "term": term,
                "category": category,
                "source_agent": source,
                "source_file": str(path),
                "source_index": index,
                "type": raw.get("type") or category,
                "interpretation": raw.get("interpretation") or "",
                "evidence_url": raw.get("evidence_url") or "",
                "evidence_text": raw.get("evidence_text") or "",
                "reason": raw.get("reason") or "",
                "confidence": raw.get("confidence") or "候補",
            }
            row["review_priority"] = priority(row)
            rows.append(row)
    rows.sort(
        key=lambda r: (
            CATEGORY_ORDER.get(r["category"], 99),
            CONFIDENCE_RANK.get(r["confidence"], 9),
            r["term"],
            r["source_file"],
        )
    )
    return rows


def priority(row):
    if row["confidence"] == "保留":
        return "C"
    if row["confidence"] == "弱候補":
        return "B"
    if row["category"] == "行動・参加スタイル語":
        return "A"
    if row["category"] == "略語・表記ゆれ・呼び名" and row["type"] in ("略語", "表記ゆれ", "呼び名"):
        return "A"
    if row["category"] == "感情・評価・界隈ノリ語":
        generic = ("最高", "楽しかった", "嬉し", "感激", "興奮", "凄")
        if any(word in row["term"] for word in generic):
            return "B"
    return "A"


def duplicate_terms(rows):
    counts = Counter(row["term"] for row in rows)
    return [
        {
            "term": term,
            "count": count,
            "sources": sorted({row["source_file"] for row in rows if row["term"] == term}),
        }
        for term, count in sorted(counts.items())
        if count > 1
    ]


def category_summary(rows):
    summary = defaultdict(lambda: Counter())
    for row in rows:
        summary[row["category"]][row["confidence"]] += 1
    return {
        category: dict(counter)
        for category, counter in sorted(summary.items(), key=lambda item: CATEGORY_ORDER.get(item[0], 99))
    }


def write_json(rows):
    terms = {row["term"] for row in rows}
    groups = [
        {
            **group,
            "present_terms": [term for term in group["terms"] if term in terms],
            "missing_terms": [term for term in group["terms"] if term not in terms],
        }
        for group in SYNONYM_GROUPS
    ]
    output = {
        "generated_by": "おと1（Codex）",
        "generated_at": "2026-06-11",
        "scope": "用語集v2 3おと統合レビュー",
        "source_files": [str(path) for _, _, path in SOURCES],
        "total_candidates": len(rows),
        "category_summary": category_summary(rows),
        "duplicate_terms": duplicate_terms(rows),
        "synonym_groups": groups,
        "candidates": rows,
    }
    OUT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def md_table(rows, limit=None):
    if limit:
        rows = rows[:limit]
    lines = ["| 優先 | 語 | 分類 | 確度 | 解釈 |", "|---|---|---|---|---|"]
    for row in rows:
        interpretation = row["interpretation"].replace("\n", " ").replace("|", "｜")
        lines.append(
            f"| {row['review_priority']} | {row['term']} | {row['category']} | "
            f"{row['confidence']} | {interpretation} |"
        )
    return "\n".join(lines)


def write_md(rows):
    by_priority = defaultdict(list)
    by_category = defaultdict(list)
    for row in rows:
        by_priority[row["review_priority"]].append(row)
        by_category[row["category"]].append(row)

    lines = [
        "# 用語集v2 3おと統合レビュー",
        "",
        "生成: おと1（Codex）",
        "対象: おと1/おと2/おと3 のローカル候補レポート",
        f"詳細JSON: `{OUT_JSON}`",
        "",
        "## 件数",
        "",
        f"- 総候補: {len(rows)}件",
    ]
    for category, counter in category_summary(rows).items():
        parts = " / ".join(f"{key}: {value}" for key, value in counter.items())
        lines.append(f"- {category}: {sum(counter.values())}件（{parts}）")
    lines.extend(
        [
            "",
            "## レビュー優先度",
            "",
            "- A: 採用/不採用を先に判定したい語",
            "- B: 弱候補、または一般語寄りでまとめ判断したい語",
            "- C: 保留",
            "",
            "## A候補",
            "",
            md_table(by_priority["A"]),
            "",
            "## B候補",
            "",
            md_table(by_priority["B"]),
            "",
            "## C候補",
            "",
            md_table(by_priority["C"]),
            "",
            "## 同義・まとめ候補",
            "",
            "| グループ | 今回出た語 | メモ |",
            "|---|---|---|",
        ]
    )
    terms = {row["term"] for row in rows}
    for group in SYNONYM_GROUPS:
        present = [term for term in group["terms"] if term in terms]
        if not present:
            continue
        lines.append(f"| {group['label']} | {', '.join(present)} | {group['note']} |")
    lines.extend(
        [
            "",
            "## 重複",
            "",
        ]
    )
    dupes = duplicate_terms(rows)
    if not dupes:
        lines.append("- 完全一致の重複なし")
    else:
        for item in dupes:
            lines.append(f"- {item['term']}: {item['count']}件")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_first_review_md(rows):
    first_rows = [row for row in rows if row["term"] in FIRST_REVIEW_TERMS]
    first_rows.sort(
        key=lambda r: (
            CATEGORY_ORDER.get(r["category"], 99),
            CONFIDENCE_RANK.get(r["confidence"], 9),
            r["term"],
        )
    )
    lines = [
        "# 用語集v2 3おと統合 第1レビュー用",
        "",
        "目的: 全156件から、まず内田さんが判定しやすく、週次収穫ループに効きそうな語を絞った版。",
        "",
        f"- 第1レビュー対象: {len(first_rows)}件",
        f"- 全件詳細: `{OUT_JSON}`",
        f"- 全件レビュー表: `{OUT_MD}`",
        "",
        "## 判定してほしいこと",
        "",
        "- 採用: 用語集v2に候補として残す",
        "- 不採用: 一般語すぎる/盆踊り語ではない",
        "- まとめ: 同義グループへ統合する",
        "",
    ]
    for category in sorted(CATEGORY_ORDER, key=CATEGORY_ORDER.get):
        category_rows = [row for row in first_rows if row["category"] == category]
        if not category_rows:
            continue
        lines.extend([f"## {category}", "", md_table(category_rows), ""])
    lines.extend(
        [
            "## まとめ判断が必要な語群",
            "",
            "| グループ | 語 | 判断ポイント |",
            "|---|---|---|",
        ]
    )
    for group in SYNONYM_GROUPS:
        present = [term for term in group["terms"] if term in FIRST_REVIEW_TERMS]
        if present:
            lines.append(f"| {group['label']} | {', '.join(present)} | {group['note']} |")
    OUT_FIRST_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    rows = load_rows()
    write_json(rows)
    write_md(rows)
    write_first_review_md(rows)
    print(f"merged {len(rows)} candidates -> {OUT_JSON}, {OUT_MD}, {OUT_FIRST_MD}")


if __name__ == "__main__":
    main()
