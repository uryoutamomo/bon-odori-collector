import sqlite3
import tempfile
import unittest
from argparse import Namespace
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from legacy.notion_writes import sync_master_to_notion as syncer


class SyncMasterToNotionTest(unittest.TestCase):
    def make_conn(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.executescript(
            """
            CREATE TABLE venues (
              venue_id TEXT PRIMARY KEY,
              canonical_name TEXT
            );
            CREATE TABLE event_occurrences (
              occurrence_id TEXT PRIMARY KEY,
              display_name TEXT,
              event_year INTEGER,
              venue_id TEXT,
              date_start TEXT,
              date_end TEXT,
              date_status TEXT,
              lifecycle_status TEXT,
              confidence TEXT,
              source_url TEXT
            );
            CREATE TABLE event_series (
              series_id TEXT PRIMARY KEY,
              canonical_name TEXT
            );
            CREATE TABLE predicted_occurrence_dates (
              predicted_date_id TEXT PRIMARY KEY,
              target_event_name TEXT,
              predicted_year INTEGER,
              date_start TEXT,
              date_end TEXT,
              date_status TEXT,
              basis_type_label TEXT,
              rule_type TEXT,
              basis TEXT,
              confidence TEXT,
              score REAL,
              application_status TEXT,
              target_series_id TEXT,
              target_occurrence_id TEXT,
              source_payload_json TEXT
            );
            CREATE TABLE external_record_links (
              system TEXT,
              source_key TEXT,
              external_id TEXT,
              master_table TEXT,
              master_id TEXT,
              relation_kind TEXT
            );
            CREATE TABLE notion_sync_jobs (
              job_id TEXT PRIMARY KEY,
              direction TEXT,
              target_table TEXT,
              target_id TEXT,
              notion_source_key TEXT,
              notion_page_id TEXT,
              status TEXT,
              requested_by TEXT,
              requested_at TEXT,
              payload_json TEXT
            );
            """
        )
        conn.execute("INSERT INTO venues VALUES (?, ?)", ("ven1", "小山台小学校"))
        conn.execute(
            """
            INSERT INTO event_occurrences VALUES (
              'occ1', '品川区民まつり 荏原第一地区', 2026, 'ven1',
              '2026-10-10', '', 'confirmed', '未確認', 'high',
              'https://example.test/source'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO external_record_links VALUES
              ('notion', 'events', 'event-page-1', 'event_occurrences', 'occ1', 'primary'),
              ('notion', 'venues', 'venue-page-1', 'venues', 'ven1', 'primary')
            """
        )
        conn.commit()
        return conn

    def test_build_event_occurrence_update_uses_rdb_values_and_relations(self):
        conn = self.make_conn()
        job = {
            "job_id": "job1",
            "direction": "rdb_to_notion",
            "target_table": "event_occurrences",
            "target_id": "occ1",
            "notion_source_key": "events",
            "notion_page_id": "",
            "status": "pending",
            "requested_by": "test",
            "requested_at": "2026-06-21T00:00:00+00:00",
            "payload_json": '{"fields": {"状態": "確認済み"}}',
        }
        update = syncer.build_update(conn, job, None)

        self.assertEqual(update["target"]["notion_page_id"], "event-page-1")
        self.assertEqual(update["target"]["venue_notion_page_id"], "venue-page-1")
        self.assertEqual(update["properties"]["開催日"], {"date": {"start": "2026-10-10"}})
        self.assertEqual(update["properties"]["状態"], {"select": {"name": "確認済み"}})
        self.assertEqual(update["properties"]["会場"], {"relation": [{"id": "venue-page-1"}]})
        self.assertEqual(update["properties"]["情報源URL"], {"url": "https://example.test/source"})
        self.assertEqual(update["skip_reason"], "")

    def test_predicted_occurrence_date_jobs_are_review_only_with_target_context(self):
        conn = self.make_conn()
        conn.execute("INSERT INTO event_series VALUES (?, ?)", ("ser1", "歌舞伎町BON ODORI"))
        conn.execute(
            """
            INSERT INTO predicted_occurrence_dates VALUES (
              'pred1', '歌舞伎町BON ODORI', 2026, '2026-08-15', '2026-08-15',
              'predicted', '曜日ベース', 'weekday_nth', '8月第3土曜',
              'medium', 0.7, 'candidate_for_2026_occurrence', 'ser1', '',
              '{"venue": "歌舞伎町シネシティ広場"}'
            )
            """
        )
        job = {
            "job_id": "job1",
            "direction": "rdb_to_notion_dry_run",
            "target_table": "predicted_occurrence_dates",
            "target_id": "pred1",
            "notion_source_key": "events",
            "notion_page_id": "",
            "status": "pending",
            "requested_by": "test",
            "requested_at": "2026-06-21T00:00:00+00:00",
            "payload_json": '{"action": "create_predicted_2026_occurrence"}',
        }

        update = syncer.build_update(conn, job, None)

        self.assertEqual(update["target"]["event_name"], "歌舞伎町BON ODORI")
        self.assertEqual(update["target"]["date_start"], "2026-08-15")
        self.assertEqual(update["target"]["venue_name"], "歌舞伎町シネシティ広場")
        self.assertEqual(update["skip_reason"], "prediction_review_only")
        self.assertEqual(update["issues"][0]["issue_type"], "predicted_occurrence_date_jobs_are_review_only")

    def test_apply_refuses_dry_run_jobs(self):
        updates = [
            {
                "job": {
                    "job_id": "job1",
                    "direction": "rdb_to_notion_dry_run",
                    "target_table": "event_occurrences",
                },
                "skip_reason": "",
            }
        ]
        args = Namespace(
            apply=True,
            confirm=syncer.CONFIRM_PHRASE,
            allow_frozen_notion_write=True,
        )

        with self.assertRaises(ValueError):
            syncer.validate_apply(args, updates)

    def test_apply_refuses_frozen_notion_writeback_by_default(self):
        updates = [
            {
                "job": {
                    "job_id": "job1",
                    "direction": "rdb_to_notion",
                    "target_table": "event_occurrences",
                },
                "skip_reason": "",
            }
        ]
        args = Namespace(
            apply=True,
            confirm=syncer.CONFIRM_PHRASE,
            allow_frozen_notion_write=False,
        )

        with self.assertRaisesRegex(ValueError, "RDB-to-Notion write-back is frozen"):
            syncer.validate_apply(args, updates)

    def test_run_writes_dry_run_report_without_notion_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "master.sqlite"
            out_json = Path(tmp) / "out.json"
            out_md = Path(tmp) / "out.md"
            conn = self.make_conn()
            conn.execute(
                """
                INSERT INTO notion_sync_jobs VALUES (
                  'job1', 'rdb_to_notion_dry_run', 'event_occurrences', 'occ1',
                  'events', 'event-page-1', 'pending', 'test',
                  '2026-06-21T00:00:00+00:00',
                  '{"fields": {"状態": "確認済み"}}'
                )
                """
            )
            conn.commit()
            disk = sqlite3.connect(db_path)
            conn.backup(disk)
            disk.close()
            conn.close()

            result = syncer.run(
                Namespace(
                    master_db=db_path,
                    notion_snapshot_db=Path(tmp) / "missing_snapshot.sqlite",
                    out_json=out_json,
                    out_md=out_md,
                    target_table="event_occurrences",
                    job_id="",
                    requested_by="",
                    status="pending",
                    include_dry_run_jobs=True,
                    apply=False,
                    confirm="",
                )
            )

            self.assertEqual(result["summary"]["selected_jobs"], 1)
            self.assertEqual(result["summary"]["ready_jobs"], 1)
            self.assertTrue(out_json.exists())
            self.assertTrue(out_md.exists())

    def test_run_skips_when_notion_snapshot_changed_after_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "master.sqlite"
            snapshot_path = Path(tmp) / "snapshot.sqlite"
            out_json = Path(tmp) / "out.json"
            out_md = Path(tmp) / "out.md"
            conn = self.make_conn()
            conn.execute(
                """
                INSERT INTO notion_sync_jobs VALUES (
                  'job1', 'rdb_to_notion', 'event_occurrences', 'occ1',
                  'events', 'event-page-1', 'pending', 'test',
                  '2026-06-21T00:00:00+00:00',
                  '{"fields": {"状態": "確認済み"}}'
                )
                """
            )
            conn.commit()
            disk = sqlite3.connect(db_path)
            conn.backup(disk)
            disk.close()
            conn.close()

            snapshot = sqlite3.connect(snapshot_path)
            snapshot.executescript(
                """
                CREATE TABLE notion_pages (
                  page_id TEXT PRIMARY KEY,
                  last_edited_time TEXT
                );
                CREATE TABLE notion_events (
                  page_id TEXT PRIMARY KEY,
                  event_name TEXT,
                  venue_ids_json TEXT,
                  start_date TEXT,
                  end_date TEXT,
                  status TEXT,
                  source_url TEXT
                );
                CREATE TABLE notion_venues (
                  page_id TEXT PRIMARY KEY,
                  venue_name TEXT
                );
                """
            )
            snapshot.execute(
                "INSERT INTO notion_pages VALUES (?, ?)",
                ("event-page-1", "2026-06-21T00:01:00+00:00"),
            )
            snapshot.execute(
                "INSERT INTO notion_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "event-page-1",
                    "品川区民まつり 荏原第一地区",
                    '["venue-page-old"]',
                    "",
                    "",
                    "要確認",
                    "",
                ),
            )
            snapshot.execute("INSERT INTO notion_venues VALUES (?, ?)", ("venue-page-old", "旧会場"))
            snapshot.commit()
            snapshot.close()

            result = syncer.run(
                Namespace(
                    master_db=db_path,
                    notion_snapshot_db=snapshot_path,
                    out_json=out_json,
                    out_md=out_md,
                    target_table="event_occurrences",
                    job_id="",
                    requested_by="",
                    status="pending",
                    include_dry_run_jobs=False,
                    apply=False,
                    confirm="",
                )
            )

            self.assertEqual(result["summary"]["selected_jobs"], 1)
            self.assertEqual(result["summary"]["ready_jobs"], 0)
            self.assertEqual(result["summary"]["skipped_jobs"], 1)
            self.assertEqual(result["issues"][0]["issue_type"], "notion_page_changed_after_job_requested")
            self.assertTrue(result["updates"][0]["field_diffs"])

    def make_snapshot_db(self, path):
        with closing(sqlite3.connect(path)) as conn:
            conn.executescript(
                """
                CREATE TABLE notion_pages (
                  page_id TEXT PRIMARY KEY,
                  last_edited_time TEXT
                );
                CREATE TABLE notion_events (
                  page_id TEXT PRIMARY KEY,
                  event_name TEXT,
                  venue_ids_json TEXT,
                  start_date TEXT,
                  end_date TEXT,
                  status TEXT,
                  source_url TEXT
                );
                CREATE TABLE notion_venues (
                  page_id TEXT PRIMARY KEY,
                  venue_name TEXT,
                  area TEXT,
                  address TEXT,
                  access TEXT,
                  scale TEXT,
                  public_intro TEXT
                );
                """
            )
            conn.execute(
                "INSERT INTO notion_pages VALUES (?, ?)",
                ("event_page", "2026-06-01T00:00:00Z"),
            )
            conn.execute(
                "INSERT INTO notion_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("event_page", "テスト盆踊り", '["venue_page"]', "2026-07-01", "", "確認済み", ""),
            )
            conn.execute(
                "INSERT INTO notion_pages VALUES (?, ?)",
                ("venue_page", "2026-06-01T00:00:00Z"),
            )
            conn.execute(
                "INSERT INTO notion_venues VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("venue_page", "テスト公園", "テスト区", "", "", "", ""),
            )
            conn.commit()

    def test_notion_snapshot_readers_close_their_connections(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "notion_snapshot.sqlite"
            self.make_snapshot_db(db_path)

            opened_connections = []
            real_connect = sqlite3.connect

            def _tracking_connect(*args, **kwargs):
                conn = real_connect(*args, **kwargs)
                opened_connections.append(conn)
                return conn

            with patch.object(syncer.sqlite3, "connect", side_effect=_tracking_connect):
                event = syncer.notion_snapshot_event(db_path, "event_page")
                venue = syncer.notion_snapshot_venue(db_path, "venue_page")
                names = syncer.notion_venue_names(db_path, ["venue_page"])

        self.assertEqual(event["event_name"], "テスト盆踊り")
        self.assertEqual(venue["venue_name"], "テスト公園")
        self.assertEqual(names, ["テスト公園"])

        self.assertGreaterEqual(len(opened_connections), 3)
        for conn in opened_connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
