#!/usr/bin/env python3
"""Verify every reviewed backlog request against an applied Master RDB."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from master_rdb.master_db import normalize_text, stable_id
from report_apply.apply_change_requests import (
    HISTORICAL_SONG_EVIDENCE_MODES,
    SONG_EVIDENCE_MODES,
    _source_evidence_id,
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def scalar(conn, query, params=()):
    return conn.execute(query, params).fetchone()[0]


def verify(db: Path, payload: dict) -> dict:
    errors = []
    counts = {}
    connection = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
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
