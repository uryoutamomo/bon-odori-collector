import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import scripts.manual.review_public_event_override_absorption as reviewer
from scripts.manual.review_public_event_override_absorption import notion_event


def create_snapshot_db(path):
    path.parent.mkdir(parents=True, exist_ok=True)
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
              start_date TEXT,
              end_date TEXT,
              status TEXT,
              public_intro TEXT,
              source_url TEXT,
              venue_ids_json TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO notion_pages VALUES (?, ?)",
            ("page1", "2026-06-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO notion_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("page1", "テスト盆踊り", "2026-07-01", "", "確認済み", "", "", "[]"),
        )
        conn.commit()


class ReviewPublicEventOverrideAbsorptionTest(unittest.TestCase):
    def test_notion_event_returns_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "notion_snapshot.sqlite"
            create_snapshot_db(db_path)

            result = notion_event(db_path, "テスト盆踊り")

        self.assertEqual(result["event_name"], "テスト盆踊り")
        self.assertEqual(result["start_date"], "2026-07-01")

    def test_notion_event_closes_its_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "notion_snapshot.sqlite"
            create_snapshot_db(db_path)

            opened_connections = []
            real_connect = sqlite3.connect

            def _tracking_connect(*args, **kwargs):
                conn = real_connect(*args, **kwargs)
                opened_connections.append(conn)
                return conn

            with patch.object(reviewer.sqlite3, "connect", side_effect=_tracking_connect):
                notion_event(db_path, "テスト盆踊り")

        self.assertTrue(opened_connections)
        for conn in opened_connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
