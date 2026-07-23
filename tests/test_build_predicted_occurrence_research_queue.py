import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path

import build_predicted_occurrence_research_queue as queue_builder


class BuildPredictedOccurrenceResearchQueueTest(unittest.TestCase):
    def make_db(self, path):
        with closing(sqlite3.connect(path)) as conn:
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
                  usual_venue_id TEXT,
                  source_url TEXT
                );
                CREATE TABLE predicted_occurrence_dates (
                  predicted_date_id TEXT PRIMARY KEY,
                  historical_candidate_id TEXT,
                  target_series_id TEXT,
                  target_occurrence_id TEXT,
                  target_event_name TEXT,
                  predicted_year INTEGER,
                  date_start TEXT,
                  date_end TEXT,
                  date_status TEXT,
                  basis_type TEXT,
                  basis_type_label TEXT,
                  rule_type TEXT,
                  basis TEXT,
                  confidence TEXT,
                  score REAL,
                  application_status TEXT,
                  source TEXT,
                  source_payload_json TEXT,
                  created_at TEXT,
                  updated_at TEXT
                );
                """
            )
            conn.execute("INSERT INTO venues VALUES (?, ?)", ("ven1", "大正大学"))
            conn.execute(
                "INSERT INTO event_series VALUES (?, ?, ?, ?, ?)",
                ("ser1", "第15回 鴨台盆踊り", "豊島区", "ven1", "https://example.test/2025"),
            )
            conn.execute(
                """
                INSERT INTO predicted_occurrence_dates VALUES (
                  'pred1', 'hist1', 'ser1', NULL, '第15回 鴨台盆踊り',
                  2026, '2026-07-04', '2026-07-05', 'predicted',
                  'weekday_based', '曜日ベース', 'weekend_near_day', '7月6日前後の週末',
                  'medium', 0.6, 'candidate_for_2026_occurrence',
                  'event_date_predictions', '{"evidence_years":[2023,2024]}',
                  'now', 'now'
                )
                """
            )
            conn.commit()

    def test_builds_p0_source_recheck_queue_for_near_prediction(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "master.sqlite"
            self.make_db(db_path)

            items = queue_builder.build_queue(db_path, today=date(2026, 6, 22))

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["priority_label"], "P0")
            self.assertEqual(items[0]["recommended_action"], "source_recheck_before_promotion")
            self.assertEqual(items[0]["evidence_years"], [2023, 2024])
            self.assertEqual(items[0]["source_review"], "current_year_third_party_source_found")
            self.assertIn("https://www.tais.ac.jp/guide/latest_news/", items[0]["checked_urls"])
            self.assertIn("https://tokyofesta.com/23ku/31077/", items[0]["checked_urls"])


if __name__ == "__main__":
    unittest.main()
