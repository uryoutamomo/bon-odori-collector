import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import rdb_builders.export_rdb_review_report as reporter
from rdb_builders.export_rdb_review_report import build_report


def create_bon_odori_db(path):
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(
            """
            CREATE TABLE events (event_id TEXT PRIMARY KEY, event_name TEXT, start_date TEXT);
            CREATE TABLE evidence_items (evidence_id TEXT PRIMARY KEY, title TEXT, url TEXT);
            CREATE TABLE event_evidence_links (
              event_id TEXT, evidence_id TEXT, link_status TEXT, link_source TEXT
            );
            CREATE TABLE song_evidence_links (
              song_title TEXT, evidence_id TEXT, link_status TEXT
            );
            CREATE TABLE review_queue (review_status TEXT, priority TEXT, evidence_id TEXT, reason TEXT);
            CREATE TABLE rdb_issues (severity TEXT, issue_type TEXT, description TEXT, payload_json TEXT);
            """
        )
        conn.commit()


class ExportRdbReviewReportTest(unittest.TestCase):
    def test_build_report_returns_empty_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "bon_odori.sqlite"
            create_bon_odori_db(db_path)

            report = build_report(db_path)

        self.assertEqual(report["status_counts"], [])
        self.assertEqual(report["matched_existing_event"], [])
        self.assertEqual(report["unmatched_songs_top"], [])
        self.assertEqual(report["issues"], [])

    def test_build_report_closes_its_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "bon_odori.sqlite"
            create_bon_odori_db(db_path)

            opened_connections = []
            real_connect = sqlite3.connect

            def _tracking_connect(*args, **kwargs):
                conn = real_connect(*args, **kwargs)
                opened_connections.append(conn)
                return conn

            with patch.object(reporter.sqlite3, "connect", side_effect=_tracking_connect):
                build_report(db_path)

        self.assertTrue(opened_connections)
        for conn in opened_connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
