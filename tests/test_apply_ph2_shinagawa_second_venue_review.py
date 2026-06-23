import sqlite3
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

import apply_ph2_shinagawa_second_venue_review as script


class ApplyPh2ShinagawaSecondVenueReviewTest(unittest.TestCase):
    def make_db(self, path):
        with sqlite3.connect(path) as conn:
            conn.executescript(
                """
                CREATE TABLE venues (
                  venue_id TEXT PRIMARY KEY,
                  canonical_name TEXT NOT NULL,
                  normalized_name TEXT NOT NULL,
                  area TEXT,
                  address TEXT,
                  source_url TEXT,
                  updated_at TEXT
                );
                CREATE TABLE venue_aliases (
                  venue_id TEXT NOT NULL,
                  alias TEXT NOT NULL,
                  normalized_alias TEXT NOT NULL,
                  source TEXT NOT NULL,
                  confidence TEXT NOT NULL,
                  PRIMARY KEY (venue_id, normalized_alias)
                );
                CREATE TABLE notion_sync_jobs (
                  job_id TEXT PRIMARY KEY,
                  requested_by TEXT
                );
                """
            )
            conn.execute(
                """
                INSERT INTO venues(
                  venue_id, canonical_name, normalized_name, area, address,
                  source_url, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    script.VENUE_ID,
                    script.CANONICAL_NAME,
                    "天妙国寺",
                    "品川区",
                    "",
                    "",
                    "2026-06-01T00:00:00+00:00",
                ),
            )
            conn.commit()

    def test_apply_is_rdb_only_and_does_not_queue_notion_sync_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db = tmp / "master.sqlite"
            self.make_db(db)

            with mock.patch.object(script, "BACKUP_DIR", tmp / "backups"):
                result = script.run(
                    Namespace(
                        master_db=db,
                        manifest=tmp / "manifest.json",
                        out_json=tmp / "review.json",
                        out_md=tmp / "review.md",
                        apply=True,
                    )
                )

            self.assertTrue(result["applied"])
            self.assertEqual(result["after"]["address"], script.CORRECT_ADDRESS)
            self.assertIn(script.ALIAS, result["after"]["aliases"])
            self.assertEqual(result["foreign_key_issues"], [])

            with sqlite3.connect(db) as conn:
                jobs = conn.execute("SELECT COUNT(*) FROM notion_sync_jobs").fetchone()[0]
            self.assertEqual(jobs, 0)


if __name__ == "__main__":
    unittest.main()
