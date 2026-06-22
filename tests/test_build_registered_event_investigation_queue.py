import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import build_registered_event_investigation_queue as queue_builder


class BuildRegisteredEventInvestigationQueueTest(unittest.TestCase):
    def make_notion_db(self, path):
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE notion_events (
              page_id TEXT PRIMARY KEY,
              event_name TEXT,
              venue_ids_json TEXT,
              start_date TEXT,
              end_date TEXT,
              status TEXT,
              annual_months TEXT,
              detail TEXT,
              public_intro TEXT,
              source_url TEXT
            );
            CREATE TABLE notion_relations (
              page_id TEXT,
              related_page_id TEXT,
              property_name TEXT
            );
            CREATE TABLE notion_venues (
              page_id TEXT PRIMARY KEY,
              venue_name TEXT,
              area TEXT,
              address TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO notion_events VALUES (
              'page1', '品川区民まつり 八潮地区', '[]', '', '', '未確認',
              '', '', '', 'https://old.example.test'
            )
            """
        )
        conn.commit()
        conn.close()

    def make_master_db(self, path):
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE external_record_links (
              system TEXT,
              source_key TEXT,
              external_id TEXT,
              master_table TEXT,
              master_id TEXT
            );
            CREATE TABLE venues (
              venue_id TEXT PRIMARY KEY,
              canonical_name TEXT,
              area TEXT,
              address TEXT
            );
            CREATE TABLE event_occurrences (
              occurrence_id TEXT PRIMARY KEY,
              event_year INTEGER,
              date_start TEXT,
              date_end TEXT,
              venue_id TEXT,
              source_url TEXT
            );
            """
        )
        conn.execute("INSERT INTO venues VALUES (?, ?, ?, ?)", ("ven1", "八潮公園", "品川区", ""))
        conn.execute(
            """
            INSERT INTO event_occurrences VALUES (
              'occ1', 2026, '2026-09-20', '', 'ven1', 'https://current.example.test'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO external_record_links VALUES (
              'notion', 'events', 'page1', 'event_occurrences', 'occ1'
            )
            """
        )
        conn.commit()
        conn.close()

    def test_rdb_completed_occurrence_is_not_requeued_from_stale_notion_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            notion_db = tmp / "notion.sqlite"
            master_db = tmp / "master.sqlite"
            observed = tmp / "observed.json"
            self.make_notion_db(notion_db)
            self.make_master_db(master_db)
            observed.write_text(json.dumps({"candidates": []}), encoding="utf-8")

            queue, skipped_complete = queue_builder.build_queue(notion_db, master_db, observed)

            self.assertEqual(queue, [])
            self.assertEqual(skipped_complete, 1)


if __name__ == "__main__":
    unittest.main()
