import sqlite3
import tempfile
import unittest
from pathlib import Path

import apply_curated_youtube_aliases as script
import master_rdb.master_db as master_db


class CuratedYouTubeAliasApplyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "master.sqlite"
        conn = master_db.init_db(self.db_path)
        conn.close()
        self._seed()

    def _seed(self):
        now = master_db.now_utc()
        with sqlite3.connect(self.db_path) as conn:
            for canonical in script.SEED_VENUE_ALIASES:
                conn.execute(
                    """
                    INSERT INTO venues(
                      venue_id, origin, canonical_name, normalized_name,
                      review_status, created_at, updated_at
                    ) VALUES (?, 'curated', ?, ?, 'active', ?, ?)
                    """,
                    (
                        master_db.stable_id("venue", canonical),
                        canonical,
                        master_db.normalize_text(canonical),
                        now,
                        now,
                    ),
                )
            for canonical in script.SEED_EVENT_ALIASES:
                conn.execute(
                    """
                    INSERT INTO event_series(
                      series_id, origin, series_key, canonical_name, normalized_name,
                      status, created_at, updated_at
                    ) VALUES (?, 'curated', ?, ?, ?, 'active', ?, ?)
                    """,
                    (
                        master_db.stable_id("series", canonical),
                        canonical,
                        canonical,
                        master_db.normalize_text(canonical),
                        now,
                        now,
                    ),
                )

    def alias_rows(self, table, id_column):
        with sqlite3.connect(self.db_path) as conn:
            return {
                (row[0], row[1])
                for row in conn.execute(f"SELECT {id_column}, alias FROM {table}")
            }

    def test_dry_run_writes_nothing(self):
        report = script.run(db_path=self.db_path)
        self.assertEqual(report["mode"], "dry_run")
        self.assertGreater(report["event_alias_inserted_count"], 0)
        self.assertEqual(self.alias_rows("event_series_aliases", "series_id"), set())
        self.assertEqual(self.alias_rows("venue_aliases", "venue_id"), set())

    def test_execute_requires_the_confirm_phrase(self):
        with self.assertRaises(ValueError):
            script.run(db_path=self.db_path, execute=True, confirm="nope")
        self.assertEqual(self.alias_rows("event_series_aliases", "series_id"), set())

    def test_execute_inserts_every_seed_alias(self):
        report = script.run(db_path=self.db_path, execute=True, confirm=script.CONFIRM_TEXT)
        expected_events = sum(len(values) for values in script.SEED_EVENT_ALIASES.values())
        expected_venues = sum(len(values) for values in script.SEED_VENUE_ALIASES.values())
        self.assertEqual(report["event_alias_inserted_count"], expected_events)
        self.assertEqual(report["venue_alias_inserted_count"], expected_venues)
        self.assertEqual(len(self.alias_rows("event_series_aliases", "series_id")), expected_events)
        self.assertEqual(report["verification"]["integrity_check"], "ok")
        self.assertEqual(report["verification"]["foreign_key_issue_count"], 0)

    def test_rerunning_skips_rows_that_are_already_present(self):
        script.run(db_path=self.db_path, execute=True, confirm=script.CONFIRM_TEXT)
        before = self.alias_rows("event_series_aliases", "series_id")
        report = script.run(db_path=self.db_path, execute=True, confirm=script.CONFIRM_TEXT)
        self.assertEqual(report["event_alias_inserted_count"], 0)
        self.assertEqual(report["venue_alias_inserted_count"], 0)
        self.assertTrue(
            all(row["reason"] == "already_present" for row in report["event_alias_skipped"])
        )
        self.assertEqual(self.alias_rows("event_series_aliases", "series_id"), before)

    def test_missing_canonical_name_fails_loudly(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM event_series WHERE canonical_name = '渋谷盆踊り'")
        with self.assertRaises(ValueError) as caught:
            script.run(db_path=self.db_path, execute=True, confirm=script.CONFIRM_TEXT)
        self.assertIn("渋谷盆踊り", str(caught.exception))

    def test_normalized_alias_uses_the_shared_rdb_normalizer(self):
        script.run(db_path=self.db_path, execute=True, confirm=script.CONFIRM_TEXT)
        with sqlite3.connect(self.db_path) as conn:
            stored = conn.execute(
                "SELECT normalized_alias FROM event_series_aliases WHERE alias = ?",
                ("Oku Asakusa Bon Odori",),
            ).fetchone()
        self.assertEqual(stored[0], master_db.normalize_text("Oku Asakusa Bon Odori"))


if __name__ == "__main__":
    unittest.main()
