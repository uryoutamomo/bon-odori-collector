import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
from unittest.mock import patch

import rdb_builders.build_master_rdb as builder
from rdb_builders.build_master_rdb import date_status, parse_year, rows


class BuildMasterRdbTest(unittest.TestCase):
    def test_year_and_date_status_use_explicit_run_context(self):
        self.assertEqual(parse_year("no year", default=2027), 2027)
        self.assertEqual(
            date_status("確認済み", "2027-01-01", as_of=date(2026, 12, 31)),
            "confirmed",
        )
        self.assertEqual(
            date_status("確認済み", "2027-01-01", as_of=date(2027, 1, 2)),
            "ended",
        )

    def test_rows_returns_table_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "source.sqlite"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute("CREATE TABLE example(id TEXT PRIMARY KEY, name TEXT)")
                conn.execute("INSERT INTO example VALUES ('e1', 'テスト')")
                conn.commit()

            result = rows(db_path, "example")

        self.assertEqual(result, [{"id": "e1", "name": "テスト"}])

    def test_rows_closes_its_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "source.sqlite"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute("CREATE TABLE example(id TEXT PRIMARY KEY)")
                conn.commit()

            opened_connections = []
            real_connect = sqlite3.connect

            def _tracking_connect(*args, **kwargs):
                conn = real_connect(*args, **kwargs)
                opened_connections.append(conn)
                return conn

            with patch.object(builder.sqlite3, "connect", side_effect=_tracking_connect):
                rows(db_path, "example")

        self.assertTrue(opened_connections)
        for conn in opened_connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
