#!/usr/bin/env python3
"""Build a read-only current-identity snapshot for B1-8 shadow review."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from master_db import MASTER_DB, file_sha256
from review_inbox_source_adapter import write_adapted_snapshot


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "data" / "review_inbox_inputs" / "historical_reference_current_identity.json"
JSON_FIELDS = {
    "source_types_json": "source_types",
    "historical_years_json": "historical_years",
    "exact_dates_json": "exact_dates",
    "year_only_evidence_json": "year_only_evidence",
    "prediction_json": "prediction",
    "source_occurrence_ids_json": "source_occurrence_ids",
}


def read_only_connection(database: Path) -> sqlite3.Connection:
    database = Path(database).resolve()
    conn = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def decoded_candidate(row: sqlite3.Row) -> dict[str, Any]:
    candidate = dict(row)
    for source_field, output_field in JSON_FIELDS.items():
        raw = candidate.pop(source_field)
        candidate[output_field] = json.loads(raw)
    candidate["auto_promote_eligible"] = bool(candidate["auto_promote_eligible"])
    candidate["current_identity"] = {
        "series_resolved": True,
        "occurrence_resolved": True,
        "occurrence_series_matches": True,
    }
    return candidate


def build_input(database: Path, *, source_locator: str = "") -> dict[str, Any]:
    database = Path(database)
    checksum = file_sha256(database)
    if not checksum:
        raise ValueError(f"historical shadow source database does not exist: {database}")
    with read_only_connection(database) as conn:
        all_rows = conn.execute(
            "SELECT candidate_id FROM historical_promotion_candidates ORDER BY candidate_id"
        ).fetchall()
        rows = conn.execute(
            """
            SELECT h.*,
                   o.series_id AS occurrence_series_id,
                   o.display_name AS occurrence_event_name,
                   o.event_year,
                   o.date_status,
                   o.lifecycle_status,
                   o.origin,
                   o.source_url,
                   COALESCE(v.canonical_name, '') AS venue
            FROM historical_promotion_candidates h
            JOIN event_series s ON s.series_id = h.target_series_id
            JOIN event_occurrences o
              ON o.occurrence_id = h.target_occurrence_id
             AND o.series_id = h.target_series_id
            LEFT JOIN venues v ON v.venue_id = COALESCE(o.venue_id, s.usual_venue_id)
            ORDER BY h.candidate_id
            """
        ).fetchall()

    all_ids = {str(row["candidate_id"]) for row in all_rows}
    candidates = [decoded_candidate(row) for row in rows]
    included_ids = {str(row["candidate_id"]) for row in candidates}
    excluded_ids = sorted(all_ids - included_ids)
    return {
        "generated_by": "build_historical_reference_shadow_input.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "database_locator": source_locator or str(database),
            "database_sha256": checksum,
            "table": "historical_promotion_candidates",
        },
        "selection": {
            "mode": "current_identity",
            "total_candidate_count": len(all_ids),
            "included_count": len(candidates),
            "excluded_count": len(excluded_ids),
            "excluded_candidate_ids": excluded_ids,
            "criteria": (
                "target_series_id and target_occurrence_id both resolve, and the "
                "occurrence belongs to target_series_id"
            ),
        },
        "candidates": candidates,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=MASTER_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source-locator", default="")
    args = parser.parse_args()
    payload = build_input(args.db, source_locator=args.source_locator)
    write_adapted_snapshot(payload, args.output)
    print(
        "historical current-identity input: "
        f"included={payload['selection']['included_count']} "
        f"excluded={payload['selection']['excluded_count']} "
        f"db_sha256={payload['source']['database_sha256']} -> {args.output}"
    )


if __name__ == "__main__":
    main()
