import sqlite3
import unittest

import dry_run_ph2_event_occurrence_apply as script


class DryRunPh2EventOccurrenceApplyTest(unittest.TestCase):
    def make_conn(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE event_series (
              series_id TEXT PRIMARY KEY,
              canonical_name TEXT NOT NULL
            );
            CREATE TABLE venues (
              venue_id TEXT PRIMARY KEY,
              canonical_name TEXT NOT NULL
            );
            CREATE TABLE event_occurrences (
              occurrence_id TEXT PRIMARY KEY,
              series_id TEXT NOT NULL,
              event_year INTEGER NOT NULL,
              display_name TEXT NOT NULL,
              venue_id TEXT,
              date_start TEXT,
              date_end TEXT,
              date_status TEXT,
              lifecycle_status TEXT,
              confidence TEXT,
              source_kind TEXT,
              source_url TEXT,
              updated_at TEXT
            );
            CREATE TABLE occurrence_dates (
              occurrence_date_id TEXT PRIMARY KEY,
              occurrence_id TEXT NOT NULL,
              date_start TEXT NOT NULL,
              date_end TEXT,
              date_type TEXT NOT NULL,
              confidence TEXT,
              basis TEXT,
              created_at TEXT
            );
            CREATE TABLE notion_sync_jobs (
              job_id TEXT PRIMARY KEY,
              requested_by TEXT
            );
            """
        )
        conn.execute("INSERT INTO event_series VALUES (?, ?)", ("ser1", "品川区民まつり テスト地区"))
        conn.execute("INSERT INTO venues VALUES (?, ?)", ("ven1", "テスト会場"))
        conn.execute(
            """
            INSERT INTO event_occurrences VALUES (
              'occ1', 'ser1', 2026, '品川区民まつり テスト地区',
              NULL, '', '', 'unknown', '未確認', 'unknown', '', '', ''
            )
            """
        )
        conn.commit()
        return conn

    def test_current_official_apply_does_not_queue_notion_sync_job(self):
        conn = self.make_conn()
        mutation = {
            "mutation_type": script.MUTATION_TYPES["current_official"],
            "event_name": "品川区民まつり テスト地区",
            "notion_page_id": "notion-event-page",
            "target": {"occurrence_id": "occ1"},
            "proposed": {
                "date_start": "2026-07-18",
                "date_end": "2026-07-19",
                "date_status": "confirmed",
                "confidence": "high",
                "source_kind": "official_current_year",
                "source_url": "https://example.test/source",
                "venue_lookup_status": "exact_match",
                "venue_matches": [{"venue_id": "ven1"}],
            },
            "notion_payload": {"fields": {"状態": "確認済み"}},
        }

        result = script.apply_current_official(conn, mutation, "2026-06-23T00:00:00+00:00")

        self.assertEqual(result["inserted_notion_sync_job_id"], "")
        self.assertFalse(result["notion_sync_job_queued"])
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM notion_sync_jobs").fetchone()[0],
            0,
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM occurrence_dates").fetchone()[0],
            1,
        )
        self.assertEqual(result["after"]["venue_name"], "テスト会場")


if __name__ == "__main__":
    unittest.main()
