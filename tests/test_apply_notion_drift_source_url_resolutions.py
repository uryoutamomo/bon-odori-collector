import sqlite3
import tempfile
import unittest
from contextlib import closing
from argparse import Namespace
from pathlib import Path
from unittest import mock

import apply_notion_drift_source_url_resolutions as script


class ApplyNotionDriftSourceUrlResolutionsTest(unittest.TestCase):
    def make_db(self, path):
        with closing(sqlite3.connect(path)) as conn:
            conn.executescript(
                """
                CREATE TABLE event_series (
                  series_id TEXT PRIMARY KEY,
                  canonical_name TEXT NOT NULL,
                  source_url TEXT,
                  updated_at TEXT
                );
                """
            )
            item = script.SERIES_SOURCE_URL_UPDATES[0]
            conn.execute(
                "INSERT INTO event_series VALUES (?, ?, ?, ?)",
                (item["series_id"], item["title"], item["old_source_url"], "old"),
            )
            conn.commit()

    def args(self, tmp, apply=False):
        return Namespace(
            master_db=tmp / "master.sqlite",
            out_db=tmp / "dry.sqlite",
            out_json=tmp / "out.json",
            out_md=tmp / "out.md",
            apply=apply,
            confirm=script.CONFIRM if apply else "",
        )

    def test_dry_run_updates_copy_only(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            self.make_db(tmp / "master.sqlite")

            result = script.run(self.args(tmp))

            self.assertFalse(result["applied"])
            self.assertEqual(result["summary"]["applied_count"], 1)
            item = script.SERIES_SOURCE_URL_UPDATES[0]
            with closing(sqlite3.connect(tmp / "master.sqlite")) as conn:
                original = conn.execute("SELECT source_url FROM event_series").fetchone()[0]
            with closing(sqlite3.connect(tmp / "dry.sqlite")) as conn:
                copied = conn.execute("SELECT source_url FROM event_series").fetchone()[0]
            self.assertEqual(original, item["old_source_url"])
            self.assertEqual(copied, item["new_source_url"])

    def test_apply_updates_master_and_refreshes_manifest(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            self.make_db(tmp / "master.sqlite")

            with mock.patch.object(script, "BACKUP_DIR", tmp / "backups"):
                with mock.patch.object(script, "refresh_manifest_database_state"):
                    result = script.run(self.args(tmp, apply=True))

            self.assertTrue(result["applied"])
            self.assertEqual(result["summary"]["applied_count"], 1)
            with closing(sqlite3.connect(tmp / "master.sqlite")) as conn:
                value = conn.execute("SELECT source_url FROM event_series").fetchone()[0]
            self.assertEqual(value, script.SERIES_SOURCE_URL_UPDATES[0]["new_source_url"])


if __name__ == "__main__":
    unittest.main()
