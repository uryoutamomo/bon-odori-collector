import sqlite3
import unittest

from promotion_candidates import build_historical_promotion_candidates as builder
from master_db import SCHEMA


class BuildHistoricalPromotionCandidatesTest(unittest.TestCase):
    def test_low_score_prediction_is_kept_for_existing_current_occurrence(self):
        item = {
            "candidate_id": "candidate_1",
            "target_series_id": "series_1",
            "target_event_name": "東本願寺盆踊り",
            "auto_promote_eligible": False,
            "prediction_summaries": [
                {
                    "rule_type": "weekday_nth",
                    "predicted_date_start": "2026-08-19",
                    "predicted_date_end": "2026-08-19",
                    "basis": "8月第3水曜",
                    "confidence": "medium",
                    "score": 0.7,
                }
            ],
        }
        occurrence_lookup = {
            ("series_1", 2026): {
                "occurrence_id": "occurrence_2026",
                "date_start": "2026-08-19",
                "date_end": "2026-08-20",
            }
        }

        rows = builder.predicted_dates_for_candidate(item, occurrence_lookup)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["target_occurrence_id"], "occurrence_2026")
        self.assertEqual(rows[0]["application_status"], "superseded_by_curated")

    def test_manual_predictions_survive_derived_table_rebuild(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(SCHEMA)
        conn.execute("PRAGMA foreign_keys = OFF")
        values = {
            column: f"value_{column}"
            for column in builder.PREDICTED_DATE_COLUMNS
        }
        values.update(
            {
                "predicted_date_id": "manual_prediction",
                "historical_candidate_id": "candidate_1",
                "target_series_id": "series_1",
                "target_occurrence_id": None,
                "predicted_year": 2026,
                "score": 0.66,
                "source": "manual_review",
            }
        )
        conn.execute(
            """
            INSERT INTO historical_promotion_candidates(
              candidate_id, target_series_id, target_occurrence_id, target_event_name,
              historical_years_json, promotion_confidence, recommended_action,
              created_at, updated_at
            ) VALUES (
              'candidate_1', 'series_1', 'occurrence_1', '手動予測イベント',
              '[2024, 2025]', 'manual', 'keep_manual_prediction', 'now', 'now'
            )
            """
        )
        columns = ", ".join(builder.PREDICTED_DATE_COLUMNS)
        placeholders = ", ".join("?" for _ in builder.PREDICTED_DATE_COLUMNS)
        conn.execute(
            f"INSERT INTO predicted_occurrence_dates ({columns}) VALUES ({placeholders})",
            tuple(values[column] for column in builder.PREDICTED_DATE_COLUMNS),
        )

        preserved = builder.manual_prediction_rows(conn)
        preserved_candidates = builder.manual_candidate_rows(conn, preserved)
        conn.execute("DELETE FROM predicted_occurrence_dates")
        conn.execute("DELETE FROM historical_promotion_candidates")
        builder.restore_manual_candidate_rows(conn, preserved_candidates)
        restored = builder.restore_manual_prediction_rows(
            conn,
            preserved,
            {candidate["candidate_id"] for candidate in preserved_candidates},
        )

        self.assertEqual(restored, 1)
        self.assertEqual(
            conn.execute("SELECT candidate_id FROM historical_promotion_candidates").fetchone()[0],
            "candidate_1",
        )
        self.assertEqual(
            conn.execute("SELECT source FROM predicted_occurrence_dates").fetchone()[0],
            "manual_review",
        )
        conn.close()

    def test_candidate_less_manual_predictions_are_unconditionally_preserved(self):
        candidate_ids = {"known_candidate"}

        self.assertTrue(
            builder.should_restore_manual_prediction(
                {"historical_candidate_id": None}, candidate_ids
            )
        )
        self.assertTrue(
            builder.should_restore_manual_prediction(
                {"historical_candidate_id": ""}, candidate_ids
            )
        )
        self.assertFalse(
            builder.should_restore_manual_prediction(
                {"historical_candidate_id": "missing_candidate"}, candidate_ids
            )
        )

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
