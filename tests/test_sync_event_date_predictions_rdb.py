import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import export_public_events
import sync_event_date_predictions_rdb as syncer
from master_rdb.master_db import SCHEMA, file_sha256


NOW = "2026-08-18T00:00:00+00:00"


class SyncEventDatePredictionsRdbTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db = self.root / "master.sqlite"
        conn = sqlite3.connect(self.db)
        conn.executescript(SCHEMA)
        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def add_series(
        self,
        *,
        suffix="main",
        canonical_name="神田明神納涼祭り",
        alias="神田明神納涼祭り アニソン盆踊り",
        venue="神田明神境内",
        event_year=2026,
        date_start="2026-08-07",
    ):
        venue_id = f"venue_{suffix}"
        series_id = f"series_{suffix}"
        occurrence_id = f"occurrence_{suffix}"
        with sqlite3.connect(self.db) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(
                """
                INSERT INTO venues(
                  venue_id, canonical_name, normalized_name, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (venue_id, venue, venue, NOW, NOW),
            )
            conn.execute(
                """
                INSERT INTO event_series(
                  series_id, series_key, canonical_name, normalized_name,
                  usual_venue_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    series_id,
                    f"series-key-{suffix}",
                    canonical_name,
                    canonical_name,
                    venue_id,
                    NOW,
                    NOW,
                ),
            )
            if alias:
                conn.execute(
                    """
                    INSERT INTO event_series_aliases(
                      series_id, alias, normalized_alias, source, confidence
                    ) VALUES (?, ?, ?, 'test', 'manual')
                    """,
                    (series_id, alias, alias),
                )
            conn.execute(
                """
                INSERT INTO event_occurrences(
                  occurrence_id, series_id, event_year, display_name, venue_id,
                  date_start, date_end, date_status, lifecycle_status,
                  current_event_state, date_certainty_tier, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'confirmed', 'published',
                          'confirmed', 'confirmed', ?, ?)
                """,
                (
                    occurrence_id,
                    series_id,
                    event_year,
                    canonical_name,
                    venue_id,
                    date_start,
                    date_start,
                    NOW,
                    NOW,
                ),
            )
        return {
            "venue_id": venue_id,
            "series_id": series_id,
            "occurrence_id": occurrence_id,
        }

    def write_predictions(
        self,
        *,
        event_name="神田明神納涼祭り アニソン盆踊り",
        venue="神田明神境内",
        series_key="youtube-series-key",
        start="2026-08-14",
        end="2026-08-16",
    ):
        path = self.root / "event_date_predictions.json"
        payload = {
            "generated_by": "build_event_date_predictions.py",
            "target_year": 2026,
            "predictions": [
                {
                    "series_key": series_key,
                    "event_name": event_name,
                    "venue": venue,
                    "target_year": 2026,
                    "prediction": {
                        "rule_type": "weekday_nth",
                        "predicted_date_start": start,
                        "predicted_date_end": end,
                        "confidence": "medium",
                        "score": 0.7,
                        "basis": "8月第2金曜から3日間",
                        "evidence_years": [2023, 2024],
                        "evidence_rows": [
                            {
                                "year": 2023,
                                "date_start": "2023-08-11",
                                "date_end": "2023-08-13",
                                "source_video_count": 1,
                            },
                            {
                                "year": 2024,
                                "date_start": "2024-08-09",
                                "date_end": "2024-08-11",
                                "source_video_count": 1,
                            },
                        ],
                    },
                    "candidate_rules": [],
                    "actual_observations": [],
                }
            ],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def execute(self, predictions):
        return syncer.run(
            db_path=self.db,
            predictions_path=predictions,
            target_year=2026,
            execute=True,
            confirm=syncer.CONFIRM_TEXT,
            now=NOW,
        )

    def test_sync_closes_public_json_fallback_without_changing_confirmed_date(self):
        identity = self.add_series()
        predictions = self.write_predictions()

        report = self.execute(predictions)

        self.assertEqual(report["summary"]["inserted_count"], 1)
        self.assertEqual(report["summary"]["support_candidate_inserted_count"], 1)
        with sqlite3.connect(self.db) as conn:
            conn.row_factory = sqlite3.Row
            occurrence = conn.execute(
                "SELECT date_start, date_status FROM event_occurrences WHERE occurrence_id=?",
                (identity["occurrence_id"],),
            ).fetchone()
            prediction = conn.execute(
                "SELECT * FROM predicted_occurrence_dates"
            ).fetchone()
        self.assertEqual((occurrence["date_start"], occurrence["date_status"]), ("2026-08-07", "confirmed"))
        self.assertEqual(prediction["target_series_id"], identity["series_id"])
        self.assertEqual(prediction["application_status"], "superseded_by_curated")
        with patch.object(export_public_events, "DATE_PREDICTIONS", predictions):
            public = export_public_events.load_public_date_predictions_for_export(
                target_year=2026, db_path=self.db
            )
        self.assertEqual(public["summary"]["json_fallback_count"], 0)
        self.assertEqual(public["predictions"][0]["event_name"], "神田明神納涼祭り アニソン盆踊り")

    def test_default_dry_run_leaves_source_database_unchanged(self):
        self.add_series()
        predictions = self.write_predictions()
        before = file_sha256(self.db)

        report = syncer.run(
            db_path=self.db,
            predictions_path=predictions,
            target_year=2026,
            now=NOW,
        )

        self.assertEqual(report["mode"], "dry_run")
        self.assertGreater(report["summary"]["change_count"], 0)
        self.assertEqual(file_sha256(self.db), before)

    def test_second_run_is_idempotent_and_check_passes(self):
        self.add_series()
        predictions = self.write_predictions()
        self.execute(predictions)

        report = syncer.run(
            db_path=self.db,
            predictions_path=predictions,
            target_year=2026,
            check=True,
            now=NOW,
        )

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["summary"]["change_count"], 0)
        self.assertEqual(report["summary"]["unchanged_count"], 1)

    def test_stale_owned_row_is_removed_but_manual_prediction_survives(self):
        identity = self.add_series()
        predictions = self.write_predictions()
        self.execute(predictions)
        with sqlite3.connect(self.db) as conn:
            candidate_id = conn.execute(
                "SELECT candidate_id FROM historical_promotion_candidates"
            ).fetchone()[0]
            machine = conn.execute(
                "SELECT * FROM predicted_occurrence_dates"
            ).fetchone()
            columns = [item[1] for item in conn.execute("PRAGMA table_info(predicted_occurrence_dates)")]
            values = dict(zip(columns, machine))
            values.update(
                {
                    "predicted_date_id": "manual_prediction",
                    "historical_candidate_id": candidate_id,
                    "source": "manual_review",
                }
            )
            conn.execute(
                f"INSERT INTO predicted_occurrence_dates ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                tuple(values[column] for column in columns),
            )
            conn.execute(
                """
                INSERT INTO predicted_occurrence_dates(
                  predicted_date_id, historical_candidate_id, target_series_id,
                  target_occurrence_id, target_event_name, predicted_year,
                  date_start, date_end, date_status, basis_type, basis_type_label,
                  rule_type, confidence, application_status, source,
                  source_payload_json, created_at, updated_at
                ) VALUES (
                  'stale_machine', ?, ?, ?, 'stale', 2026,
                  '2026-09-01', '2026-09-01', 'predicted', 'date_based', '日にちベース',
                  'fixed_date', 'low', 'candidate', ?, '{}', ?, ?
                )
                """,
                (
                    candidate_id,
                    identity["series_id"],
                    identity["occurrence_id"],
                    syncer.PREDICTION_SOURCE,
                    NOW,
                    NOW,
                ),
            )

        report = self.execute(predictions)

        self.assertEqual(report["summary"]["deleted_stale_count"], 1)
        with sqlite3.connect(self.db) as conn:
            remaining = {
                row[0]
                for row in conn.execute(
                    "SELECT predicted_date_id FROM predicted_occurrence_dates"
                )
            }
        self.assertIn("manual_prediction", remaining)
        self.assertNotIn("stale_machine", remaining)

    def test_ambiguous_identity_fails_before_any_database_write(self):
        self.add_series(suffix="a")
        self.add_series(suffix="b")
        predictions = self.write_predictions()
        before = file_sha256(self.db)

        with self.assertRaisesRegex(syncer.PredictionSyncError, "ambiguous"):
            self.execute(predictions)

        self.assertEqual(file_sha256(self.db), before)

    def test_canonical_containment_requires_the_same_unique_venue(self):
        identity = self.add_series(
            canonical_name="新橋こいち祭",
            alias="",
            venue="桜田公園",
            date_start="2026-07-24",
        )
        predictions = self.write_predictions(
            event_name="第28回新橋こいち祭 盆踊り",
            venue="桜田公園",
            start="2026-07-23",
            end="2026-07-23",
        )

        report = self.execute(predictions)

        row = report["predictions"][0]
        self.assertEqual(row["match_kind"], "canonical_contained")
        self.assertEqual(row["target_series_id"], identity["series_id"])

    def test_execute_requires_exact_confirmation(self):
        self.add_series()
        predictions = self.write_predictions()

        with self.assertRaisesRegex(syncer.PredictionSyncError, "requires --confirm"):
            syncer.run(
                db_path=self.db,
                predictions_path=predictions,
                target_year=2026,
                execute=True,
                confirm="wrong",
            )

    def test_prediction_with_less_than_two_historical_years_is_rejected(self):
        self.add_series()
        predictions = self.write_predictions()
        payload = json.loads(predictions.read_text(encoding="utf-8"))
        payload["predictions"][0]["prediction"]["evidence_years"] = [2025]
        predictions.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        with self.assertRaisesRegex(syncer.PredictionSyncError, "at least two"):
            self.execute(predictions)


if __name__ == "__main__":
    unittest.main()
