"""Classify historical promotion candidates before inserting reference dates.

This is read-only. It turns the generated historical_promotion_candidates table
into an explicit review queue so auto-eligible rows are still separated from
rows with year-only evidence, missing venue, or known series ambiguity.
"""

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from master_db import MASTER_DB, connect_existing


DATA = Path("data")
OUT_JSON = DATA / "historical_promotion_candidate_review.json"
OUT_MD = DATA / "historical_promotion_candidate_review.md"


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rows(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def load_payload(value, default):
    if value in (None, ""):
        return default
    return json.loads(value)


def classify(row):
    exact_dates = load_payload(row["exact_dates_json"], {})
    year_only = load_payload(row["year_only_evidence_json"], {})
    historical_years = load_payload(row["historical_years_json"], [])
    date_counts = [len(value or []) for value in exact_dates.values()]
    insertable_years = [
        year
        for year in historical_years
        if int(year) < int(row["event_year"]) and exact_dates.get(str(year))
    ]
    reasons = []
    if row["existing_historical_reference_dates"] >= len(insertable_years) and insertable_years:
        reasons.append("historical_reference_already_recorded")
    if not row["auto_promote_eligible"]:
        reasons.append("not_auto_promote_eligible")
    if row["promotion_confidence"] != "high":
        reasons.append("low_promotion_confidence")
    if year_only:
        reasons.append("has_year_only_evidence")
    if not row["venue_id"]:
        reasons.append("target_occurrence_missing_venue")
    if any(count > 2 for count in date_counts):
        reasons.append("many_dates_in_single_year")
    if row["target_event_name"] == "郡上おどり in 青山":
        reasons.append("known_series_split_review")

    if "historical_reference_already_recorded" in reasons:
        action = "already_has_historical_reference"
    elif "known_series_split_review" in reasons or "target_occurrence_missing_venue" in reasons:
        action = "series_or_venue_review"
    elif "not_auto_promote_eligible" in reasons or "low_promotion_confidence" in reasons:
        action = "manual_review"
    elif "has_year_only_evidence" in reasons:
        action = "manual_review_year_only_evidence"
    elif "many_dates_in_single_year" in reasons:
        action = "manual_review_many_dates"
    else:
        action = "ready_to_insert_historical_reference"

    return {
        "candidate_id": row["candidate_id"],
        "event_name": row["target_event_name"],
        "target_occurrence_id": row["target_occurrence_id"],
        "target_year": row["event_year"],
        "target_date_start": row["date_start"],
        "target_date_end": row["date_end"],
        "target_date_status": row["date_status"],
        "venue": row["venue"],
        "match_score": row["match_score"],
        "promotion_confidence": row["promotion_confidence"],
        "auto_promote_eligible": bool(row["auto_promote_eligible"]),
        "historical_years": historical_years,
        "insertable_historical_years": insertable_years,
        "exact_dates": exact_dates,
        "year_only_evidence": year_only,
        "existing_historical_reference_dates": row["existing_historical_reference_dates"],
        "evidence_url_count": row["evidence_url_count"],
        "song_title_count": row["song_title_count"],
        "review_action": action,
        "review_reasons": reasons,
    }


def build(args):
    with connect_existing(args.master_db) as conn:
        candidates = rows(
            conn,
            """
            SELECT h.*, o.event_year, o.date_start, o.date_end, o.date_status,
                   o.venue_id, v.canonical_name AS venue,
                   (
                     SELECT COUNT(*)
                     FROM occurrence_dates od
                     WHERE od.occurrence_id = h.target_occurrence_id
                       AND od.date_type = 'historical_reference'
                   ) AS existing_historical_reference_dates
            FROM historical_promotion_candidates h
            JOIN event_occurrences o ON o.occurrence_id = h.target_occurrence_id
            LEFT JOIN venues v ON v.venue_id = o.venue_id
            ORDER BY h.auto_promote_eligible DESC, h.match_score DESC, h.target_event_name
            """,
        )
    review = [classify(row) for row in candidates]
    result = {
        "generated_by": "review_historical_promotion_candidates.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "read_only_historical_reference_review",
        "sources": {"master_db": str(args.master_db)},
        "summary": {
            "candidate_count": len(review),
            "actions": dict(Counter(row["review_action"] for row in review)),
        },
        "review": review,
    }
    write_json(args.out_json, result)
    Path(args.out_md).write_text(render_markdown(result), encoding="utf-8")
    return result


def render_markdown(result):
    lines = [
        "# Historical promotion candidate review",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- scope: {result['scope']}",
        f"- candidate_count: {result['summary']['candidate_count']}",
        f"- actions: {result['summary']['actions']}",
        "",
        "| action | event | years | exact dates | venue | reasons |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in result["review"]:
        exact = "; ".join(f"{year}:{','.join(dates)}" for year, dates in row["exact_dates"].items())
        lines.append(
            f"| {row['review_action']} | {row['event_name']} | "
            f"{', '.join(str(year) for year in row['historical_years'])} | {exact} | "
            f"{row.get('venue') or ''} | {', '.join(row['review_reasons'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-db", default=str(MASTER_DB))
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    args = parser.parse_args()
    result = build(args)
    print(f"historical promotion review: actions={result['summary']['actions']}")


if __name__ == "__main__":
    main()
