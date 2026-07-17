import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from master_db import init_db
from review_inbox import (
    clear_inbox_decision,
    export_inbox_json,
    inbox_rows,
    inbox_schema_version,
    migrate_inbox_schema_v2,
    payload_hash,
    record_inbox_decision,
    upsert_inbox_items,
)


def inbox_item(**overrides):
    item = {
        "kind": "current_year_confirmation",
        "domain": "開催日",
        "time_scope": "future",
        "priority_label": "P0",
        "priority_score": 100,
        "title": "丸の内de盆踊り 2026候補",
        "event_name": "丸の内de盆踊り",
        "venue": "行幸通り",
        "event_year": 2026,
        "source_id": "date_predictions",
        "source_key": "marunouchi|2026",
        "source_url": "https://example.com",
        "recommended_action": "confirm_current_date",
        "payload": {"summary": "7月最終金曜候補"},
    }
    item.update(overrides)
    return item


class ReviewInboxTest(unittest.TestCase):
    def test_new_master_database_starts_with_inbox_v2(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = init_db(Path(tmp) / "master.sqlite")
            try:
                self.assertEqual(inbox_schema_version(conn), 2)
            finally:
                conn.close()

    def test_payload_hash_is_canonical(self):
        self.assertEqual(
            payload_hash('{"b": 2, "a": 1}'),
            payload_hash('{"a":1,"b":2}'),
        )

    def test_upsert_and_export_pending_inbox_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            conn = sqlite3.connect(db)
            try:
                normalized = upsert_inbox_items(conn, [inbox_item()])
                conn.commit()
                rows = inbox_rows(conn, status="pending")
            finally:
                conn.close()

            self.assertEqual(len(normalized), 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["event_name"], "丸の内de盆踊り")
            self.assertEqual(rows[0]["time_scope"], "future")
            self.assertEqual(rows[0]["payload"]["summary"], "7月最終金曜候補")
            self.assertEqual(len(rows[0]["source_payload_hash"]), 64)

            out_json = Path(tmp) / "review_inbox.json"
            payload = export_inbox_json(db, out_json, status="pending")

            self.assertEqual(payload["source"], "master_rdb.review_inbox_items")
            self.assertEqual(payload["items"][0]["recommended_action"], "confirm_current_date")
            saved = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(saved["items"][0]["source_key"], "marunouchi|2026")

    def test_upsert_keeps_processed_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            conn = sqlite3.connect(db)
            try:
                upsert_inbox_items(conn, [inbox_item(status="pending")])
                conn.execute(
                    "UPDATE review_inbox_items SET status = 'accepted' WHERE source_key = ?",
                    ("marunouchi|2026",),
                )
                upsert_inbox_items(conn, [inbox_item(status="pending", title="再収穫された候補")])
                conn.commit()
                rows = inbox_rows(conn, status=None)
            finally:
                conn.close()

            self.assertEqual(rows[0]["status"], "accepted")
            self.assertEqual(rows[0]["title"], "再収穫された候補")

    def test_decision_round_trip_and_rebuild_preserves_lifecycle(self):
        conn = sqlite3.connect(":memory:")
        try:
            item = upsert_inbox_items(conn, [inbox_item()])[0]
            decided = record_inbox_decision(
                conn,
                item["inbox_id"],
                decision="accepted",
                decided_by="おと（Codex）",
                decision_route="change_request",
                decided_at="2026-07-17T13:00:00+00:00",
            )
            upsert_inbox_items(
                conn,
                [inbox_item(status="pending", title="再生成された候補", payload={"summary": "更新"})],
            )
            rebuilt = inbox_rows(conn, status=None)[0]
            cleared = clear_inbox_decision(conn, item["inbox_id"])
        finally:
            conn.close()

        self.assertEqual(decided["status"], "accepted")
        self.assertEqual(decided["closed_at"], "2026-07-17T13:00:00+00:00")
        self.assertEqual(rebuilt["status"], "accepted")
        self.assertEqual(rebuilt["decision"], "accepted")
        self.assertEqual(rebuilt["decision_route"], "change_request")
        self.assertEqual(rebuilt["title"], "再生成された候補")
        self.assertEqual(rebuilt["payload"]["summary"], "更新")
        self.assertEqual(cleared["status"], "pending")
        self.assertIsNone(cleared["decision"])

    def test_explicit_v1_to_v2_migration_backfills_observation_fields(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(
                """
                CREATE TABLE review_inbox_items (
                  inbox_id TEXT PRIMARY KEY, kind TEXT NOT NULL, domain TEXT NOT NULL,
                  priority_label TEXT, priority_score REAL, title TEXT NOT NULL,
                  event_name TEXT, venue TEXT, event_year INTEGER, source_id TEXT NOT NULL,
                  source_key TEXT NOT NULL, source_url TEXT, recommended_action TEXT,
                  status TEXT NOT NULL DEFAULT 'pending', payload_json TEXT NOT NULL DEFAULT '{}',
                  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                INSERT INTO review_inbox_items VALUES (
                  'inbox_legacy', 'historical_reference', '過去実績', '', 1,
                  'legacy', '', '', 2025, 'legacy', 'legacy|1', '', '', 'accepted',
                  '{"source":"legacy"}', '2026-07-16T00:00:00+00:00',
                  '2026-07-17T00:00:00+00:00'
                );
                """
            )
            self.assertEqual(inbox_schema_version(conn), 1)
            upsert_inbox_items(
                conn,
                [inbox_item(
                    inbox_id="inbox_legacy",
                    kind="historical_reference",
                    time_scope="historical",
                    source_id="legacy",
                    source_key="legacy|1",
                    status="pending",
                    title="legacy rebuilt",
                )],
            )
            legacy_row = inbox_rows(conn, status=None)[0]
            changed = migrate_inbox_schema_v2(conn)
            unchanged = migrate_inbox_schema_v2(conn)
            row = inbox_rows(conn, status=None)[0]
        finally:
            conn.close()

        self.assertTrue(changed)
        self.assertFalse(unchanged)
        self.assertEqual(legacy_row["status"], "accepted")
        self.assertEqual(legacy_row["title"], "legacy rebuilt")
        self.assertEqual(row["status"], "accepted")
        self.assertEqual(row["time_scope"], "historical")
        self.assertEqual(row["last_seen_at"], legacy_row["updated_at"])
        self.assertEqual(len(row["source_payload_hash"]), 64)


if __name__ == "__main__":
    unittest.main()
