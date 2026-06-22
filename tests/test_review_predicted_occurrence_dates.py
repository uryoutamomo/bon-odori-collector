import sqlite3
import unittest

import review_predicted_occurrence_dates as reviewer


class ReviewPredictedOccurrenceDatesTest(unittest.TestCase):
    def make_conn(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE venues (
              venue_id TEXT PRIMARY KEY,
              canonical_name TEXT
            );
            CREATE TABLE event_series (
              series_id TEXT PRIMARY KEY,
              canonical_name TEXT,
              area TEXT,
              usual_venue_id TEXT
            );
            CREATE TABLE event_occurrences (
              occurrence_id TEXT PRIMARY KEY,
              series_id TEXT,
              venue_id TEXT,
              display_name TEXT,
              event_year INTEGER,
              date_start TEXT,
              date_end TEXT,
              date_status TEXT,
              lifecycle_status TEXT,
              confidence TEXT,
              source_url TEXT,
              updated_at TEXT
            );
            """
        )
        conn.execute("INSERT INTO venues VALUES (?, ?)", ("ven1", "桜田公園"))
        conn.execute(
            "INSERT INTO event_series VALUES (?, ?, ?, ?)",
            ("ser_old", "第28回新橋こいち祭 盆踊り", "港区", "ven1"),
        )
        conn.execute(
            "INSERT INTO event_series VALUES (?, ?, ?, ?)",
            ("ser_curated", "新橋こいち祭", "港区", "ven1"),
        )
        conn.execute(
            """
            INSERT INTO event_occurrences VALUES (
              'occ_curated', 'ser_curated', 'ven1', '新橋こいち祭', 2026,
              '2026-07-23', '2026-07-24', 'confirmed', 'published', 'high',
              'http://www.shinbashi.net/top/koichi/2026/greeting/', 'now'
            )
            """
        )
        return conn

    def test_linked_confirmed_occurrence_can_supersede_different_series_prediction(self):
        conn = self.make_conn()
        prediction = {
            "predicted_date_id": "preddate_newbashi",
            "target_series_id": "ser_old",
            "target_occurrence_id": "occ_curated",
            "target_event_name": "第28回新橋こいち祭 盆踊り",
            "predicted_year": 2026,
            "date_start": "2026-07-23",
            "date_end": "2026-07-23",
            "application_status": "superseded_by_curated",
        }

        result = reviewer.classify_prediction(conn, prediction)

        self.assertEqual(result["review_action"], "already_superseded_by_curated")
        self.assertEqual(result["reason"], "linked_occurrence_has_different_confirmed_date")
        self.assertEqual(result["curated_occurrence"]["occurrence_id"], "occ_curated")


if __name__ == "__main__":
    unittest.main()
