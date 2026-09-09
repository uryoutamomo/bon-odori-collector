import argparse
import json
import sqlite3
from unittest.mock import patch

import pytest

import report_apply.review_backlog_change_requests as scoped_retraction
from report_apply.apply_change_requests import apply_payload, run, validate_payload
from report_apply.review_backlog_change_requests import (
    _snapshot_sha256,
    evidence_snapshot,
    observed_snapshot,
)
from scripts.verify_review_backlog_application import verify
from tests.test_review_backlog_change_requests import NOW, make_connection


def add_same_title_elsewhere(conn):
    conn.execute(
        """
        INSERT INTO event_occurrences(
          occurrence_id, series_id, event_year, occurrence_sequence,
          display_name, date_status, lifecycle_status, confidence, created_at, updated_at
        ) VALUES ('occ_2', 'series_1', 2026, 1, '別開催回', 'ended', 'published', 'high', ?, ?)
        """,
        (NOW, NOW),
    )
    conn.execute(
        """
        INSERT INTO occurrence_songs(
          occurrence_song_id, occurrence_id, song_title_raw, normalized_title,
          role, evidence_status, confidence, source_count, evidence_count, created_at, updated_at
        ) VALUES ('os_same_title_elsewhere', 'occ_2', '24', '24', 'result', 'observed', 'low', 1, 1, ?, ?)
        """,
        (NOW, NOW),
    )
    conn.execute(
        """
        INSERT INTO occurrence_song_evidence_links(occurrence_song_id, evidence_id, link_status, confidence)
        VALUES ('os_same_title_elsewhere', 'ev_raw', 'linked', 0.8)
        """
    )
    conn.execute(
        """
        INSERT INTO observed_occurrences(
          observed_occurrence_id, source, raw_event_name, normalized_event_name,
          event_year, match_status, quality_status, source_payload_json, created_at, updated_at
        ) VALUES ('obs_2', 'youtube', '別開催回', '別開催回', 2026, 'matched_curated', 'matched_curated', '{}', ?, ?)
        """,
        (NOW, NOW),
    )
    conn.execute(
        """
        INSERT INTO observed_occurrence_songs(
          observed_occurrence_song_id, observed_occurrence_id, occurrence_song_id,
          raw_song_title, normalized_title, match_status, role, evidence_status,
          evidence_urls_json, source_payload_json, created_at, updated_at
        ) VALUES ('obs_same_title_elsewhere', 'obs_2', 'os_same_title_elsewhere', '24', '24',
          'unmatched', 'result', 'observed', '[]', '{}', ?, ?)
        """,
        (NOW, NOW),
    )
    conn.commit()


def scoped_request(conn, *, evidence_ids=None, observed_ids=None):
    previous = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        evidence_rows = conn.execute(
            """
            SELECT e.*, link.occurrence_song_id AS link_occurrence_song_id,
              link.evidence_id AS link_evidence_id, link.link_status AS link_status,
              link.confidence AS link_confidence, link.notes AS link_notes
            FROM occurrence_song_evidence_links link
            JOIN evidence_items e ON e.evidence_id = link.evidence_id
            WHERE link.occurrence_song_id = 'os_noise' ORDER BY e.evidence_id
            """
        ).fetchall()
        observed_rows = conn.execute(
            "SELECT * FROM observed_occurrence_songs WHERE occurrence_song_id = 'os_noise' ORDER BY observed_occurrence_song_id"
        ).fetchall()
        canonical = conn.execute(
            "SELECT * FROM occurrence_songs WHERE occurrence_song_id = 'os_noise'"
        ).fetchone()
        evidence = [
            {
                "evidence_id": row["evidence_id"], "url": row["url"],
                "snapshot_sha256": _snapshot_sha256(evidence_snapshot({
                    key: row[key] for key in row.keys() if not key.startswith("link_")
                })),
                "link_snapshot_sha256": _snapshot_sha256({
                    "occurrence_song_id": row["link_occurrence_song_id"],
                    "evidence_id": row["link_evidence_id"],
                    "link_status": row["link_status"],
                    "confidence": row["link_confidence"],
                    "notes": row["link_notes"],
                }),
            }
            for row in evidence_rows
            if evidence_ids is None or row["evidence_id"] in evidence_ids
        ]
        observed = [
            observed_snapshot(row)
            for row in observed_rows
            if observed_ids is None or row["observed_occurrence_song_id"] in observed_ids
        ]
    finally:
        conn.row_factory = previous
    return {
        "request_type": "rdb_change_requests",
        "requests": [{
            "request_id": "scoped-noise",
            "change_type": "retract_occurrence_song",
            "occurrence_id": "occ_1",
            "occurrence_song_id": "os_noise",
            "raw_song_name": "24",
            "expected_canonical_sha256": _snapshot_sha256({key: canonical[key] for key in canonical.keys()}),
            "expected_evidence": evidence,
            "expected_observed": observed,
            "review": {"reason": "曲名でない数値", "source_context": "YouTube setlist review"},
        }],
    }


