import hashlib
import sqlite3
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from build_historical_reference_shadow_input import build_input
from master_db import init_db
from review_inbox_source_adapter import write_adapted_snapshot
from review_inbox_source_writer import ArtifactState, CasConflictError, SourceWriterError
from run_review_inbox_historical_shadow import CONFIRM, run_historical_shadow


JST = ZoneInfo("Asia/Tokyo")
ENABLED_ENV = {
    "REVIEW_INBOX_DUAL_WRITE_MODE": "bulk",
    "REVIEW_INBOX_CAS_PUBLISH_ENABLED": "true",
    "REVIEW_INBOX_READER_MODE": "legacy",
    "REVIEW_INBOX_LEGACY_WRITER_ENABLED": "true",
}


class FakeArtifactStore:
    def __init__(self, database):
        self.database_bytes = Path(database).read_bytes()
        self.snapshot_id = "R0"
        self.fetch_calls = 0
        self.publish_calls = 0

    def status(self):
        return ArtifactState(hashlib.sha256(self.database_bytes).hexdigest(), self.snapshot_id)

    def fetch(self, destination):
        self.fetch_calls += 1
        Path(destination).write_bytes(self.database_bytes)

    def publish(self, source, *, expected_remote_checksum):
        current = hashlib.sha256(self.database_bytes).hexdigest()
        if current != expected_remote_checksum:
            raise CasConflictError("fake conflict")
        self.publish_calls += 1
        self.database_bytes = Path(source).read_bytes()
        self.snapshot_id = f"R{self.publish_calls}"
        return self.status()


def args_for(tmp, input_path, rstart, *, suffix="first", **overrides):
    values = {
        "input": Path(input_path),
        "snapshot_out": Path(tmp) / f"snapshot-{suffix}.json",
        "report_out": Path(tmp) / f"report-{suffix}.json",
        "observation_id": f"b1-8-{suffix}",
        "expect_rstart_checksum": rstart,
        "public_today": "2026-07-18",
        "bucket": "unused-in-test",
        "prefix": "master-rdb",
        "work_dir": Path(tmp) / "work",
        "execute": True,
        "confirm": CONFIRM,
    }
    values.update(overrides)
    return Namespace(**values)


def seed_database(path):
    conn = init_db(path)
    for index, action in enumerate(
        (
            "auto_promote_historical_reference",
            "manual_review_multi_year_history",
            "manual_predicted_date_review",
        ),
        start=1,
    ):
        series_id = f"series_{index}"
        occurrence_id = f"occ_{index}"
        conn.execute(
            "INSERT INTO event_series(series_id, series_key, canonical_name, normalized_name, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, 'now', 'now')",
            (series_id, series_id, f"Event {index}", f"event {index}"),
        )
        conn.execute(
            "INSERT INTO event_occurrences(occurrence_id, series_id, event_year, display_name, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, 'now', 'now')",
            (occurrence_id, series_id, 2025 if index < 3 else 2026, f"Event {index}"),
        )
        conn.execute(
            """
            INSERT INTO historical_promotion_candidates(
              candidate_id, target_series_id, target_occurrence_id, target_event_name,
              historical_years_json, match_score, promotion_confidence,
              recommended_action, created_at, updated_at
            ) VALUES (?, ?, ?, ?, '[2023, 2024]', 80, 'high', ?, 'now', 'now')
            """,
            (f"candidate_{index}", series_id, occurrence_id, f"Event {index}", action),
        )
    conn.commit()
    conn.close()


def build_input_file(database, output):
    write_adapted_snapshot(build_input(database, source_locator="s3://test/master.sqlite"), output)


def fixed_public_digest(_database, *, today):
    return hashlib.sha256(today.encode("utf-8")).hexdigest()


