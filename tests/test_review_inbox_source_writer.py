import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from master_db import file_sha256, init_db
from review_inbox import inbox_id_for, inbox_rows, upsert_inbox_items
from review_inbox_adapters.source_writer import (
    ArtifactState,
    CasConflictError,
    SourceWriterError,
    SourceWriterFlags,
    _inbox_only_authorizer,
    _reconcile_in_transaction,
    run_source_shadow,
)


SOURCE_ID = "registered_event_investigation"


def source_item(source_key="evtinv_current", **overrides):
    item = {
        "kind": "occurrence_creation",
        "domain": "開催判断",
        "time_scope": "future",
        "priority_label": "P1",
        "priority_score": 10.0,
        "title": "盆ダンスフェスティバル",
        "event_name": "盆ダンスフェスティバル",
        "venue": "白金児童遊園",
        "event_year": 2023,
        "source_id": SOURCE_ID,
        "source_key": source_key,
        "source_url": "https://example.com/event",
        "recommended_action": "queue_for_post_cutover_research",
        "payload": {"task_id": source_key, "occurrence_id": "occ_fixture"},
    }
    item.update(overrides)
    item["inbox_id"] = inbox_id_for(item)
    return item


def adapted_snapshot(*items, selection_mode="canary"):
    return {
        "source_id": SOURCE_ID,
        "input_path": "fixture.json",
        "input_sha256": "a" * 64,
        "input_size_bytes": 123,
        "item_count": len(items),
        "selection": {"mode": selection_mode, "source_keys": [i["source_key"] for i in items]},
        "items": list(items),
    }


def public_projection_digest(path):
    with closing(sqlite3.connect(path)) as conn:
        payload = {
            "venues": conn.execute("SELECT * FROM venues ORDER BY venue_id").fetchall(),
            "occurrences": conn.execute(
                "SELECT * FROM event_occurrences ORDER BY occurrence_id"
            ).fetchall(),
        }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


class FakeArtifactStore:
    def __init__(self, database):
        self.database_bytes = Path(database).read_bytes()
        self.snapshot_id = "Rstart-snapshot"
        self.status_calls = 0
        self.fetch_calls = 0
        self.publish_calls = 0
        self.publish_expectations = []

    def status(self):
        self.status_calls += 1
        return ArtifactState(
            checksum=hashlib.sha256(self.database_bytes).hexdigest(),
            snapshot_id=self.snapshot_id,
        )

    def fetch(self, destination):
        self.fetch_calls += 1
        Path(destination).write_bytes(self.database_bytes)

    def publish(self, source, *, expected_remote_checksum):
        self.publish_calls += 1
        self.publish_expectations.append(expected_remote_checksum)
        current = hashlib.sha256(self.database_bytes).hexdigest()
        if current != expected_remote_checksum:
            raise CasConflictError("fake CAS conflict")
        self.database_bytes = Path(source).read_bytes()
        self.snapshot_id = f"snapshot-{self.publish_calls}"
        return self.status()

    def write_to(self, destination):
        Path(destination).write_bytes(self.database_bytes)


class ConflictBeforePublishStore(FakeArtifactStore):
    def status(self):
        state = super().status()
        if self.status_calls == 2:
            return ArtifactState(checksum="f" * 64, snapshot_id="concurrent")
        return state


def make_master(path):
    conn = init_db(path)
    conn.commit()
    conn.close()