def test_scoped_retraction_only_changes_the_reviewed_occurrence_and_preserves_raw_rows():
    conn = make_connection()
    add_same_title_elsewhere(conn)
    payload = scoped_request(conn)
    validate_payload(payload)

    result, issues = apply_payload(conn, payload, NOW)

    assert issues == []
    assert result["requests_unresolved"] == []
    assert conn.execute("SELECT COUNT(*) FROM occurrence_songs WHERE occurrence_song_id = 'os_noise'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM occurrence_song_evidence_links WHERE occurrence_song_id = 'os_noise'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM evidence_items WHERE evidence_id = 'ev_noise'").fetchone()[0] == 1
    assert conn.execute("SELECT raw_song_title, occurrence_song_id, matched_song_id, match_status FROM observed_occurrence_songs WHERE observed_occurrence_song_id = 'obs_noise'").fetchone() == ("24", None, None, "rejected_llm_review")
    assert conn.execute("SELECT COUNT(*) FROM occurrence_songs WHERE occurrence_song_id = 'os_target'").fetchone()[0] == 1
    assert conn.execute("SELECT occurrence_song_id, match_status FROM observed_occurrence_songs WHERE observed_occurrence_song_id = 'obs_same_title_elsewhere'").fetchone() == ("os_same_title_elsewhere", "unmatched")
    assert verify_db(conn, payload)["summary"]["verified"] is True


@pytest.mark.parametrize("column,value", [
    ("raw_song_title", "改変された生曲名"),
    ("evidence_urls_json", '["https://example.invalid/changed"]'),
    ("probability", 0.99),
    ("created_at", "2000-01-01T00:00:00+00:00"),
])
def test_verifier_rejects_any_retained_observed_field_mutation(column, value):
    conn = make_connection()
    payload = scoped_request(conn)
    apply_payload(conn, payload, NOW)
    conn.execute(
        f"UPDATE observed_occurrence_songs SET {column} = ? WHERE observed_occurrence_song_id = 'obs_noise'",
        (value,),
    )

    report = verify_db(conn, payload)

    assert report["summary"]["verified"] is False
    assert report["errors"][0]["error"] == "scoped_retraction_observed_mismatch"


def test_verifier_rejects_an_unknown_retained_observed_column(tmp_path):
    conn = make_connection()
    payload = scoped_request(conn)
    apply_payload(conn, payload, NOW)
    conn.execute("ALTER TABLE observed_occurrence_songs ADD COLUMN reviewer_note TEXT")
    conn.execute("UPDATE observed_occurrence_songs SET reviewer_note = 'mutated' WHERE observed_occurrence_song_id = 'obs_noise'")

    report = verify_db(conn, payload)

    assert report["summary"]["verified"] is False
    assert report["errors"][0]["error"] == "scoped_retraction_observed_mismatch"


@pytest.mark.parametrize("mutation", ["new_evidence", "changed_evidence", "changed_link", "changed_canonical", "changed_observed", "partial_evidence", "wrong_hash"])
def test_scoped_retraction_fails_closed_without_mutation(mutation):
    conn = make_connection()
    payload = scoped_request(conn)
    if mutation == "new_evidence":
        conn.execute("INSERT INTO evidence_items(evidence_id, platform, evidence_type, source_key, raw_json) VALUES ('ev_new', 'youtube', 'observed', 'new', '{}')")
        conn.execute("INSERT INTO occurrence_song_evidence_links VALUES ('os_noise', 'ev_new', 'linked', 0.8, '')")
    elif mutation == "changed_evidence":
        conn.execute("UPDATE evidence_items SET raw_json = '{\"changed\":true}' WHERE evidence_id = 'ev_noise'")
    elif mutation == "changed_link":
        conn.execute("UPDATE occurrence_song_evidence_links SET confidence = 0.1 WHERE occurrence_song_id = 'os_noise'")
    elif mutation == "changed_canonical":
        conn.execute("UPDATE occurrence_songs SET notes = 'changed' WHERE occurrence_song_id = 'os_noise'")
    elif mutation == "changed_observed":
        conn.execute("UPDATE observed_occurrence_songs SET source_payload_json = '{\"changed\":true}' WHERE observed_occurrence_song_id = 'obs_noise'")
    elif mutation == "partial_evidence":
        conn.execute("INSERT INTO evidence_items(evidence_id, platform, evidence_type, source_key, raw_json) VALUES ('ev_second', 'youtube', 'observed', 'second', '{}')")
        conn.execute("INSERT INTO occurrence_song_evidence_links VALUES ('os_noise', 'ev_second', 'linked', 0.8, '')")
    else:
        payload["requests"][0]["expected_evidence"][0]["snapshot_sha256"] = "0" * 64
    conn.commit()

    with pytest.raises(ValueError, match="scoped retraction refused"):
        apply_payload(conn, payload, NOW)

    assert conn.execute("SELECT COUNT(*) FROM occurrence_songs WHERE occurrence_song_id = 'os_noise'").fetchone()[0] == 1
    assert conn.execute("SELECT occurrence_song_id, match_status FROM observed_occurrence_songs WHERE observed_occurrence_song_id = 'obs_noise'").fetchone() == ("os_noise", "unmatched")


