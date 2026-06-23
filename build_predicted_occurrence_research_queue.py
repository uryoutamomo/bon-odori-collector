"""Build a review queue for predicted occurrence dates.

Predicted dates are useful planning hints, but they are not current-year
confirmation. This helper keeps them out of Notion/public writes and turns
pending predictions into a source-check queue.
"""

import argparse
import json
import sqlite3
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from master_db import MASTER_DB, connect_existing


DATA = Path("data")
OUT_JSON = DATA / "predicted_occurrence_research_queue.json"
OUT_MD = DATA / "predicted_occurrence_research_queue.md"
DEFAULT_TODAY = date(2026, 6, 22)

SOURCE_REVIEW = {
    "丸の内de盆踊り": {
        "source_checked_at": "2026-06-22",
        "source_review": "current_year_source_not_found",
        "source_note": "Marunouchi.com event index and 2025 article were rechecked; no 2026 丸の内de盆踊り source was found.",
        "checked_urls": [
            "https://www.marunouchi.com/pickup/event/",
            "https://www.marunouchi.com/pickup/event/6763/",
            "https://minato-bon-odori.blogspot.com/2021/05/coming-all-h.html",
        ],
    },
    "謝恩納涼盆踊り大会（青山善光寺）": {
        "source_checked_at": "2026-06-22",
        "source_review": "current_year_source_not_found",
        "source_note": "OMOHARAREAL source is 令和7年/2025 coverage and the current bon-odori index had no 2026 row; keep as prediction.",
        "checked_urls": [
            "https://omoharareal.com/navi/news/detail/5157",
            "https://minato-bon-odori.blogspot.com/2021/05/coming-all-h.html",
        ],
    },
    "シタマチ.ふるさと盆踊り大会": {
        "source_checked_at": "2026-06-22",
        "source_review": "current_year_source_not_found",
        "source_note": "TokyoFesta and 上野が、すき。 sources confirm 2025-08-16 to 2025-08-17; no 2026 source was found.",
        "checked_urls": [
            "https://tokyofesta.com/23ku/24373/",
            "https://shopblog.dmdepart.jp/ueno/uenogasuki/article/detail/?cd=000993",
            "https://minato-bon-odori.blogspot.com/2021/05/coming-all-h.html",
        ],
    },
    "歌舞伎町BON ODORI": {
        "source_checked_at": "2026-06-22",
        "source_review": "current_year_source_not_found",
        "source_note": "Shinjuku tourism page is 2025-08-16 evidence and the current bon-odori index had no 2026 row; keep as prediction.",
        "checked_urls": [
            "https://www.kanko-shinjuku.jp/event/-/article_4606.html",
            "https://minato-bon-odori.blogspot.com/2021/05/coming-all-h.html",
        ],
    },
    "第28回新橋こいち祭 盆踊り": {
        "source_checked_at": "2026-06-22",
        "source_review": "previous_year_official_source",
        "source_note": "Existing 新橋こいち祭 source is 2025 material; confirm the 2026 program before promotion.",
    },
    "自由が丘納涼盆踊り大会": {
        "source_checked_at": "2026-06-22",
        "source_review": "current_year_source_not_found",
        "source_note": "Jiyugaoka official 2026 event list still shows no July event; TokyoFesta remains 2025 evidence only.",
        "checked_urls": [
            "https://www.jiyugaoka-abc.com/event/",
            "https://tokyofesta.com/23ku/23804/",
            "https://minato-bon-odori.blogspot.com/2021/05/coming-all-h.html",
        ],
    },
    "西久保八幡神社 盆踊り": {
        "source_checked_at": "2026-06-22",
        "source_review": "current_year_source_not_found",
        "source_note": "Official shrine article is 令和7年/2025例大祭 evidence and the current bon-odori index had no 2026 row; keep as prediction.",
        "checked_urls": [
            "https://hachimanjinja.or.jp/main/?p=5604",
            "https://minato-bon-odori.blogspot.com/2021/05/coming-all-h.html",
        ],
    },
    "第15回 鴨台盆踊り": {
        "source_checked_at": "2026-06-22",
        "source_review": "current_year_third_party_source_found",
        "source_note": "TokyoFesta has a 2026 第16回 鴨台 article for 2026-07-10 to 2026-07-11, but 大正大学公式確認は未発見 and the prediction differs; keep in review queue.",
        "checked_urls": [
            "https://www.tais.ac.jp/guide/latest_news/",
            "https://www.tais.ac.jp/guide/latest_news/20250627/92922/",
            "https://tokyofesta.com/23ku/31077/",
            "https://minato-bon-odori.blogspot.com/2021/05/coming-all-h.html",
        ],
    },
    "赤坂浄土寺盆踊り大会": {
        "source_checked_at": "2026-06-22",
        "source_review": "current_year_source_not_found",
        "source_note": "Web search, current bon-odori index, and existing prior-year X evidence did not confirm 2026; keep low-confidence prediction only.",
        "checked_urls": [
            "https://x.com/nsPFhl5JW382058/status/1939266951391613148",
            "https://minato-bon-odori.blogspot.com/2021/05/coming-all-h.html",
        ],
    },
}


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rows(db_path, query, params=()):
    with connect_existing(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(query, params)]


def date_range(start, end):
    if end and end != start:
        return f"{start} to {end}"
    return start or ""


