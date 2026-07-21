"""Create a first-pass review summary for X account ranking validation.

This is an assistant review, not a final user decision. It labels the generated
validation sample with the current project goal in mind:

- useful: helps discover/confirm an event or decide whether to attend
- maybe: related but far, indirect, or mostly atmosphere/practice
- not_useful: off-target for this project
"""

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


SAMPLES_FILE = Path("data/x_rank_validation_samples.json")
RESULT_FILE = Path("data/x_rank_validation_result.json")


USEFUL_HINTS = [
    "築地本願寺",
    "晴海ふ頭公園",
    "大江戸まつり",
    "浜町公園",
    "神田明神",
    "上野公園",
    "豊洲",
    "錦糸町河内音頭",
    "すみだ錦糸町",
    "奥浅草盆踊り",
    "ふるさと千川",
    "戸越宮前",
    "飛鳥山",
    "TOKYO盆ダンス",
    "濱町音頭",
    "築地",
    "中央区",
    "浅草",
    "台東区",
    "墨田区",
    "江東区",
]

MAYBE_HINTS = [
    "練習会",
    "踊ってきた",
    "踊って来た",
    "初めて踊った",
    "楽しかった",
    "盆踊り会場",
    "音頭",
    "豊田講堂",
    "横浜",
    "藤沢",
    "松戸",
    "蒲田",
    "石神井",
    "軽井沢",
]

NOT_USEFUL_HINTS = [
    "見取り図盆踊り",
    "江戸妖怪探偵社",
    "老人スポーツ大会",
    "文芸社セレクション",
    "国富音頭",
    "犬山踊芸祭",
    "真夏のラフフェス",
    "Secret再結成",
    "イビルジョー",
    "カラオケ",
    "暗黒盆踊り",
    "盆踊りチョー得意",
    "バック・ビート",
    "盆踊り大会やろう",
    "あぎゃ",
    "鼻の皮",
    "電車空いてる",
    "オフィス寒すぎ",
    "療養",
]


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def contains_any(text, hints):
    return any(hint in text for hint in hints)


def review_sample(sample):
    text = sample.get("text", "")
    score = sample.get("score", 0)
    reasons = sample.get("reasons", [])

    if score < 0 or contains_any(text, NOT_USEFUL_HINTS):
        return "不要", "off_target_or_no_context"

    if contains_any(text, USEFUL_HINTS):
        return "有益", "home_area_or_known_target_signal"

    if "future_schedule" in reasons and "date_time" in reasons and "link" in reasons:
        if contains_any(text, MAYBE_HINTS):
            return "微妙", "valid_event_but_indirect_or_far"
        return "有益", "dated_event_signal"

    if "experience" in reasons or contains_any(text, MAYBE_HINTS):
        return "微妙", "experience_or_practice_reference"

    if score >= 20:
        return "微妙", "high_score_but_project_fit_unclear"

    return "不要", "weak_context"


def main():
    data = load_json(SAMPLES_FILE, {"samples": []})
    reviewed = []
    by_bucket = defaultdict(Counter)
    by_score_band = defaultdict(Counter)
    by_reason = Counter()

    for sample in data.get("samples", []):
        label, reason = review_sample(sample)
        row = dict(sample)
        row["review"] = {
            "human_label": label,
            "usefulness_type": sample.get("kind_tags", []),
            "notes": reason,
            "reviewer": "おと（Codex） first-pass",
        }
        reviewed.append(row)
        by_bucket[sample.get("sample_bucket", "")][label] += 1
        if sample.get("score", 0) >= 20:
            band = "high_20_plus"
        elif sample.get("score", 0) >= 7:
            band = "middle_7_plus"
        else:
            band = "low_under_7"
        by_score_band[band][label] += 1
        by_reason[reason] += 1

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": str(SAMPLES_FILE),
        "reviewer": "おと（Codex） first-pass",
        "note": "内田さんの最終判断前に、スコア式の弱点を見るための一次レビュー。",
        "summary": {
            "total": len(reviewed),
            "labels": dict(Counter(row["review"]["human_label"] for row in reviewed)),
            "by_bucket": {k: dict(v) for k, v in sorted(by_bucket.items())},
            "by_score_band": {k: dict(v) for k, v in sorted(by_score_band.items())},
            "review_reasons": dict(by_reason),
        },
        "findings": [
            "高スコアは近場・日程確定系では強いが、遠方イベントや一般イベント混入もある。",
            "1投稿だけ高得点のアカウントをCandidate止まりにした方針は妥当。",
            "中位スコアは文脈確認だけの投稿が多く、ランク上げには使いにくい。",
            "参加レポ型は新規発見ではなく、行く判断・雰囲気判断として別枠評価が必要。",
        ],
        "reviewed_samples": reviewed,
    }
    RESULT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[review] wrote {len(reviewed)} reviewed samples -> {RESULT_FILE}")
    print(f"[review] labels: {output['summary']['labels']}")
    print(f"[review] by_bucket: {output['summary']['by_bucket']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
