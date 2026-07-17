import sqlite3
import tempfile
import unittest
from pathlib import Path

from build_public_historical_reference_change_requests import build_payload
from master_db import normalize_text


class BuildPublicHistoricalReferenceChangeRequestsTest(unittest.TestCase):
    def make_db(self, path, *, existing_historical=False):
        with sqlite3.connect(path) as conn:
            conn.executescript(
                """
                CREATE TABLE venues (
                  venue_id TEXT PRIMARY KEY,
                  canonical_name TEXT,
                  normalized_name TEXT,
                  review_status TEXT
                );
                CREATE TABLE event_series (
                  series_id TEXT PRIMARY KEY,
                  canonical_name TEXT,
                  normalized_name TEXT,
                  source_url TEXT
                );
                CREATE TABLE event_occurrences (
                  occurrence_id TEXT PRIMARY KEY,
                  series_id TEXT,
                  event_year INTEGER,
                  display_name TEXT,
                  venue_id TEXT,
                  date_start TEXT,
                  date_end TEXT,
                  date_status TEXT,
                  lifecycle_status TEXT,
                  confidence TEXT,
                  source_kind TEXT,
                  source_url TEXT
                );
                CREATE TABLE occurrence_dates (
                  occurrence_date_id TEXT PRIMARY KEY,
                  occurrence_id TEXT,
                  date_start TEXT,
                  date_end TEXT,
                  date_type TEXT
                );
                CREATE TABLE evidence_items (
                  evidence_id TEXT PRIMARY KEY,
                  title TEXT,
                  url TEXT
                );
                CREATE TABLE occurrence_evidence_links (
                  occurrence_id TEXT,
                  evidence_id TEXT,
                  confidence REAL
                );
                """
            )
            conn.execute(
                "INSERT INTO venues VALUES (?, ?, ?, ?)",
                ("ven1", "中央公園", normalize_text("中央公園"), "active"),
            )
            conn.execute(
                "INSERT INTO event_series VALUES (?, ?, ?, ?)",
                ("ser1", "中央公園盆踊り", normalize_text("中央公園盆踊り"), None),
            )
            conn.execute(
                "INSERT INTO event_occurrences VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("occ1", "ser1", 2026, "中央公園盆踊り", "ven1", None, None, "unknown", "draft", "medium", "public", None),
            )
            if existing_historical:
                conn.execute(
                    "INSERT INTO occurrence_dates VALUES (?, ?, ?, ?, ?)",
                    ("od1", "occ1", "2025-07-25", "2025-07-25", "historical_reference"),
                )
            conn.commit()

    def public_event(self):
        return {
            "name": "中央公園盆踊り",
            "venue": "中央公園",
            "date": "",
            "date_end": "",
            "historical_reference_label": "2025-07-25実績・今年未確認",
            "historical_reference": {
                "last_seen_year": 2025,
                "last_seen_dates": ["2025-07-25"],
                "confidence": "medium",
            },
            "source_urls": [
                {
                    "label": "公式告知あり",
                    "url": "https://example.test/event",
                    "kind": "official",
                }
            ],
        }

    def test_builds_dry_run_request_for_strong_unique_occurrence_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "master.sqlite"
            self.make_db(db_path)

            payload, report = build_payload([self.public_event()], db_path)

            self.assertEqual(report["request_count"], 1)
            self.assertEqual(report["issue_count"], 0)
            request = payload["requests"][0]
            self.assertEqual(request["change_type"], "add_historical_reference")
            self.assertEqual(request["occurrence_id"], "occ1")
            self.assertEqual(request["historical_date"], "2025-07-25")
            self.assertTrue(request["dry_run_only"])

    def test_skips_when_same_historical_reference_is_already_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "master.sqlite"
            self.make_db(db_path, existing_historical=True)

            payload, report = build_payload([self.public_event()], db_path)

            self.assertEqual(payload["requests"], [])
            self.assertEqual(report["summary"]["skipped:already_recorded"], 1)

    def test_accepts_unique_exact_venue_match_when_event_name_differs(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "master.sqlite"
            self.make_db(db_path)
            event = self.public_event()
            event["name"] = "第10回 中央公園まつり 盆踊り"

            payload, report = build_payload([event], db_path)

            self.assertEqual(report["request_count"], 1)
            self.assertEqual(report["summary"]["resolution:venue_exact_unique"], 1)
            self.assertEqual(payload["requests"][0]["occurrence_id"], "occ1")

    def test_uses_source_map_occurrence_id_before_name_matching(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "master.sqlite"
            self.make_db(db_path)
            event = self.public_event()
            event["name"] = "公開用に少し違う名前"
            source_map = {
                "公開用に少し違う名前|中央公園||": {
                    "occurrence_id": "occ1",
                }
            }

            payload, report = build_payload([event], db_path, source_map=source_map)

            self.assertEqual(report["request_count"], 1)
            self.assertEqual(report["summary"]["resolution:source_map"], 1)
            self.assertEqual(payload["requests"][0]["occurrence_id"], "occ1")

    def test_falls_back_to_rdb_occurrence_source_with_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "master.sqlite"
            self.make_db(db_path)
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    "UPDATE event_occurrences SET source_url = ? WHERE occurrence_id = 'occ1'",
                    ("https://example.test/rdb-occurrence",),
                )
            event = self.public_event()
            event["source_urls"] = []

            payload, report = build_payload([event], db_path)

            self.assertEqual(report["request_count"], 1)
            self.assertEqual(report["summary"]["source:rdb_occurrence"], 1)
            source = payload["requests"][0]["source"]
            self.assertEqual(source["url"], "https://example.test/rdb-occurrence")
            self.assertEqual(source["kind"], "historical_occurrence_rdb_occurrence")
            self.assertEqual(source["provenance"], "rdb_occurrence")


if __name__ == "__main__":
    unittest.main()