def priority_for(prediction, today):
    start = date.fromisoformat(prediction["date_start"])
    days_until = (start - today).days
    score = 0
    reasons = []

    if days_until < 0:
        score -= 2
        reasons.append("predicted_date_already_past")
    elif days_until <= 14:
        score += 10
        reasons.append("within_14_days")
    elif days_until <= 30:
        score += 9
        reasons.append("within_30_days")
    elif days_until <= 45:
        score += 7
        reasons.append("within_45_days")
    elif days_until <= 60:
        score += 6
        reasons.append("within_60_days")
    else:
        score += 3
        reasons.append("later_prediction")

    if prediction.get("confidence") == "low":
        score -= 2
        reasons.append("low_prediction_confidence")
    elif prediction.get("confidence") == "medium":
        score += 1
        reasons.append("medium_prediction_confidence")

    if prediction.get("basis_type") == "date_based":
        score -= 1
        reasons.append("date_based_prediction")
    else:
        score += 1
        reasons.append("weekday_based_prediction")

    if score >= 9:
        label = "P0"
        action = "source_recheck_before_promotion"
    elif score >= 5:
        label = "P1"
        action = "queue_for_source_recheck"
    else:
        label = "P2"
        action = "keep_prediction_queue_only"

    return days_until, score, label, action, reasons


def load_predictions(master_db):
    return rows(
        master_db,
        """
        SELECT p.*, s.canonical_name AS series_name, s.area,
               s.source_url AS series_source_url,
               v.canonical_name AS usual_venue
        FROM predicted_occurrence_dates p
        JOIN event_series s ON s.series_id = p.target_series_id
        LEFT JOIN venues v ON v.venue_id = s.usual_venue_id
        WHERE p.application_status = 'candidate_for_2026_occurrence'
        ORDER BY p.date_start, p.score DESC, p.target_event_name
        """,
    )


def parse_payload(value):
    try:
        return json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}


def build_queue(master_db, today=DEFAULT_TODAY):
    predictions = load_predictions(master_db)
    items = []
    for prediction in predictions:
        payload = parse_payload(prediction.get("source_payload_json"))
        source_review = SOURCE_REVIEW.get(prediction["target_event_name"], {})
        days_until, priority_score, priority_label, action, reasons = priority_for(prediction, today)
        items.append(
            {
                "predicted_date_id": prediction["predicted_date_id"],
                "event_name": prediction["target_event_name"],
                "predicted_year": prediction["predicted_year"],
                "predicted_date_start": prediction["date_start"],
                "predicted_date_end": prediction.get("date_end") or prediction["date_start"],
                "days_until_predicted_start": days_until,
                "basis": prediction.get("basis") or "",
                "basis_type": prediction.get("basis_type") or "",
                "rule_type": prediction.get("rule_type") or "",
                "confidence": prediction.get("confidence") or "",
                "score": prediction.get("score"),
                "usual_venue": prediction.get("usual_venue") or "",
                "area": prediction.get("area") or "",
                "source_url": prediction.get("series_source_url") or "",
                "evidence_years": payload.get("evidence_years") or [],
                "evidence_rows": payload.get("evidence_rows") or [],
                "source_checked_at": source_review.get("source_checked_at") or "",
                "source_review": source_review.get("source_review") or "source_recheck_required",
                "source_note": source_review.get("source_note") or "Current-year source has not been reviewed.",
                "checked_urls": source_review.get("checked_urls") or [],
                "priority_score": priority_score,
                "priority_label": priority_label,
                "recommended_action": action,
                "reason_codes": reasons,
            }
        )
    items.sort(key=lambda row: ({"P0": 0, "P1": 1, "P2": 2}.get(row["priority_label"], 9), row["days_until_predicted_start"], row["event_name"]))
    return items


def render_markdown(result):
    lines = [
        "# Predicted occurrence research queue",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- master_db: `{result['sources']['master_db']}`",
        f"- today: {result['options']['today']}",
        f"- item_count: {result['summary']['item_count']}",
        f"- by_priority: {result['summary']['by_priority']}",
        f"- by_action: {result['summary']['by_action']}",
        "",
        "| priority | event | predicted | basis | venue | source review | action |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in result["items"]:
        lines.append(
            f"| {item['priority_label']} | {item['event_name']} | "
            f"{date_range(item['predicted_date_start'], item['predicted_date_end'])} | "
            f"{item['basis']} | {item['usual_venue']} | {item['source_review']} | {item['recommended_action']} |"
        )
    lines.extend(["", "## Source Notes", ""])
    for item in result["items"]:
        checked = ", ".join(item["checked_urls"]) if item["checked_urls"] else item["source_url"] or "(none)"
        lines.append(
            f"- {item['priority_label']} {item['event_name']}: {item['source_note']} "
            f"checked={checked}"
        )
    lines.append("")
    return "\n".join(lines)


def run(args):
    today = date.fromisoformat(args.today)
    items = build_queue(args.master_db, today=today)
    result = {
        "generated_by": "build_predicted_occurrence_research_queue.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "read_only_predicted_date_source_research_queue",
        "sources": {"master_db": str(args.master_db)},
        "options": {"today": args.today},
        "summary": {
            "item_count": len(items),
            "by_priority": dict(Counter(item["priority_label"] for item in items)),
            "by_action": dict(Counter(item["recommended_action"] for item in items)),
            "notion_write": "not_allowed",
            "public_json_write": "not_allowed",
        },
        "items": items,
    }
    write_json(args.out_json, result)
    Path(args.out_md).write_text(render_markdown(result), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-db", default=str(MASTER_DB))
    parser.add_argument("--today", default=DEFAULT_TODAY.isoformat())
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    args = parser.parse_args()
    result = run(args)
    print(
        "predicted occurrence research queue: "
        f"items={result['summary']['item_count']} priorities={result['summary']['by_priority']}"
    )


if __name__ == "__main__":
    main()
