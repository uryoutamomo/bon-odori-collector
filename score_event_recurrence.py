#!/usr/bin/env python3
"""Score event recurrence likelihood for public-facing status labels."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EVENTS_PATH = ROOT / "data/public/events_public.json"
OUT_JSON = ROOT / "data/event_recurrence_candidates.json"
OUT_MD = ROOT / "data/event_recurrence_candidates.md"
OUT_PUBLIC_PREVIEW = ROOT / "data/public/events_public_with_recurrence.json"
TODAY = date(2026, 6, 17)


RECURRING_KEYWORDS = [
    "毎年",
    "例年",
    "恒例",
    "納涼",
    "例大祭",
    "町会",
    "自治会",
    "商店街",
    "神社",
    "寺",
    "盆踊り大会",
    "夏祭り",
    "まつり",
]

ONE_SHOT_KEYWORDS = [
    "第1回",
    "第１回",
    "初開催",
    "初回",
    "特別",
    "周年",
    "記念",
    "アースデイ",
    "フェス",
    "FESTIVAL",
    "Festival",
    "STEAM",
    "BON DANCE",
    "BONDO",
    "シブヤエンタメ祭",
]


def read_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        y, m, d = [int(part) for part in value.split("-")]
        return date(y, m, d)
    except Exception:
        return None


def event_text(event: dict) -> str:
    return "\n".join(
        str(event.get(key) or "")
        for key in ["name", "venue", "area", "description", "detail"]
    )


def event_key(event: dict) -> str:
    return "|".join(str(event.get(key) or "") for key in ["name", "venue", "date"])


def label_for_score(score: float) -> tuple[str, str]:
    if score >= 0.75:
        return "今年も開催見込み 高", "expected_high"
    if score >= 0.55:
        return "今年も開催見込み 中", "expected_medium"
    if score >= 0.35:
        return "今年も開催見込み 低", "expected_low"
    return "日程未確認", "date_unknown"


def score_2025_candidate(event: dict) -> tuple[float, list[str], list[str]]:
    text = event_text(event)
    reasons: list[str] = []
    cautions: list[str] = []
    score = 0.45

    if "2025" in text:
        score += 0.05
        reasons.append("2025年実績あり")
    if "公式確認URL" in text or "公式" in text:
        score += 0.08
        reasons.append("公式/準公式確認あり")
    if "youtube_evidence" in text or "YouTube 2025" in text:
        score += 0.04
        reasons.append("動画実績証拠あり")
    if event.get("venue"):
        score += 0.04
        reasons.append("会場あり")
    if event.get("area"):
        score += 0.02
        reasons.append("23区エリアあり")

    recurring_hits = [word for word in RECURRING_KEYWORDS if word in text]
    if recurring_hits:
        score += min(0.18, 0.04 * len(recurring_hits))
        reasons.extend(f"継続語:{word}" for word in recurring_hits[:4])

    if re.search(r"第[2-9２-９][0-9０-９]*回|第[一二三四五六七八九十百]+回", text):
        score += 0.07
        reasons.append("回数付き継続イベント")

    if "次回日程は未確認" in text:
        cautions.append("次回日程未確認")

    one_shot_hits = [word for word in ONE_SHOT_KEYWORDS if word in text]
    if one_shot_hits:
        score -= min(0.20, 0.05 * len(one_shot_hits))
        cautions.extend(f"単発/企画色:{word}" for word in one_shot_hits[:4])

    if re.search(r"2025\b|2025年", str(event.get("name") or "")):
        score -= 0.05
        cautions.append("イベント名に2025明記")

    score = max(0.05, min(0.90, score))
    return round(score, 2), reasons, cautions


def public_status_for_event(event: dict) -> dict:
    start = parse_iso_date(event.get("date"))
    status = event.get("status")
    year = start.year if start else None

    if year == 2026 and start and start >= TODAY:
        return {
            "public_status": "upcoming_confirmed",
            "public_status_label": "今後開催",
            "recurrence_label": "2026年確認済み",
            "recurrence_score": 0.95,
            "reasons": ["2026年日付確認済み"],
            "cautions": [],
            "last_seen_year": None,
        }

    if year == 2026:
        return {
            "public_status": "ended_2026",
            "public_status_label": "開催終了",
            "recurrence_label": "2026年開催終了",
            "recurrence_score": 0.98,
            "reasons": ["2026年開催済み"],
            "cautions": [],
            "last_seen_year": None,
        }

    if year == 2025:
        score, reasons, cautions = score_2025_candidate(event)
        label, public_status = label_for_score(score)
        return {
            "public_status": public_status,
            "public_status_label": "2025年実績あり",
            "recurrence_label": label,
            "recurrence_score": score,
            "reasons": reasons,
            "cautions": cautions,
            "last_seen_year": 2025,
        }

    score = 0.25 if event.get("months") or event.get("hints") else 0.15
    reasons = []
    if event.get("months"):
        reasons.append("月ヒントあり")
    if event.get("hints"):
        reasons.append("日付ヒントあり")
    if status == "未確認":
        reasons.append("未確認")
    return {
        "public_status": "date_unknown",
        "public_status_label": "日程未確認",
        "recurrence_label": "日程未確認",
        "recurrence_score": score,
        "reasons": reasons,
        "cautions": ["2026年日程なし"],
        "last_seen_year": None,
    }


def summarize_date(event: dict) -> str:
    start = event.get("date") or ""
    end = event.get("date_end") or ""
    if start and end and end != start:
        return f"{start}〜{end}"
    return start or "日程未確認"


def public_note(row: dict) -> str:
    status = row.get("public_status")
    date_text = summarize_date(row)
    if status == "upcoming_confirmed":
        return f"2026年日程確認済み: {date_text}"
    if status == "ended_2026":
        return f"2026年開催終了: {date_text}"
    if status in {"expected_high", "expected_medium", "expected_low"}:
        return f"昨年開催あり: {date_text}。今年の日程は未確認です。"
    return "今年の日程は未確認です。"


def build_rows(events: list[dict]) -> list[dict]:
    rows = []
    for event in events:
        scored = public_status_for_event(event)
        start = parse_iso_date(event.get("date"))
        row = {
            "event_key": event_key(event),
            "name": event.get("name"),
            "venue": event.get("venue"),
            "area": event.get("area"),
            "date": event.get("date"),
            "date_end": event.get("date_end"),
            "source_status": event.get("status"),
            "source_date_year": start.year if start else None,
            "months": event.get("months") or [],
            "public_status": scored["public_status"],
            "public_status_label": scored["public_status_label"],
            "recurrence_label": scored["recurrence_label"],
            "recurrence_score": scored["recurrence_score"],
            "recurrence_reasons": scored["reasons"],
            "recurrence_cautions": scored["cautions"],
            "last_seen_year": scored["last_seen_year"],
            "last_seen_dates": [value for value in [event.get("date"), event.get("date_end")] if value],
            "needs_review": scored["public_status"] in {"expected_high", "expected_medium"},
        }
        row["public_note"] = public_note(row)
        rows.append(row)
    return rows


def enrich_public_events(events: list[dict], rows: list[dict]) -> list[dict]:
    by_key = {row["event_key"]: row for row in rows}
    enriched = []
    for event in events:
        item = dict(event)
        row = by_key.get(event_key(event))
        if row:
            for key in [
                "public_status",
                "public_status_label",
                "public_note",
                "recurrence_label",
                "recurrence_score",
                "recurrence_reasons",
                "recurrence_cautions",
                "last_seen_year",
                "last_seen_dates",
            ]:
                item[key] = row[key]
        enriched.append(item)
    return enriched


def sort_rows(rows: list[dict]) -> list[dict]:
    status_order = {
        "upcoming_confirmed": 0,
        "expected_high": 1,
        "expected_medium": 2,
        "expected_low": 3,
        "date_unknown": 4,
        "ended_2026": 5,
    }
    return sorted(
        rows,
        key=lambda row: (
            status_order.get(row["public_status"], 9),
            -(row["recurrence_score"] or 0),
            row.get("date") or "9999-99-99",
            row.get("area") or "",
            row.get("name") or "",
        ),
    )


def render_md(rows: list[dict]) -> str:
    counts = Counter(row["public_status"] for row in rows)
    labels = {
        "upcoming_confirmed": "今後開催",
        "expected_high": "今年も開催見込み 高",
        "expected_medium": "今年も開催見込み 中",
        "expected_low": "今年も開催見込み 低",
        "date_unknown": "日程未確認",
        "ended_2026": "開催終了",
    }
    lines = [
        "# 再開催見込みスコア 初版",
        "",
        "既存 `data/public/events_public.json` だけを使った仮スコアです。公開表示へ入れる前に、こと/内田さんレビューで調整します。",
        "",
        "## 件数",
        "",
    ]
    for key in ["upcoming_confirmed", "expected_high", "expected_medium", "expected_low", "date_unknown", "ended_2026"]:
        lines.append(f"- {labels[key]}: {counts.get(key, 0)}")

    lines.extend(
        [
            "",
            "## 要レビュー（中〜高、2026日付なし）",
            "",
            "| score | label | 日付/実績 | 区 | イベント | 会場 | 理由 | 注意 |",
            "|---:|---|---|---|---|---|---|---|",
        ]
    )
    review_rows = [row for row in rows if row["public_status"] in {"expected_high", "expected_medium"}]
    for row in review_rows[:80]:
        reasons = " / ".join(row["recurrence_reasons"][:4])
        cautions = " / ".join(row["recurrence_cautions"][:3])
        lines.append(
            f"| {row['recurrence_score']:.2f} | {row['recurrence_label']} | {summarize_date(row)} | "
            f"{row.get('area') or ''} | {row.get('name') or ''} | {row.get('venue') or ''} | {reasons} | {cautions} |"
        )

    lines.extend(
        [
            "",
            "## 全件",
            "",
            "| category | score | 元status | 日付 | 区 | イベント | 会場 |",
            "|---|---:|---|---|---|---|---|",
        ]
    )
    for row in rows:
        lines.append(
            f"| {row['recurrence_label']} | {row['recurrence_score']:.2f} | {row.get('source_status') or ''} | "
            f"{summarize_date(row)} | {row.get('area') or ''} | {row.get('name') or ''} | {row.get('venue') or ''} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    events = read_json(EVENTS_PATH)
    rows = sort_rows(build_rows(events))
    output = {
        "generated_at": "2026-06-17",
        "source": str(EVENTS_PATH.relative_to(ROOT)),
        "today": TODAY.isoformat(),
        "count": len(rows),
        "status_counts": dict(Counter(row["public_status"] for row in rows)),
        "rows": rows,
    }
    write_json(OUT_JSON, output)
    OUT_MD.write_text(render_md(rows), encoding="utf-8")
    write_json(OUT_PUBLIC_PREVIEW, enrich_public_events(events, rows))
    print(f"wrote {OUT_JSON}")
    print(f"wrote {OUT_MD}")
    print(f"wrote {OUT_PUBLIC_PREVIEW}")
    print(dict(Counter(row["public_status"] for row in rows)))


if __name__ == "__main__":
    main()
