import sqlite3
import tempfile
import unittest
from pathlib import Path

import run_series_alias_migration as runner
from event_model.series_alias_migration import (
    MIGRATION_NAME,
    MIGRATION_VERSION,
    migrate_event_series_aliases,
)
import master_rdb.master_db as master_db


def seed_series(conn, canonical="渋谷盆踊り"):
    now = master_db.now_utc()
    series_id = master_db.stable_id("series", canonical)
    conn.execute(
        """
        INSERT INTO event_series(
          series_id, origin, series_key, canonical_name, normalized_name,
          status, created_at, updated_at
        ) VALUES (?, 'curated', ?, ?, ?, 'active', ?, ?)
        """,
        (series_id, canonical, canonical, master_db.normalize_text(canonical), now, now),
    )
    return series_id


class SeriesAliasMigrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "master.sqlite"
        conn = master_db.init_db(self.db_path)
        conn.close()
        # Model a database created before the alias store existed.
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DROP TABLE event_series_aliases")
            self.series_id = seed_series(conn)

    def table_exists(self, conn, name):
        return bool(
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
            ).fetchone()
        )

    def test_creates_table_and_records_migration(self):
        with sqlite3.connect(self.db_path) as conn:
            report = migrate_event_series_aliases(conn)
            self.assertTrue(report["table_created"])
            self.assertEqual(report["alias_row_count"], 0)
            self.assertTrue(self.table_exists(conn, "event_series_aliases"))
            recorded = conn.execute(
                "SELECT name FROM schema_migrations WHERE version = ?", (MIGRATION_VERSION,)
            ).fetchone()
            self.assertEqual(recorded[0], MIGRATION_NAME)

    def test_is_idempotent_and_keeps_existing_rows(self):
        with sqlite3.connect(self.db_path) as conn:
            migrate_event_series_aliases(conn)
            conn.execute(
                """
                INSERT INTO event_series_aliases(
                  series_id, alias, normalized_alias, source, confidence
                ) VALUES (?, 'Shibuya Bon Odori', 'shibuyabonodori', 'test', 'manual')
                """,
                (self.series_id,),
            )
            report = migrate_event_series_aliases(conn)
            self.assertFalse(report["table_created"])
            self.assertEqual(report["alias_row_count"], 1)

    def test_requires_event_series_table(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DROP TABLE event_series")
            with self.assertRaises(ValueError):
                migrate_event_series_aliases(conn)

    def test_alias_rows_require_a_known_series(self):
        with sqlite3.connect(self.db_path) as conn:
            migrate_event_series_aliases(conn)
        # foreign_keys only takes effect outside an open transaction, so the
        # constraint is checked on a fresh connection.
        conn = sqlite3.connect(self.db_path)
        self.addCleanup(conn.close)
        conn.execute("PRAGMA foreign_keys = ON")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO event_series_aliases(
                  series_id, alias, normalized_alias, source, confidence
                ) VALUES ('ser_missing', 'x', 'x', 'test', 'manual')
                """
            )


class SeriesAliasMigrationRunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "master.sqlite"
        conn = master_db.init_db(self.db_path)
        conn.close()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DROP TABLE event_series_aliases")
            seed_series(conn)

    def stored_tables(self):
        with sqlite3.connect(self.db_path) as conn:
            return {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }

    def test_dry_run_leaves_the_database_untouched(self):
        report = runner.run(db_path=self.db_path)
        self.assertEqual(report["mode"], "dry_run")
        self.assertEqual(report["status"], "pass")
        self.assertNotIn("event_series_aliases", self.stored_tables())

    def test_execute_requires_the_confirm_phrase(self):
        with self.assertRaises(ValueError):
            runner.run(db_path=self.db_path, execute=True, confirm="nope")
        self.assertNotIn("event_series_aliases", self.stored_tables())

    def test_execute_creates_the_table(self):
        report = runner.run(
            db_path=self.db_path, execute=True, confirm=runner.CONFIRM_TEXT
        )
        self.assertEqual(report["mode"], "execute")
        self.assertEqual(report["verification"]["integrity_check"], "ok")
        self.assertEqual(report["verification"]["foreign_key_issue_count"], 0)
        self.assertIn("event_series_aliases", self.stored_tables())


if __name__ == "__main__":
    unittest.main()
