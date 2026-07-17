import sqlite3
import tempfile
import unittest
from pathlib import Path

from compare_public_projection_sources import build_report


class ComparePublicProjectionSourcesTest(unittest.TestCase):
    def make_db(self, path):
        with sqlite3.connect(path) as conn:
            conn.executescript(
                """
                CREATE TABLE venues (
                  venue_id TEXT PRIMARY KEY,
                  canonical_name TEXT
                );
                CREATE TABLE event_series (
                  series_id TEXT PRIMARY KEY,
                  canonical_name TEXT,
                  annual_months_json TEXT,
                  schedule_rule_type TEXT,
                  schedule_rule_detail TEXT,
                  usual_venue_id TEXT
                );
                CREATE TABLE event_occurrences (
                  occurrence_id TEXT PRIMARY KEY,
                  series_id TEXT,
                  event_year INTEGER,
                  display_name TEXT,
                  venue_id TEXT,
                  date_start TEXT,
                  date_end TEXT,
                  lifecycle_status TEXT,
                  origin TEXT
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
                CREATE TABLE occurrence_dates (
                  occurrence_date_id TEXT PRIMARY KEY,
                  occurrence_id TEXT,
                  date_start TEXT,
                  date_end TEXT,
                  date_type TEXT,
                  confidence TEXT,
                  source_evidence_id TEXT,
                  basis TEXT,
                  created_at TEXT
                );
                CREATE TABLE evidence_items (
                  evidence_id TEXT PRIMARY KEY,
                  title TEXT,
                  url TEXT
                );
                """
            )
            conn.execute("INSERT INTO venues VALUES (?, ?)", ("ven1", "中央公園"))
            conn.execute(
                "INSERT INTO event_series VALUES (?, ?, ?, ?, ?, ?)",
                ("ser1", "中央公園盆踊り", "[7]", "weekday_last", "7月下旬", "ven1"),
            )
            conn.execute(
                "INSERT INTO event_occurrences VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("occ1", "ser1", 2026, "中央公園盆踊り", "ven1", None, None, "draft", "curated"),
            )
            conn.execute(
                """
                INSERT INTO predicted_occurrence_dates VALUES (
                  'pred1', 'hist1', 'ser1', 'occ1', '中央公園盆踊り',
                  2026, '2026-07-31', '', 'predicted',
                  'weekday_based', '曜日ベース', 'weekday_last', '7月下旬の最終金曜',
                  'medium', 0.7, 'candidate_for_2026_occurrence',
                  'event_date_predictions', '{"evidence_years":[2024,2025]}',
                  'now', 'now'
                )
                """
            )
            conn.execute(
                """
                INSERT INTO occurrence_dates VALUES (
                  'od1', 'occ1', '2025-07-25', '', 'historical_reference',
                  'medium', NULL, '{}', 'now'
                )
                """
            )
            conn.commit()

    def test_report_matches_public_projection_fields_to_rdb_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "master.sqlite"
            self.make_db(db_path)
            events = [
                {
                    "name": "中央公園盆踊り",
                    "venue": "中央公園",
                    "public_category": "recurring_last_year",
                    "display_tier": "historical_reference",
                    "date_prediction": {
                        "date": "2026-07-31",
                        "date_end": "",
                        "confidence": "medium",
                        "rule_type": "weekday_last",
                        "basis": "7月下旬の最終金曜",
                    },
                    "historical_reference": {
                        "last_seen_dates": ["2025-07-25"],
                    },
                    "season_hint": {
                        "months": [7],
                    },
                }
            ]

            report = build_report(events, db_path)

            self.assertEqual(report["blocking_row_count"], 0)
            self.assertEqual(report["summary"]["prediction:match"], 1)
            self.assertEqual(report["summary"]["historical:match"], 1)
            self.assertEqual(report["summary"]["season:match"], 1)

    def test_report_flags_missing_rdb_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "master.sqlite"
            self.make_db(db_path)
            events = [
                {
                    "name": "別イベント",
                    "venue": "別会場",
                    "date_prediction": {"date": "2026-08-01"},
                }
            ]

            report = build_report(events, db_path)

            self.assertEqual(report["blocking_row_count"], 1)
            self.assertEqual(report["summary"]["prediction:missing_rdb_source"], 1)

    def test_report_uses_source_map_occurrence_id_before_fuzzy_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "master.sqlite"
            self.make_db(db_path)
            events = [
                {
                    "name": "公開用に少し違う名前",
                    "venue": "中央公園",
                    "date": "",
                    "date_end": "",
                    "public_category": "recurring_last_year",
                    "date_prediction": {
                        "date": "2026-07-31",
                        "date_end": "",
                        "confidence": "medium",
                        "rule_type": "weekday_last",
                        "basis": "7月下旬の最終金曜",
                    },
                    "historical_reference": {
                        "last_seen_dates": ["2025-07-25"],
                    },
                    "season_hint": {
                        "months": [7],
                    },
                }
            ]
            source_map = {
                "公開用に少し違う名前|中央公園||": {
                    "occurrence_id": "occ1",
                }
            }

            report = build_report(events, db_path, source_map=source_map)

            self.assertEqual(report["blocking_row_count"], 0)
            self.assertEqual(report["source_counts"]["sidecar_hits"], 1)
            self.assertEqual(report["summary"]["prediction:match"], 1)
            self.assertEqual(report["summary"]["historical:match"], 1)
            self.assertEqual(report["summary"]["season:match"], 1)

    def test_historical_match_uses_any_source_for_same_occurrence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "master.sqlite"
            self.make_db(db_path)
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO occurrence_dates VALUES (
                      'od_old', 'occ1', '2024-07-26', '', 'historical_reference',
                      'medium', NULL, '{}', 'now'
                    )
                    """
                )
                conn.commit()
            events = [
                {
                    "name": "公開用に少し違う名前",
                    "venue": "中央公園",
                    "date": "",
                    "date_end": "",
                    "historical_reference": {
                        "last_seen_dates": ["2025-07-25"],
                    },
                }
            ]
            source_map = {
                "公開用に少し違う名前|中央公園||": {
                    "occurrence_id": "occ1",
                }
            }

            report = build_report(events, db_path, source_map=source_map)

            self.assertEqual(report["blocking_row_count"], 0)
            self.assertEqual(report["summary"]["historical:match"], 1)


if __name__ == "__main__":
    unittest.main()