class ReviewInboxSourceWriterTest(unittest.TestCase):
    def enabled_flags(self, mode="canary"):
        return SourceWriterFlags(dual_write_mode=mode, cas_publish_enabled=True)

    def test_bulk_accepts_only_atomic_reader_writer_pairs(self):
        SourceWriterFlags(
            dual_write_mode="bulk",
            cas_publish_enabled=True,
            reader_mode="legacy",
            legacy_writer_enabled=True,
        ).require_shadow_run("all")
        SourceWriterFlags(
            dual_write_mode="bulk",
            cas_publish_enabled=True,
            reader_mode="inbox",
            legacy_writer_enabled=False,
        ).require_shadow_run("all")
        for reader_mode, legacy_writer_enabled in (("legacy", False), ("inbox", True)):
            with self.subTest(reader_mode=reader_mode, legacy_writer_enabled=legacy_writer_enabled):
                with self.assertRaisesRegex(SourceWriterError, "must be paired"):
                    SourceWriterFlags(
                        dual_write_mode="bulk",
                        cas_publish_enabled=True,
                        reader_mode=reader_mode,
                        legacy_writer_enabled=legacy_writer_enabled,
                    ).require_shadow_run("all")

    def test_canary_rejects_cutover_reader_writer_pair(self):
        with self.assertRaisesRegex(SourceWriterError, "canary writes require"):
            SourceWriterFlags(
                dual_write_mode="canary",
                cas_publish_enabled=True,
                reader_mode="inbox",
                legacy_writer_enabled=False,
            ).require_shadow_run("canary")

    def test_default_off_refuses_before_touching_artifact_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            make_master(db)
            store = FakeArtifactStore(db)

            with self.assertRaisesRegex(SourceWriterError, "dual-write is off"):
                run_source_shadow(
                    store=store,
                    adapted_snapshot=adapted_snapshot(source_item()),
                    observation_id="run-default-off",
                    public_projection_digest=public_projection_digest,
                    flags=SourceWriterFlags(),
                )

        self.assertEqual(store.status_calls, 0)
        self.assertEqual(store.fetch_calls, 0)
        self.assertEqual(store.publish_calls, 0)

    def test_canary_writes_current_projection_and_cas_publishes_with_audits(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            make_master(db)
            start_checksum = file_sha256(db)
            store = FakeArtifactStore(db)
            item = source_item()

            report = run_source_shadow(
                store=store,
                adapted_snapshot=adapted_snapshot(item),
                observation_id="workflow-123",
                public_projection_digest=public_projection_digest,
                flags=self.enabled_flags(),
            )

            fetched = Path(tmp) / "fetched.sqlite"
            store.write_to(fetched)
            with closing(sqlite3.connect(fetched)) as conn:
                rows = inbox_rows(conn, status=None)

        self.assertTrue(report["published"])
        self.assertFalse(report["no_op"])
        self.assertEqual(report["parity"]["summary"]["extra_count"], 0)
        self.assertEqual(report["reconciliation"]["summary"]["unmapped_count"], 0)
        self.assertEqual(report["reconciliation"]["changed_ids"], [item["inbox_id"]])
        self.assertEqual(store.publish_expectations, [start_checksum])
        self.assertEqual(store.fetch_calls, 2)
        self.assertEqual(rows[0]["last_seen_at"], "workflow-123")
        self.assertEqual(rows[0]["status"], "pending")

    def test_reconciliation_stays_inside_callers_transaction_and_rolls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            make_master(db)
            conn = sqlite3.connect(db, isolation_level=None)
            try:
                conn.set_authorizer(_inbox_only_authorizer)
                conn.execute("BEGIN IMMEDIATE")
                _reconcile_in_transaction(
                    conn,
                    adapted_snapshot(source_item()),
                    observation_id="transaction-proof",
                )
                self.assertTrue(conn.in_transaction)
                conn.rollback()
                count = conn.execute("SELECT COUNT(*) FROM review_inbox_items").fetchone()[0]
            finally:
                conn.set_authorizer(None)
                conn.close()

        self.assertEqual(count, 0)

    def test_identical_second_run_is_noop_without_a_new_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            make_master(db)
            store = FakeArtifactStore(db)
            snapshot = adapted_snapshot(source_item())
            first = run_source_shadow(
                store=store,
                adapted_snapshot=snapshot,
                observation_id="workflow-1",
                public_projection_digest=public_projection_digest,
                flags=self.enabled_flags(),
            )
            first_snapshot = store.snapshot_id
            second = run_source_shadow(
                store=store,
                adapted_snapshot=snapshot,
                observation_id="workflow-2",
                public_projection_digest=public_projection_digest,
                flags=self.enabled_flags(),
            )

        self.assertTrue(first["published"])
        self.assertTrue(second["no_op"])
        self.assertFalse(second["published"])
        self.assertEqual(second["reconciliation"]["unchanged_ids"], [source_item()["inbox_id"]])
        self.assertEqual(store.publish_calls, 1)
        self.assertEqual(store.snapshot_id, first_snapshot)

    def test_unseen_rows_are_classified_without_delete_or_lifecycle_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            conn = init_db(db)
            pending = source_item("evtinv_stale_pending", title="pending old")
            decided = source_item("evtinv_decided", title="decided old")
            upsert_inbox_items(conn, [pending, decided])
            conn.execute(
                """
                UPDATE review_inbox_items
                SET status='accepted', decision='accepted', decided_by='reviewer',
                    decided_at='2026-07-18T00:00:00+00:00',
                    closed_at='2026-07-18T00:00:00+00:00', decision_route='no_apply'
                WHERE inbox_id=?
                """,
                (decided["inbox_id"],),
            )
            conn.commit()
            conn.close()
            store = FakeArtifactStore(db)
            current = source_item("evtinv_current")

            report = run_source_shadow(
                store=store,
                adapted_snapshot=adapted_snapshot(current),
                observation_id="workflow-reconcile",
                public_projection_digest=public_projection_digest,
                flags=self.enabled_flags(),
            )
            fetched = Path(tmp) / "fetched.sqlite"
            store.write_to(fetched)
            with closing(sqlite3.connect(fetched)) as conn:
                rows = {row["inbox_id"]: row for row in inbox_rows(conn, status=None)}

        reconciliation = report["reconciliation"]
        self.assertEqual(
            [item["inbox_id"] for item in reconciliation["stale_candidates"]],
            [pending["inbox_id"]],
        )
        self.assertEqual(
            [item["inbox_id"] for item in reconciliation["lifecycle_retained"]],
            [decided["inbox_id"]],
        )
        self.assertEqual(reconciliation["summary"]["unmapped_count"], 0)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[pending["inbox_id"]]["status"], "pending")
        self.assertEqual(rows[decided["inbox_id"]]["decision"], "accepted")
        self.assertEqual(rows[decided["inbox_id"]]["decided_by"], "reviewer")

    def test_cas_conflict_stops_before_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            make_master(db)
            store = ConflictBeforePublishStore(db)

            with self.assertRaisesRegex(CasConflictError, "remote checksum changed"):
                run_source_shadow(
                    store=store,
                    adapted_snapshot=adapted_snapshot(source_item()),
                    observation_id="workflow-conflict",
                    public_projection_digest=public_projection_digest,
                    flags=self.enabled_flags(),
                )

        self.assertEqual(store.publish_calls, 0)

    def test_public_projection_difference_stops_before_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            make_master(db)
            store = FakeArtifactStore(db)
            calls = []

            def changed_digest(_path):
                calls.append(len(calls))
                return "before" if len(calls) == 1 else "after"

            with self.assertRaisesRegex(SourceWriterError, "public projection"):
                run_source_shadow(
                    store=store,
                    adapted_snapshot=adapted_snapshot(source_item()),
                    observation_id="workflow-public-diff",
                    public_projection_digest=changed_digest,
                    flags=self.enabled_flags(),
                )

        self.assertEqual(store.publish_calls, 0)

    def test_selection_mode_must_match_canary_or_bulk_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            make_master(db)
            store = FakeArtifactStore(db)

            with self.assertRaisesRegex(SourceWriterError, "does not match"):
                run_source_shadow(
                    store=store,
                    adapted_snapshot=adapted_snapshot(source_item(), selection_mode="all"),
                    observation_id="workflow-wrong-mode",
                    public_projection_digest=public_projection_digest,
                    flags=self.enabled_flags("canary"),
                )

        self.assertEqual(store.status_calls, 0)


if __name__ == "__main__":
    unittest.main()
