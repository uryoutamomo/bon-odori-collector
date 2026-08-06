import tempfile
import unittest
from datetime import date
from pathlib import Path

from master_rdb.master_db import init_db, now_utc, stable_id
from transition_ended_occurrences import apply_transitions, main, transition_candidates


class TransitionEndedOccurrencesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "master.sqlite"
        self.conn = init_db(self.db)
        self.now = now_utc()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def add_occurrence(self, *, name, state, start, end, tier="confirmed"):
        venue_id = stable_id("venue", name)
        series_id = stable_id("series", name)
        occurrence_id = stable_id("occurrence", name)
        self.conn.execute("INSERT INTO venues (venue_id, canonical_name, normalized_name, area, created_at, updated_at) VALUES (?, ?, ?, 'テスト区', ?, ?)", (venue_id, f"{name}会場", name, self.now, self.now))
        self.conn.execute("INSERT INTO event_series (series_id, series_key, canonical_name, normalized_name, area, created_at, updated_at) VALUES (?, ?, ?, ?, 'テスト区', ?, ?)", (series_id, name, name, name, self.now, self.now))
        self.conn.execute("""INSERT INTO event_occurrences (occurrence_id, series_id, event_year, display_name, venue_id, date_start, date_end, current_event_state, date_certainty_tier, created_at, updated_at) VALUES (?, ?, 2026, ?, ?, ?, ?, ?, ?, ?, ?)""", (occurrence_id, series_id, name, venue_id, start, end, state, tier, self.now, self.now))
        self.conn.commit()
        return occurrence_id

    def candidates(self, as_of="2026-07-31"):
        return transition_candidates(self.conn, date.fromisoformat(as_of))

    def test_past_confirmed_schedule_transitions_to_ended(self):
        occurrence_id = self.add_occurrence(name="終了済み", state="confirmed", start="2026-07-29", end="2026-07-30")
        candidates = self.candidates()
        self.assertEqual([row["occurrence_id"] for row in candidates], [occurrence_id])
        apply_transitions(self.conn, candidates, now="2026-07-31T00:00:00+00:00")
        row = self.conn.execute("SELECT current_event_state, date_certainty_tier FROM event_occurrences WHERE occurrence_id=?", (occurrence_id,)).fetchone()
        self.assertEqual(tuple(row), ("ended", "confirmed"))

    def test_schedule_ending_today_remains_confirmed(self):
        self.add_occurrence(name="本日終了", state="confirmed", start="2026-07-29", end="2026-07-31")
        self.assertEqual(self.candidates(), [])

    def test_cancelled_is_not_transitioned(self):
        self.add_occurrence(name="中止", state="cancelled", start="2026-07-29", end="2026-07-30")
        self.assertEqual(self.candidates(), [])

    def test_predicted_is_not_transitioned(self):
        self.add_occurrence(name="予測", state="predicted", start="2026-07-29", end="2026-07-30", tier="rule_predicted")
        self.assertEqual(self.candidates(), [])

    def test_empty_date_end_falls_back_to_date_start(self):
        occurrence_id = self.add_occurrence(name="終了日なし", state="confirmed", start="2026-07-30", end="")
        self.assertEqual([row["occurrence_id"] for row in self.candidates()], [occurrence_id])

    def test_main_refuses_to_create_a_missing_database(self):
        missing = Path(self.tmp.name) / "missing.sqlite"
        with self.assertRaisesRegex(SystemExit, "Master DB is missing"):
            main(["--db", str(missing), "--as-of-date", "2026-07-31"])
        self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
