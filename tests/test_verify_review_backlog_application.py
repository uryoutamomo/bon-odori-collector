import sqlite3

import pytest

from master_rdb.master_db import SCHEMA, stable_id
from report_apply.apply_change_requests import apply_payload, validate_payload
from scripts.verify_review_backlog_application import verify


NOW = "2026-09-01T00:00:00+00:00"


def connection():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    conn.execute(
        """
        INSERT INTO event_series(
          series_id, series_key, canonical_name, normalized_name,
          annual_months_json, status, created_at, updated_at
        ) VALUES ('existing_series', 'existing', '既存盆踊り', '既存盆踊り', '[]', 'active', ?, ?)
        """,
        (NOW, NOW),
    )
    conn.execute(
        """
        INSERT INTO event_series(
          series_id, series_key, canonical_name, normalized_name,
          annual_months_json, status, created_at, updated_at
        ) VALUES ('confirm_series', 'confirm', '確認済み盆踊り', '確認済み盆踊り', '[]', 'active', ?, ?)
        """,
        (NOW, NOW),
    )
    conn.execute(
        """
        INSERT INTO event_occurrences(
          occurrence_id, series_id, event_year, occurrence_sequence, display_name,
          date_status, lifecycle_status, confidence, created_at, updated_at
        ) VALUES ('existing_occurrence', 'confirm_series', 2026, 1, '確認済み盆踊り',
                  'unknown', 'draft', 'unknown', ?, ?)
        """,
        (NOW, NOW),
    )
    conn.execute(
        """
        INSERT INTO venues(venue_id, canonical_name, normalized_name, review_status, created_at, updated_at)
        VALUES ('known_venue', '指定会場', '指定会場', 'active', ?, ?)
        """,
        (NOW, NOW),
    )
    return conn


def payload():
    return {
        "request_type": "rdb_change_requests",
        "requests": [
            {
                "request_id": "new_series",
                "change_type": "create_event_series",
                "series_name": "新規盆踊り",
                "display_name": "新規盆踊り",
                "event_year": 2026,
                "date_start": "2026-07-20",
                "venue": {"name": "新規会場", "area": "中央区"},
                "source": {"url": "https://example.test/new", "kind": "official_current_year"},
            },
            {
                "request_id": "new_occurrence",
                "change_type": "create_current_year_occurrence",
                "series_id": "existing_series",
                "display_name": "既存盆踊り 2026",
                "event_year": 2026,
                "date_start": "2026-07-21",
                "date_end": "2026-07-22",
                "venue": {"venue_id": "known_venue"},
                "source": {"url": "https://example.test/occurrence", "kind": "organizer_current_year"},
            },
            {
                "request_id": "confirm_existing",
                "change_type": "confirm_current_year_date",
                "occurrence_id": "existing_occurrence",
                "event_year": 2026,
                "date_start": "2026-08-01",
                "venue": {"name": "確認会場"},
                "source": {"url": "https://example.test/confirm", "kind": "trusted_x_current_year"},
                "detail_replacement": "2026年の公式日程を確認。",
                "expected_detail_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            },
        ],
    }


def verify_db(conn, requests):
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "verified.sqlite"
        conn.commit()
        disk = sqlite3.connect(path)
        conn.backup(disk)
        disk.close()
        return verify(path, requests)


def applied_fixture():
    conn = connection()
    requests = payload()
    validate_payload(requests)
    applied, issues = apply_payload(conn, requests, NOW)
    assert issues == []
    assert len(applied["requests_applied"]) == 3
    return conn, requests


def test_verifier_accepts_all_current_year_event_change_types():
    conn, requests = applied_fixture()

    report = verify_db(conn, requests)

    assert report["summary"]["verified"] is True


def test_verifier_checks_explicit_representative_source_replacement():
    conn, requests = applied_fixture()
    requests["requests"][2]["expected_source_url"] = "https://example.test/last-year"
    assert verify_db(conn, requests)["summary"]["verified"] is True
    conn.execute("UPDATE event_occurrences SET source_url='https://example.test/last-year' WHERE occurrence_id='existing_occurrence'")
    report = verify_db(conn, requests)
    assert report["summary"]["verified"] is False
    assert any(row["error"] == "representative_source_url_mismatch" for row in report["errors"])


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("wrong_year", "current_year_occurrence_mismatch"),
        ("wrong_date", "current_year_occurrence_mismatch"),
        ("wrong_venue", "venue_name_mismatch"),
        ("wrong_source_kind", "current_year_occurrence_mismatch"),
        ("missing_evidence", "current_year_evidence_mismatch"),
        ("missing_evidence_item", "current_year_evidence_mismatch"),
        ("missing_target", "current_year_occurrence_missing"),
        ("wrong_state", "current_year_occurrence_state_mismatch"),
        ("wrong_detail_replacement", "detail_replacement_mismatch"),
    ],
)
def test_verifier_rejects_current_year_confirmation_mutations(mutation, expected_error):
    conn, requests = applied_fixture()
    if mutation == "wrong_year":
        conn.execute("UPDATE event_occurrences SET event_year = 2025 WHERE occurrence_id = 'existing_occurrence'")
    elif mutation == "wrong_date":
        conn.execute("UPDATE event_occurrences SET date_end = '2026-08-02' WHERE occurrence_id = 'existing_occurrence'")
    elif mutation == "wrong_venue":
        conn.execute("UPDATE venues SET canonical_name = '別会場' WHERE normalized_name = '確認会場'")
    elif mutation == "wrong_source_kind":
        conn.execute("UPDATE event_occurrences SET source_kind = 'historical_occurrence_video' WHERE occurrence_id = 'existing_occurrence'")
    elif mutation == "missing_evidence":
        conn.execute(
            "DELETE FROM occurrence_evidence_links WHERE occurrence_id = 'existing_occurrence' AND target = 'date_and_venue'"
        )
    elif mutation == "missing_evidence_item":
        conn.execute(
            "DELETE FROM occurrence_evidence_links WHERE occurrence_id = 'existing_occurrence' AND target = 'date_and_venue'"
        )
        conn.execute(
            "DELETE FROM evidence_items WHERE url = 'https://example.test/confirm'"
        )
    elif mutation == "missing_target":
        conn.commit()
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DELETE FROM event_occurrences WHERE occurrence_id = 'existing_occurrence'")
    elif mutation == "wrong_state":
        conn.execute("UPDATE event_occurrences SET lifecycle_status = 'draft' WHERE occurrence_id = 'existing_occurrence'")
    else:
        conn.execute("UPDATE event_occurrences SET detail = '古い日程' WHERE occurrence_id = 'existing_occurrence'")

    report = verify_db(conn, requests)

    assert report["summary"]["verified"] is False
    assert expected_error in {error["error"] for error in report["errors"]}


def test_verifier_rejects_generated_series_or_occurrence_id_mismatch():
    conn, requests = applied_fixture()
    series_id = stable_id("series", "新規盆踊り")
    occurrence_id = stable_id("occ", series_id, 2026, 1)
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("UPDATE event_occurrences SET occurrence_id = ? WHERE occurrence_id = ?", ("wrong_occurrence", occurrence_id))

    report = verify_db(conn, requests)

    assert report["summary"]["verified"] is False
    assert "current_year_occurrence_missing" in {error["error"] for error in report["errors"]}