class RunReviewInboxHistoricalShadowTest(unittest.TestCase):
    def test_default_off_confirm_and_four_environment_gates_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "not-read.json"
            cases = (
                (args_for(tmp, missing, "a" * 64, execute=False), {}, "execution is off"),
                (args_for(tmp, missing, "a" * 64, confirm="wrong"), ENABLED_ENV, "--confirm must be exactly"),
                (
                    args_for(tmp, missing, "a" * 64),
                    {key: value for key, value in ENABLED_ENV.items() if key != "REVIEW_INBOX_READER_MODE"},
                    "explicit environment gates",
                ),
                (
                    args_for(tmp, missing, "a" * 64),
                    {**ENABLED_ENV, "REVIEW_INBOX_DUAL_WRITE_MODE": "canary"},
                    "must be explicitly set to bulk",
                ),
                (
                    args_for(tmp, missing, "a" * 64),
                    {**ENABLED_ENV, "REVIEW_INBOX_CAS_PUBLISH_ENABLED": "false"},
                    "CAS publication is off",
                ),
            )
            for args, environ, message in cases:
                with self.subTest(message=message), self.assertRaisesRegex(SourceWriterError, message):
                    run_historical_shadow(
                        args,
                        environ=environ,
                        now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                        store_factory=lambda _args: self.fail("store must not be created"),
                    )

    def test_cron_bad_lineage_and_existing_evidence_stop_before_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "master.sqlite"
            input_path = Path(tmp) / "input.json"
            seed_database(database)
            build_input_file(database, input_path)
            checksum = hashlib.sha256(database.read_bytes()).hexdigest()

            cases = (
                (args_for(tmp, input_path, checksum), datetime(2026, 7, 18, 17, 30, tzinfo=JST), "17:20-18:00"),
                (args_for(tmp, input_path, "f" * 64), datetime(2026, 7, 18, 12, 0, tzinfo=JST), "input database checksum"),
            )
            for args, now, message in cases:
                with self.subTest(message=message), self.assertRaisesRegex(SourceWriterError, message):
                    run_historical_shadow(
                        args,
                        environ=ENABLED_ENV,
                        now=now,
                        store_factory=lambda _args: self.fail("store must not be created"),
                    )

            args = args_for(tmp, input_path, checksum)
            args.report_out.write_text("existing", encoding="utf-8")
            with self.assertRaisesRegex(SourceWriterError, "refusing to overwrite"):
                run_historical_shadow(
                    args,
                    environ=ENABLED_ENV,
                    now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                    store_factory=lambda _args: self.fail("store must not be created"),
                )

    def test_current_identity_items_publish_as_pending_review_only_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "master.sqlite"
            input_path = Path(tmp) / "input.json"
            seed_database(database)
            build_input_file(database, input_path)
            store = FakeArtifactStore(database)
            checksum = hashlib.sha256(store.database_bytes).hexdigest()

            report = run_historical_shadow(
                args_for(tmp, input_path, checksum),
                environ=ENABLED_ENV,
                now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                store_factory=lambda _args: store,
                digest_function=fixed_public_digest,
            )

            remote = Path(tmp) / "remote.sqlite"
            remote.write_bytes(store.database_bytes)
            conn = sqlite3.connect(remote)
            try:
                rows = conn.execute(
                    "SELECT kind, time_scope, status, decision, decided_by, decided_at, "
                    "closed_at, decision_route, recommended_action "
                    "FROM review_inbox_items WHERE source_id='historical_reference'"
                ).fetchall()
            finally:
                conn.close()

            self.assertEqual(len(rows), 3)
            self.assertEqual({row[0] for row in rows}, {"historical_reference"})
            self.assertEqual({row[1] for row in rows}, {"reference"})
            self.assertTrue(all(row[2] == "pending" and all(value is None for value in row[3:8]) for row in rows))
            self.assertEqual(
                {row[8] for row in rows},
                {"review_historical_reference", "research_multi_year_history", "review_prediction_queue"},
            )
            self.assertTrue(report["published"])
            self.assertTrue(report["parity"]["summary"]["parity"])
            self.assertTrue(report["audit"]["domain_table_counts_unchanged"])
            self.assertTrue(report["audit"]["public_projection_unchanged"])
            self.assertTrue(report["entrypoint"]["promotion_neutralization_checked"])
            self.assertEqual(store.publish_calls, 1)

    def test_entrypoint_rejects_forbidden_action_even_after_adapter_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "master.sqlite"
            input_path = Path(tmp) / "input.json"
            seed_database(database)
            build_input_file(database, input_path)
            checksum = hashlib.sha256(database.read_bytes()).hexdigest()
            unsafe_snapshot = {
                "source_id": "historical_reference",
                "input_sha256": "a" * 64,
                "input_size_bytes": 1,
                "item_count": 1,
                "items": [
                    {
                        "inbox_id": "inbox_unsafe",
                        "source_id": "historical_reference",
                        "source_key": "occ_unsafe",
                        "kind": "historical_reference",
                        "time_scope": "reference",
                        "recommended_action": "auto_promote_unsafe",
                    }
                ],
            }
            with patch(
                "run_review_inbox_historical_shadow.build_snapshot",
                return_value=unsafe_snapshot,
            ), self.assertRaisesRegex(SourceWriterError, "forbidden action"):
                run_historical_shadow(
                    args_for(tmp, input_path, checksum),
                    environ=ENABLED_ENV,
                    now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                    store_factory=lambda _args: self.fail("store must not be created"),
                )

    def test_removed_current_candidate_is_reported_stale_without_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "master.sqlite"
            first_input = Path(tmp) / "first-input.json"
            seed_database(database)
            build_input_file(database, first_input)
            first_store = FakeArtifactStore(database)
            run_historical_shadow(
                args_for(tmp, first_input, hashlib.sha256(first_store.database_bytes).hexdigest()),
                environ=ENABLED_ENV,
                now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                store_factory=lambda _args: first_store,
                digest_function=fixed_public_digest,
            )

            current = Path(tmp) / "current.sqlite"
            current.write_bytes(first_store.database_bytes)
            conn = sqlite3.connect(current)
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("DELETE FROM historical_promotion_candidates WHERE candidate_id='candidate_3'")
            conn.commit()
            conn.close()
            second_input = Path(tmp) / "second-input.json"
            build_input_file(current, second_input)
            second_store = FakeArtifactStore(current)

            report = run_historical_shadow(
                args_for(
                    tmp,
                    second_input,
                    hashlib.sha256(second_store.database_bytes).hexdigest(),
                    suffix="second",
                ),
                environ=ENABLED_ENV,
                now=datetime(2026, 7, 18, 12, 0, tzinfo=JST),
                store_factory=lambda _args: second_store,
                digest_function=fixed_public_digest,
            )

            self.assertEqual(report["reconciliation"]["summary"]["stale_candidate_count"], 1)
            remote = Path(tmp) / "second-remote.sqlite"
            remote.write_bytes(second_store.database_bytes)
            with sqlite3.connect(remote) as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM review_inbox_items WHERE source_id='historical_reference'"
                ).fetchone()[0]
            self.assertEqual(count, 3)


if __name__ == "__main__":
    unittest.main()
