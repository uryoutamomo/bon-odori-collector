import sqlite3
import tempfile
import unittest
from pathlib import Path

import run_place_dictionary_migration as runner
from event_model.place_dictionary import (
    MIGRATION_NAME,
    MIGRATION_VERSION,
    TOKYO_23_WARDS,
    is_tokyo23_place,
    migrate_place_dictionary,
)
import master_rdb.master_db as master_db


class PlaceDictionaryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "master.sqlite"
        conn = master_db.init_db(self.db_path)
        conn.close()

    def _place(self, conn, name, parent=None, place_type="locality"):
        place_id = master_db.stable_id("test_place", name, parent or "")
        now = master_db.now_utc()
        conn.execute(
            """INSERT INTO place_nodes(
              place_id, place_type, canonical_name, normalized_name, parent_place_id,
              source, confidence, review_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'test', 'manual', 'active', ?, ?)""",
            (place_id, place_type, name, master_db.normalize_text(name), parent, now, now),
        )
        return place_id

    def test_seeds_prefectures_and_municipalities_and_derives_tokyo23(self):
        with sqlite3.connect(self.db_path) as conn:
            report = migrate_place_dictionary(conn)
            self.assertEqual(report["prefecture_count"], 47)
            self.assertEqual(report["municipality_count"], 43)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM place_nodes WHERE place_type='prefecture'").fetchone()[0], 47)
            tokyo_ward_id = conn.execute(
                "SELECT place_id FROM place_nodes WHERE canonical_name='中央区' AND place_type='municipality'"
            ).fetchone()[0]
            self.assertTrue(is_tokyo23_place(conn, tokyo_ward_id))
            tokyo = conn.execute("SELECT place_id FROM place_nodes WHERE canonical_name='東京都'").fetchone()[0]
            kagurazaka = self._place(conn, "神楽坂", tokyo_ward_id)
            self.assertTrue(is_tokyo23_place(conn, kagurazaka))
            self.assertFalse(is_tokyo23_place(conn, tokyo))
            recorded = conn.execute("SELECT name FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,)).fetchone()[0]
            self.assertEqual(recorded, MIGRATION_NAME)

    def test_same_named_ordinance_city_ward_never_derives_tokyo23(self):
        with sqlite3.connect(self.db_path) as conn:
            migrate_place_dictionary(conn)
            hokkaido = conn.execute("SELECT place_id FROM place_nodes WHERE canonical_name='北海道'").fetchone()[0]
            sapporo = conn.execute(
                "SELECT place_id FROM place_nodes WHERE canonical_name='札幌市' AND parent_place_id=?",
                (hokkaido,),
            ).fetchone()[0]
            central = self._place(conn, "中央区", sapporo, "locality")
            self.assertFalse(is_tokyo23_place(conn, central))

    def test_cycle_in_parent_chain_is_rejected(self):
        with sqlite3.connect(self.db_path) as conn:
            migrate_place_dictionary(conn)
            tokyo = conn.execute("SELECT place_id FROM place_nodes WHERE canonical_name='東京都'").fetchone()[0]
            loop = self._place(conn, "循環地名", tokyo)
            conn.execute("UPDATE place_nodes SET parent_place_id=? WHERE place_id=?", (loop, loop))
            with self.assertRaisesRegex(ValueError, "cycle"):
                is_tokyo23_place(conn, loop)

    def test_no_subsite_type_is_accepted(self):
        with sqlite3.connect(self.db_path) as conn:
            migrate_place_dictionary(conn)
            now = master_db.now_utc()
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO place_nodes VALUES ('subsite', 'subsite', '境内', '境内', NULL, NULL, NULL, NULL, 'test', 'manual', 'active', ?, ?)",
                    (now, now),
                )


class PlaceDictionaryRunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "master.sqlite"
        conn = master_db.init_db(self.db_path)
        now = master_db.now_utc()
        conn.execute(
            "INSERT INTO venues VALUES ('ven_keep', 'curated', '既存会場', '既存会場', '江東区', '', '', '', '', '', '', NULL, NULL, 'active', ?, ?)",
            (now, now),
        )
        conn.commit()
        conn.close()

    def test_dry_run_preserves_source_and_execute_does_not_change_venues(self):
        before = self.db_path.read_bytes()
        report = runner.run(db_path=self.db_path)
        self.assertEqual(report["mode"], "dry_run")
        self.assertEqual(before, self.db_path.read_bytes())
        report = runner.run(db_path=self.db_path, execute=True, confirm=runner.CONFIRM_TEXT)
        self.assertTrue(report["verification"]["unchanged_existing_tables"])
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM venues").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM place_nodes").fetchone()[0], 90)


if __name__ == "__main__":
    unittest.main()
