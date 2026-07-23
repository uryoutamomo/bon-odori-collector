import sqlite3
import unittest

from event_model.state_axes_migration import migrate_event_state_axes


class EventStateAxesMigrationTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript(
            """
            CREATE TABLE schema_migrations (
              version INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              applied_at TEXT NOT NULL
            );
            CREATE TABLE event_occurrences (
              occurrence_id TEXT PRIMARY KEY,
              event_year INTEGER NOT NULL,
              date_start TEXT,
              date_status TEXT NOT NULL,
              lifecycle_status TEXT NOT NULL,
              source_kind TEXT,
              source_url TEXT
            );
            INSERT INTO event_occurrences VALUES
              ('occ_public', 2026, '2026-08-01', 'confirmed', 'published', 'official_current_year', 'https://example.com'),
              ('occ_old', 2025, '2025-08-01', 'ended', 'published', 'notion_events', 'https://example.com/old');
            """
        )
        self.events = [{
            "name": "例祭",
            "venue": "例会場",
            "date": "2026-08-01",
            "date_end": None,
            "current_event_state": "confirmed",
            "date_certainty_tier": "confirmed",
        }]
        self.source_map = {
            "mapped_count": 1,
            "rows": [{
                "public_event_key": "例祭|例会場|2026-08-01|",
                "occurrence_id": "occ_public",
            }],
        }

    def tearDown(self):
        self.conn.close()

    def test_adds_and_backfills_canonical_axes(self):
        report = migrate_event_state_axes(
            self.conn, events=self.events, source_map=self.source_map
        )
        rows = dict(
            (row[0], row[1:])
            for row in self.conn.execute(
                "SELECT occurrence_id, current_event_state, date_certainty_tier FROM event_occurrences"
            )
        )
        self.assertEqual(rows["occ_public"], ("confirmed", "confirmed"))
        self.assertEqual(rows["occ_old"], ("ended", "confirmed"))
        self.assertEqual(report["public_mapped_count"], 1)
        self.assertEqual(report["invalid_row_count"], 0)

    def test_is_idempotent(self):
        migrate_event_state_axes(self.conn, events=self.events, source_map=self.source_map)
        report = migrate_event_state_axes(self.conn, events=self.events, source_map=self.source_map)
        self.assertEqual(report["columns_added"], [])
        self.assertEqual(report["changed_row_count"], 0)

    def test_trigger_rejects_invalid_combination(self):
        migrate_event_state_axes(self.conn, events=self.events, source_map=self.source_map)
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """
                UPDATE event_occurrences
                SET current_event_state='confirmed', date_certainty_tier='season_hint'
                WHERE occurrence_id='occ_public'
                """
            )

    def test_fallback_mapping_uses_explicit_target_year(self):
        self.conn.execute(
            """
            INSERT INTO event_occurrences VALUES
              ('occ_2027', 2027, NULL, 'unknown', 'published',
               'official_current_year', 'https://example.com/2027')
            """
        )
        report = migrate_event_state_axes(
            self.conn,
            events=self.events,
            source_map=self.source_map,
            target_year=2027,
        )
        row = self.conn.execute(
            """
            SELECT current_event_state, date_certainty_tier
            FROM event_occurrences WHERE occurrence_id='occ_2027'
            """
        ).fetchone()
        self.assertEqual(row, ("announced", "season_hint"))
        self.assertEqual(report["target_year"], 2027)


if __name__ == "__main__":
    unittest.main()
