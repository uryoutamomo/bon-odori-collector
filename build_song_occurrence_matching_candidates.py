"""Dry-run: propose matched_occurrence_id candidates for unmatched observed_occurrences.

Read-only against the master RDB. Reuses report_apply.event_report_helpers.find_occurrence_candidates
(the same fuzzy matcher used for interactive report review) instead of inventing a new one.
Writes a review JSON with per-threshold counts and samples; does not touch the database.
"""

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from master_rdb.master_db import MASTER_DB, connect_existing
from report_apply.event_report_helpers import find_occurrence_candidates


DATA = Path("data")
OUT_JSON = DATA / "song_occurrence_matching_candidates.json"
THRESHOLDS = [0.6, 0.7, 0.8, 0.92]


def rows(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def unmatched_observed_occurrences(conn):
    return rows(
        conn,
        """
        SELECT observed_occurrence_id, raw_event_name, raw_venue_name, event_year, quality_status
        FROM observed_occurrences
        WHERE match_status = 'unmatched'
        ORDER BY event_year, raw_venue_name, raw_event_name
        """,
    )


def build_candidates(conn, occurrences):
    results = []
    for occ in occurrences:
        candidates = find_occurrence_candidates(
            conn,
            occ["raw_event_name"],
            venue_name_hint=occ["raw_venue_name"],
            event_year=occ["event_year"],
            limit=3,
        )
        best = candidates[0] if candidates else None
        results.append(
            {
                "observed_occurrence_id": occ["observed_occurrence_id"],
                "raw_event_name": occ["raw_event_name"],
                "raw_venue_name": occ["raw_venue_name"],
                "event_year": occ["event_year"],
                "quality_status": occ["quality_status"],
                "best_candidate": (
                    {
                        "occurrence_id": best["occurrence_id"],
                        "display_name": best["display_name"],
                        "venue_name": best["venue_name"],
                        "match_score": best["match_score"],
                    }
                    if best
                    else None
                ),
                "runner_up_candidates": [
                    {
                        "occurrence_id": c["occurrence_id"],
                        "display_name": c["display_name"],
                        "venue_name": c["venue_name"],
                        "match_score": c["match_score"],
                    }
                    for c in candidates[1:3]
                ],
            }
        )
    return results


def threshold_summary(results, thresholds):
    summary = {}
    for threshold in thresholds:
        matched = [
            r for r in results if r["best_candidate"] and r["best_candidate"]["match_score"] >= threshold
        ]
        by_quality = Counter(r["quality_status"] for r in matched)
        summary[str(threshold)] = {
            "matched_count": len(matched),
            "by_quality_status": dict(by_quality),
        }
    return summary


def sample_rows(results, threshold, next_threshold, limit=15):
    """Rows whose best-candidate score falls in [threshold, next_threshold) — the marginal band a
    threshold decision actually affects, for spot-checking precision at the boundary."""
    band = [
        r
        for r in results
        if r["best_candidate"]
        and threshold <= r["best_candidate"]["match_score"] < (next_threshold or 1.01)
    ]
    return band[:limit]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(MASTER_DB))
    parser.add_argument("--out-json", default=str(OUT_JSON))
    args = parser.parse_args()

    with connect_existing(args.db) as conn:
        occurrences = unmatched_observed_occurrences(conn)
        results = build_candidates(conn, occurrences)

    no_candidate_count = sum(1 for r in results if r["best_candidate"] is None)
    summary = threshold_summary(results, THRESHOLDS)
    bands = {}
    for i, threshold in enumerate(THRESHOLDS):
        next_threshold = THRESHOLDS[i + 1] if i + 1 < len(THRESHOLDS) else None
        bands[f"{threshold}-{next_threshold or '1.0'}"] = sample_rows(results, threshold, next_threshold)

    output = {
        "generated_by": "build_song_occurrence_matching_candidates.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": str(args.db),
        "unmatched_total": len(occurrences),
        "no_candidate_found": no_candidate_count,
        "threshold_summary": summary,
        "band_samples_for_spot_check": bands,
        "all_results": results,
    }
    Path(args.out_json).write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "song occurrence matching candidates: "
        f"unmatched={len(occurrences)} no_candidate={no_candidate_count} "
        f"summary={summary}"
    )


if __name__ == "__main__":
    main()
