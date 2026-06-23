import sqlite3
import unittest

import build_historical_promotion_candidates as builder


class BuildHistoricalPromotionCandidatesTest(unittest.TestCase):
    def test_clear_predicted_date_sync_jobs_removes_legacy_jobs_only(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE notion_sync_jobs (
              job_id TEXT PRIMARY KEY,
              target_table TEXT NOT NULL,
              requested_by TEXT NOT NULL
            );
            """
        )
        conn.executemany(
            "INSERT INTO notion_sync_jobs VALUES (?, ?, ?)",
            [
                (
                    "old-predicted",
                    "predicted_occurrence_dates",
                    "build_historical_promotion_candidates.py",
                ),
                (
                    "other-table",
                    "event_occurrences",
                    "build_historical_promotion_candidates.py",
                ),
                (
                    "other-script",
                    "predicted_occurrence_dates",
                    "other.py",
                ),
            ],
        )

        builder.clear_predicted_date_sync_jobs(conn)

        remaining = {
            row[0]
            for row in conn.execute("SELECT job_id FROM notion_sync_jobs ORDER BY job_id")
        }
        self.assertEqual(remaining, {"other-table", "other-script"})


if __name__ == "__main__":
    unittest.main()
