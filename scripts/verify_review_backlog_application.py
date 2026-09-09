#!/usr/bin/env python3
"""Verify every reviewed backlog request against an applied Master RDB."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from master_rdb.master_db import normalize_text, stable_id
from report_apply.review_backlog_change_requests import (
    SCOPED_RETRACTION_OBSERVED_MUTABLE_COLUMNS,
    _snapshot_sha256,
    evidence_snapshot,
)
from report_apply.apply_change_requests import (
    HISTORICAL_SONG_EVIDENCE_MODES,
    SONG_EVIDENCE_MODES,
    _source_evidence_id,
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def scalar(conn, query, params=()):
    return conn.execute(query, params).fetchone()[0]


def _error(errors, request_id, error, **details):
    errors.append({"request_id": request_id, "error": error, **details})


def _verify_current_year_evidence(connection, request, occurrence_id, errors):
    """Verify the evidence and link every current-year schedule writer creates."""
    request_id = request["request_id"]
    evidence_id = _source_evidence_id(request)
    row = connection.execute(
        """
        SELECT e.url, e.evidence_type, e.detected_event_date, l.link_status
        FROM evidence_items e
        LEFT JOIN occurrence_evidence_links l
          ON l.evidence_id = e.evidence_id
         AND l.occurrence_id = ?
         AND l.target = 'date_and_venue'
        WHERE e.evidence_id = ?
        """,
        (occurrence_id, evidence_id),
    ).fetchone()
    expected = (request["source"]["url"], request["source"]["kind"], request["date_start"])
    actual = tuple(row[:3]) if row else None
    if actual != expected or not row or row[3] != "accepted":
        _error(
            errors,
            request_id,
            "current_year_evidence_mismatch",
            evidence_id=evidence_id,
            expected={"url": expected[0], "kind": expected[1], "date_start": expected[2], "link_status": "accepted"},
            actual={
                "url": actual[0] if actual else None,
                "kind": actual[1] if actual else None,
                "date_start": actual[2] if actual else None,
                "link_status": row[3] if row else None,
            },
        )


def _verify_current_year_occurrence(connection, request, occurrence_id, errors, *, series_id):
    """Check the durable schedule/venue contract shared by the three event actions."""
    request_id = request["request_id"]
    occurrence = connection.execute(
        """
        SELECT series_id, event_year, occurrence_sequence, venue_id, date_start, date_end,
               date_status, lifecycle_status, current_event_state, date_certainty_tier, source_kind, detail
        FROM event_occurrences WHERE occurrence_id = ?
        """,
        (occurrence_id,),
    ).fetchone()
    expected_end = request.get("date_end") or request["date_start"]
    expected = (series_id, int(request["event_year"]), 1, request["date_start"], expected_end, request["source"]["kind"])
    if not occurrence:
        _error(errors, request_id, "current_year_occurrence_missing", occurrence_id=occurrence_id)
        return
    actual = (occurrence[0], occurrence[1], occurrence[2], occurrence[4], occurrence[5], occurrence[10])
    if actual != expected:
        _error(errors, request_id, "current_year_occurrence_mismatch", occurrence_id=occurrence_id, expected=expected, actual=actual)
    if occurrence[6] not in {"confirmed", "ended"} or occurrence[7] != "published" or occurrence[8] != occurrence[6] or occurrence[9] != "confirmed":
        _error(
            errors, request_id, "current_year_occurrence_state_mismatch", occurrence_id=occurrence_id,
            actual={"date_status": occurrence[6], "lifecycle_status": occurrence[7], "current_event_state": occurrence[8], "date_certainty_tier": occurrence[9]},
        )
    if request.get("detail_replacement") is not None and occurrence[11] != request["detail_replacement"].strip():
        _error(
            errors, request_id, "detail_replacement_mismatch", occurrence_id=occurrence_id,
            expected=request["detail_replacement"].strip(), actual=occurrence[11],
        )
    if "expected_source_url" in request:
        actual_source = connection.execute("SELECT source_url FROM event_occurrences WHERE occurrence_id = ?", (occurrence_id,)).fetchone()[0]
        if actual_source != request["source"]["url"]:
            _error(errors, request_id, "representative_source_url_mismatch", expected=request["source"]["url"], actual=actual_source)
    venue = request.get("venue") or {}
    if venue.get("venue_id"):
        if occurrence[3] != venue["venue_id"]:
            _error(errors, request_id, "venue_id_mismatch", expected=venue["venue_id"], actual=occurrence[3])
    elif venue.get("name"):
        venue_row = connection.execute("SELECT canonical_name FROM venues WHERE venue_id = ?", (occurrence[3],)).fetchone()
        if not venue_row or venue_row[0] != venue["name"]:
            _error(errors, request_id, "venue_name_mismatch", expected=venue["name"], actual=venue_row[0] if venue_row else None)
    else:
        _error(errors, request_id, "venue_missing")
    _verify_current_year_evidence(connection, request, occurrence_id, errors)


def verify(db: Path, payload: dict) -> dict:
    errors = []
    counts = {}
    connection = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        for request in payload.get("requests") or []:
            change_type = request["change_type"]
            counts[change_type] = counts.get(change_type, 0) + 1
            request_id = request["request_id"]
            raw_normalized = normalize_text(request.get("raw_song_name"))
            if change_type in {"merge_song_identity", "register_song_candidate"}:
                target_normalized = normalize_text(request["target_song_name"])
                song = connection.execute(
                    "SELECT song_id, status FROM songs WHERE normalized_title = ?",
                    (target_normalized,),
                ).fetchone()
                if not song:
                    errors.append({"request_id": request_id, "error": "target_song_missing"})
                    continue
                if change_type == "register_song_candidate" and song[1] != "candidate":
                    errors.append(
                        {
                            "request_id": request_id,
                            "error": "candidate_status_mismatch",
                            "actual": song[1],
                        }
                    )
                bad_observed = scalar(
                    connection,
                    """
                    SELECT COUNT(*) FROM observed_occurrence_songs
                    WHERE normalized_title = ?
                      AND (matched_song_id != ? OR match_status NOT IN (
                        'matched_song_llm_review', 'candidate_song_llm_review'
                      ))
                    """,
                    (raw_normalized, song[0]),
                )
                if bad_observed:
                    errors.append(
                        {
                            "request_id": request_id,
                            "error": "observed_song_link_mismatch",
                            "count": bad_observed,
                        }
                    )
                if raw_normalized != target_normalized:
                    raw_canonical = scalar(
                        connection,
                        "SELECT COUNT(*) FROM occurrence_songs WHERE normalized_title = ?",
                        (raw_normalized,),
                    )
                    if raw_canonical:
                        errors.append(
                            {
                                "request_id": request_id,
                                "error": "raw_canonical_rows_remain",
                                "count": raw_canonical,
                            }
                        )
            elif change_type == "retract_occurrence_song":
                occurrence_song_id = request["occurrence_song_id"]
                canonical = scalar(
                    connection,
                    "SELECT COUNT(*) FROM occurrence_songs WHERE occurrence_song_id = ?",
                    (occurrence_song_id,),
                )
                if canonical:
                    errors.append(
                        {
                            "request_id": request_id,
                            "error": "scoped_retraction_canonical_remains",
                            "occurrence_song_id": occurrence_song_id,
                        }
                    )
                for expected in request["expected_evidence"]:
                    row = connection.execute(
                        "SELECT * FROM evidence_items WHERE evidence_id = ?",
                        (expected["evidence_id"],),
                    ).fetchone()
                    if not row or row["url"] != expected["url"] or _snapshot_sha256(evidence_snapshot(row)) != expected["snapshot_sha256"]:
                        errors.append(
                            {
                                "request_id": request_id,
                                "error": "scoped_retraction_evidence_changed",
                                "evidence_id": expected["evidence_id"],
                            }
                        )
                for expected in request["expected_observed"]:
                    row = connection.execute(
                        "SELECT * FROM observed_occurrence_songs WHERE observed_occurrence_song_id = ?",
                        (expected["observed_occurrence_song_id"],),
                    ).fetchone()
                    retained_snapshot = row and _snapshot_sha256(
                        {
                            key: row[key]
                            for key in row.keys()
                            if key not in SCOPED_RETRACTION_OBSERVED_MUTABLE_COLUMNS
                        }
                    )
                    preserved = retained_snapshot == expected["retained_fields_sha256"]
                    retracted = row and row["occurrence_song_id"] is None and row["matched_song_id"] is None and row["match_status"] == "rejected_llm_review"
                    if not preserved or not retracted:
                        errors.append(
                            {
                                "request_id": request_id,
                                "error": "scoped_retraction_observed_mismatch",
                                "observed_occurrence_song_id": expected["observed_occurrence_song_id"],
                            }
                        )
            elif change_type == "retract_song_identity":
                bad_observed = scalar(
                    connection,
                    """
                    SELECT COUNT(*) FROM observed_occurrence_songs
                    WHERE normalized_title = ? AND match_status != 'rejected_llm_review'
                    """,
                    (raw_normalized,),
                )
                canonical = scalar(
                    connection,
                    "SELECT COUNT(*) FROM occurrence_songs WHERE normalized_title = ?",
                    (raw_normalized,),
                )
                if bad_observed or canonical:
                    errors.append(
                        {
                            "request_id": request_id,
                            "error": "retraction_incomplete",
                            "bad_observed": bad_observed,
                            "canonical": canonical,
                        }
                    )
            elif change_type == "record_youtube_review_decision":
                evidence_id = stable_id(
                    "evid", "review_backlog_youtube", request["source_key"]
                )
                expected = f"reviewed_{request['decision']}"
                row = connection.execute(
                    "SELECT raw_status FROM evidence_items WHERE evidence_id = ?",
                    (evidence_id,),
                ).fetchone()
                if not row or row[0] != expected:
                    errors.append(
                        {
                            "request_id": request_id,
                            "error": "youtube_review_record_mismatch",
                            "expected": expected,
                            "actual": row[0] if row else None,
                        }
                    )
            elif change_type == "add_song_evidence":
                mode = SONG_EVIDENCE_MODES[request["evidence_mode"]]
                evidence_id = _source_evidence_id(request)
                evidence = connection.execute(
                    "SELECT detected_event_date FROM evidence_items WHERE evidence_id = ?",
                    (evidence_id,),
                ).fetchone()
                if not evidence:
                    errors.append({"request_id": request_id, "error": "song_evidence_missing"})
                    continue
                if (
                    request["evidence_mode"] in HISTORICAL_SONG_EVIDENCE_MODES
                    and evidence[0] != request.get("event_date")
                ):
                    errors.append(
                        {
                            "request_id": request_id,
                            "error": "historical_song_evidence_date_mismatch",
                            "expected": request.get("event_date"),
                            "actual": evidence[0],
                        }
                    )
                for song in request["songs"]:
                    normalized_title = normalize_text(song["title"])
                    linked = connection.execute(
                        """
                        SELECT os.inherited_from_year, l.link_status, os.probability
                        FROM occurrence_songs os
                        JOIN occurrence_song_evidence_links l
                          ON l.occurrence_song_id = os.occurrence_song_id
                        WHERE os.occurrence_id = ?
                          AND os.normalized_title = ?
                          AND os.role = ?
                          AND l.evidence_id = ?
                        """,
                        (
                            request["occurrence_id"],
                            normalized_title,
                            mode["role"],
                            evidence_id,
                        ),
                    ).fetchone()
                    if not linked or linked[1] != "accepted":
                        errors.append(
                            {
                                "request_id": request_id,
                                "error": "occurrence_song_evidence_link_missing",
                                "song": song["title"],
                            }
                        )
                    elif request["evidence_mode"] in HISTORICAL_SONG_EVIDENCE_MODES and linked[2] is None:
                        errors.append(
                            {
                                "request_id": request_id,
                                "error": "historical_song_probability_not_calibrated",
                                "song": song["title"],
                            }
                        )
                    elif request["evidence_mode"] in HISTORICAL_SONG_EVIDENCE_MODES:
                        latest_linked_year = connection.execute(
                            """
                            SELECT MAX(CAST(SUBSTR(e.detected_event_date, 1, 4) AS INTEGER))
                            FROM occurrence_songs os
                            JOIN occurrence_song_evidence_links l
                              ON l.occurrence_song_id = os.occurrence_song_id
                            JOIN evidence_items e ON e.evidence_id = l.evidence_id
                            WHERE os.occurrence_id = ?
                              AND os.normalized_title = ?
                              AND os.role = ?
                              AND l.link_status = 'accepted'
                              AND e.detected_event_date IS NOT NULL
                            """,
                            (request["occurrence_id"], normalized_title, mode["role"]),
                        ).fetchone()[0]
                        if linked[0] != latest_linked_year:
                            errors.append(
                                {
                                    "request_id": request_id,
                                    "error": "historical_song_latest_year_mismatch",
                                    "song": song["title"],
                                    "expected": latest_linked_year,
                                    "actual": linked[0],
                                }
                            )
            elif change_type == "create_event_series":
                series_key = normalize_text(request["series_name"])
                series_id = stable_id("series", series_key)
                series = connection.execute(
                    "SELECT series_id, series_key, canonical_name, source_url FROM event_series WHERE series_id = ?",
                    (series_id,),
                ).fetchone()
                expected_series = (series_id, series_key, request["series_name"], request["source"]["url"])
                if not series or tuple(series) != expected_series:
                    _error(errors, request_id, "created_series_mismatch", expected=expected_series, actual=tuple(series) if series else None)
                    continue
                occurrence_id = stable_id("occ", series_id, int(request["event_year"]), 1)
                _verify_current_year_occurrence(connection, request, occurrence_id, errors, series_id=series_id)
            elif change_type == "create_current_year_occurrence":
                series_id = request["series_id"]
                occurrence_id = stable_id("occ", series_id, int(request["event_year"]), 1)
                _verify_current_year_occurrence(connection, request, occurrence_id, errors, series_id=series_id)
            elif change_type == "confirm_current_year_date":
                target = connection.execute(
                    "SELECT series_id FROM event_occurrences WHERE occurrence_id = ?",
                    (request["occurrence_id"],),
                ).fetchone()
                _verify_current_year_occurrence(
                    connection,
                    request,
                    request["occurrence_id"],
                    errors,
                    series_id=target[0] if target else None,
                )
            else:
                errors.append({"request_id": request_id, "error": "unsupported_type"})

        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_keys:
            errors.append(
                {"request_id": "database", "error": "foreign_key_check", "count": len(foreign_keys)}
            )
    finally:
        connection.close()
    return {
        "generated_by": "scripts/verify_review_backlog_application.py",
        "database": str(db),
        "summary": {
            "request_count": sum(counts.values()),
            "change_type_counts": counts,
            "error_count": len(errors),
            "verified": not errors,
        },
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.db, load(args.requests))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report["summary"], ensure_ascii=False))
    if not report["summary"]["verified"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
