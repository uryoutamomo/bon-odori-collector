import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import master_rdb.master_db as master_db
from master_rdb.master_db import file_sha256, refresh_manifest_database_state


class MasterDbManifestTest(unittest.TestCase):
    def test_refresh_manifest_database_state_preserves_source_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db_path = tmp / "master.sqlite"
            manifest_path = tmp / "manifest.json"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute("CREATE TABLE example(id TEXT PRIMARY KEY)")
                conn.execute("INSERT INTO example VALUES ('one')")
                conn.commit()
            manifest_path.write_text(
                json.dumps(
                    {
                        "source_checksums": {"notion_db": "abc"},
                        "post_build_steps": ["build_registered_event_investigation_queue.py"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            manifest = refresh_manifest_database_state(
                db_path,
                manifest_path,
                updated_at="2026-06-22T00:00:00+00:00",
            )

            self.assertEqual(manifest["source_checksums"], {"notion_db": "abc"})
            self.assertEqual(manifest["table_counts"]["example"], 1)
            self.assertEqual(manifest["database_checksum"], file_sha256(db_path))
            self.assertEqual(manifest["database_updated_at"], "2026-06-22T00:00:00+00:00")

    def test_refresh_manifest_database_state_closes_its_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db_path = tmp / "master.sqlite"
            manifest_path = tmp / "manifest.json"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute("CREATE TABLE example(id TEXT PRIMARY KEY)")
                conn.commit()

            opened_connections = []
            real_connect = sqlite3.connect

            def _tracking_connect(*args, **kwargs):
                conn = real_connect(*args, **kwargs)
                opened_connections.append(conn)
                return conn

            with patch.object(master_db.sqlite3, "connect", side_effect=_tracking_connect):
                refresh_manifest_database_state(db_path, manifest_path)

            self.assertTrue(opened_connections)
            for conn in opened_connections:
                with self.assertRaises(sqlite3.ProgrammingError):
                    conn.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