@pytest.mark.parametrize("field,value", [
    ("occurrence_id", "wrong_occurrence"),
    ("occurrence_song_id", "wrong_occurrence_song"),
    ("raw_song_name", "別の曲"),
])
def test_scoped_retraction_rejects_wrong_target_identifiers(field, value):
    conn = make_connection()
    payload = scoped_request(conn)
    payload["requests"][0][field] = value

    with pytest.raises(ValueError, match="scoped retraction refused"):
        apply_payload(conn, payload, NOW)

    assert conn.execute("SELECT COUNT(*) FROM occurrence_songs WHERE occurrence_song_id = 'os_noise'").fetchone()[0] == 1


def test_scoped_retraction_dry_run_uses_the_guarded_entry_point_and_leaves_source_db_unchanged(tmp_path):
    source = tmp_path / "source.sqlite"
    conn = make_connection()
    conn.commit()
    disk = sqlite3.connect(source)
    conn.backup(disk)
    disk.close()
    payload = scoped_request(conn)
    requests = tmp_path / "requests.json"
    requests.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with patch("report_apply.apply_change_requests.audit_db", return_value={
        "issues_by_severity": {}, "issue_count": 0, "issues_by_type": {},
    }):
        result = run(argparse.Namespace(
            requests=requests, master_db=source, out_db=tmp_path / "dry-run.sqlite",
            out_json=tmp_path / "report.json", out_md=tmp_path / "report.md", apply=False, confirm="",
        ))

    assert result["write_guard"]["db_committed"] is True
    assert sqlite3.connect(source).execute("SELECT COUNT(*) FROM occurrence_songs WHERE occurrence_song_id = 'os_noise'").fetchone()[0] == 1
    assert sqlite3.connect(tmp_path / "dry-run.sqlite").execute("SELECT COUNT(*) FROM occurrence_songs WHERE occurrence_song_id = 'os_noise'").fetchone()[0] == 0


def test_dry_run_refuses_the_source_db_as_its_output_even_via_symlink(tmp_path):
    source = tmp_path / "source.sqlite"
    conn = make_connection()
    conn.commit()
    disk = sqlite3.connect(source)
    conn.backup(disk)
    disk.close()
    payload = scoped_request(conn)
    requests = tmp_path / "requests.json"
    requests.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    alias = tmp_path / "source-alias.sqlite"
    alias.symlink_to(source)

    with pytest.raises(ValueError, match="out-db must not equal"):
        run(argparse.Namespace(
            requests=requests, master_db=source, out_db=alias,
            out_json=tmp_path / "report.json", out_md=tmp_path / "report.md", apply=False, confirm="",
        ))

    assert sqlite3.connect(source).execute("SELECT COUNT(*) FROM occurrence_songs WHERE occurrence_song_id = 'os_noise'").fetchone()[0] == 1


@pytest.mark.parametrize("caller_transaction", [False, True])
def test_scoped_retraction_locks_before_snapshot_and_preserves_caller_transaction(tmp_path, monkeypatch, caller_transaction):
    source = tmp_path / "concurrent.sqlite"
    memory = make_connection()
    memory.commit()
    disk = sqlite3.connect(source)
    memory.backup(disk)
    disk.close()
    primary = sqlite3.connect(source, timeout=0)
    concurrent = sqlite3.connect(source, timeout=0)
    primary.execute("PRAGMA foreign_keys = ON")
    concurrent.execute("PRAGMA foreign_keys = ON")
    payload = scoped_request(primary)
    blocked = []
    original = scoped_retraction._scoped_evidence

    def attempt_concurrent_add(*args):
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            concurrent.execute(
                "INSERT INTO evidence_items(evidence_id, platform, evidence_type, source_key, raw_json) VALUES ('ev_race', 'youtube', 'observed', 'race', '{}')"
            )
        blocked.append(True)
        concurrent.rollback()
        return original(*args)

    monkeypatch.setattr(scoped_retraction, "_scoped_evidence", attempt_concurrent_add)
    if caller_transaction:
        primary.execute("BEGIN")
    result, issues = apply_payload(primary, payload, NOW)

    assert blocked == [True]
    assert issues == []
    assert result["requests_unresolved"] == []
    assert primary.in_transaction is True
    if caller_transaction:
        primary.rollback()
        assert primary.execute("SELECT COUNT(*) FROM occurrence_songs WHERE occurrence_song_id = 'os_noise'").fetchone()[0] == 1
    else:
        primary.commit()
        assert primary.execute("SELECT COUNT(*) FROM occurrence_songs WHERE occurrence_song_id = 'os_noise'").fetchone()[0] == 0
    concurrent.execute("INSERT INTO evidence_items(evidence_id, platform, evidence_type, source_key, raw_json) VALUES ('ev_after', 'youtube', 'observed', 'after', '{}')")
    concurrent.commit()
    primary.close()
    concurrent.close()


def verify_db(conn, payload):
    # verify() deliberately opens a file read-only, so persist this focused fixture first.
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "verified.sqlite"
        conn.commit()
        disk = sqlite3.connect(path)
        conn.backup(disk)
        disk.close()
        return verify(path, payload)
