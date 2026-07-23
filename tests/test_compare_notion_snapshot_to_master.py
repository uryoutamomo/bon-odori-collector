import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import compare_notion_snapshot_to_master as compare


class CompareNotionSnapshotToMasterTest(unittest.TestCase):
    def test_series_public_intro_blank_sibling_is_not_reported_as_drift(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            notion_db = tmp / "notion.sqlite"
            with closing(sqlite3.connect(notion_db)) as conn:
                conn.executescript(
                    """
                    CREATE TABLE notion_events (
                      page_id TEXT PRIMARY KEY,
                      event_name TEXT,
                      start_date TEXT,
                      end_date TEXT,
                      status TEXT,
                      annual_months TEXT,
                      detail TEXT,
                      public_intro TEXT,
                      source_url TEXT
                    );
                    CREATE TABLE notion_relations (
                      page_id TEXT,
                      property_name TEXT,
                      related_page_id TEXT
                    );
                    """
                )
                conn.execute(
                    "INSERT INTO notion_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ("page_2025", "Sample Bon Dance", "", "", "", "", "", "", "https://example.com"),
                )
                conn.execute(
                    "INSERT INTO notion_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ("page_2026", "Sample Bon Dance", "", "", "", "", "", "紹介文", "https://example.com"),
                )

            with closing(sqlite3.connect(":memory:")) as conn:
                conn.executescript(
                    """
                    CREATE TABLE external_record_links (
                      system TEXT,
                      source_key TEXT,
                      external_id TEXT,
                      master_table TEXT,
                      master_id TEXT,
                      relation_kind TEXT
                    );
                    CREATE TABLE event_occurrences (
                      occurrence_id TEXT PRIMARY KEY,
                      series_id TEXT,
                      display_name TEXT,
                      event_year INTEGER,
                      venue_id TEXT,
                      date_start TEXT,
                      date_end TEXT,
                      date_status TEXT,
                      lifecycle_status TEXT,
                      source_url TEXT,
                      public_intro_override TEXT,
                      detail TEXT
                    );
                    CREATE TABLE event_series (
                      series_id TEXT PRIMARY KEY,
                      canonical_name TEXT,
                      usual_venue_id TEXT,
                      annual_months_json TEXT,
                      public_intro TEXT,
                      source_url TEXT
                    );
                    """
                )
                conn.execute(
                    "INSERT INTO event_series VALUES (?, ?, ?, ?, ?, ?)",
                    ("ser1", "Sample Bon Dance", "", "[]", "紹介文", "https://example.com"),
                )
                conn.executemany(
                    "INSERT INTO external_record_links VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        ("notion", "events", "page_2025", "event_series", "ser1", "series_for_occurrence"),
                        ("notion", "events", "page_2026", "event_series", "ser1", "series_for_occurrence"),
                    ],
                )
                conn.execute("ATTACH DATABASE ? AS notion", (str(notion_db),))

                diffs = compare.compare_events(conn)

            public_intro_diffs = [
                row for row in diffs
                if row["entity_type"] == "event_series" and row["field"] == "public_intro"
            ]
            self.assertEqual(public_intro_diffs, [])


if __name__ == "__main__":
    unittest.main()
