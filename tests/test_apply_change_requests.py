import argparse
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import report_apply.apply_change_requests as apply_change_requests
from report_apply.apply_change_requests import apply_payload, validate_apply_allowed, validate_payload
from master_rdb.master_db import SCHEMA


class ApplyChangeRequestsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.sqlite"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.executescript(SCHEMA)
        self.conn.execute(
            """
            INSERT INTO venues(
              venue_id, canonical_name, normalized_name, area, address,
              review_status, created_at, updated_at
            ) VALUES ('venue_old', '旧会場', '旧会場', '中央区', '東京都中央区1-1', 'active', 'now', 'now')
            """
        )
        self.conn.execute(
            """
            INSERT INTO event_series(
              series_id, series_key, canonical_name, normalized_name,
              annual_months_json, status, created_at, updated_at
            ) VALUES ('series_1', 'sample', 'サンプル盆踊り', 'サンプル盆踊り', '[]', 'active', 'now', 'now')
            """
        )
        self.conn.execute(
            """
            INSERT INTO event_occurrences(
              occurrence_id, series_id, event_year, occurrence_sequence,
              display_name, venue_id, date_status, lifecycle_status,
              confidence, created_at, updated_at
            ) VALUES ('occ_1', 'series_1', 2026, 1, 'サンプル盆踊り', 'venue_old', 'unknown', 'draft', 'unknown', 'now', 'now')
            """
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_validates_current_year_confirmation_requires_current_year_source(self):
        payload = {
            "request_type": "rdb_change_requests",
            "requests": [
                {
                    "request_id": "bad",
                    "change_type": "confirm_current_year_date",
                    "occurrence_id": "occ_1",
                    "event_year": 2026,
                    "date_start": "2026-07-20",
                    "source": {"url": "https://example.com", "kind": "historical_occurrence_video"},
                }
            ],
        }

        with self.assertRaisesRegex(ValueError, "confirm_current_year_date requires kind"):
            validate_payload(payload)

    def test_validates_create_current_year_occurrence_contract(self):
        payload = {
            "request_type": "rdb_change_requests",
            "requests": [
                {
                    "request_id": "create_bad",
                    "change_type": "create_current_year_occurrence",
                    "series_id": "series_1",
                    "display_name": "第2回 サンプル盆踊り",
                    "event_year": 2026,
                    "date_start": "2025-07-20",
                    "venue": {},
                    "source": {
                        "url": "https://example.com/history",
                        "kind": "historical_occurrence_page",
                    },
                }
            ],
        }

        with self.assertRaisesRegex(
            ValueError,
            "missing required field: name.*requires kind.*date_start must be in event_year",
        ):
            validate_payload(payload)

    def test_creates_current_year_occurrence_for_existing_series_idempotently(self):
        self.conn.execute("DELETE FROM event_occurrences WHERE occurrence_id = 'occ_1'")
        self.conn.commit()
        payload = {
            "request_type": "rdb_change_requests",
            "requests": [
                {
                    "request_id": "create_2026",
                    "change_type": "create_current_year_occurrence",
                    "series_id": "series_1",
                    "display_name": "第2回 サンプル盆踊り",
                    "event_year": 2026,
                    "date_start": "2026-07-20",
                    "date_end": "2026-07-21",
                    "venue": {
                        "name": "新会場",
                        "area": "中央区",
                        "address": "東京都中央区2-2",
                    },
                    "source": {
                        "url": "https://example.com/official-2026",
                        "kind": "official_current_year",
                        "title": "2026年公式発表",
                    },
                    "note": "2026年の公式開催情報を確認。",
                }
            ],
        }
        validate_payload(payload)

        first, first_issues = apply_payload(self.conn, payload, "2026-07-21T00:00:00+00:00")
        self.conn.commit()
        second, second_issues = apply_payload(self.conn, payload, "2026-07-21T00:01:00+00:00")
        self.conn.commit()

        self.assertEqual(first_issues, [])
        self.assertEqual(second_issues, [])
        self.assertTrue(first["requests_applied"][0]["occurrence_created"])
        self.assertFalse(second["requests_applied"][0]["occurrence_created"])
        occurrence = self.conn.execute(
            """
            SELECT display_name, date_start, date_end, date_status, lifecycle_status, source_url
            FROM event_occurrences
            WHERE series_id = 'series_1' AND event_year = 2026
            """
        ).fetchone()
        self.assertEqual(
            tuple(occurrence),
            (
                "第2回 サンプル盆踊り",
                "2026-07-20",
                "2026-07-21",
                "confirmed",
                "published",
                "https://example.com/official-2026",
            ),
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM event_occurrences WHERE series_id = 'series_1' AND event_year = 2026"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM occurrence_evidence_links WHERE occurrence_id = ?",
                (first["requests_applied"][0]["occurrence_id"],),
            ).fetchone()[0],
            1,
        )

    def test_create_current_year_occurrence_skips_unknown_series(self):
        payload = {
            "request_type": "rdb_change_requests",
            "requests": [
                {
                    "request_id": "create_unknown",
                    "change_type": "create_current_year_occurrence",
                    "series_id": "series_missing",
                    "display_name": "未知の盆踊り",
                    "event_year": 2026,
                    "date_start": "2026-07-20",
                    "venue": {"name": "会場"},
                    "source": {
                        "url": "https://example.com/official",
                        "kind": "official_current_year",
                    },
                }
            ],
        }
        validate_payload(payload)

        applied, issues = apply_payload(self.conn, payload, "2026-07-21T00:00:00+00:00")

        self.assertEqual(applied["requests_applied"], [])
        self.assertEqual(applied["requests_unresolved"], ["create_unknown"])
        self.assertEqual(issues[0]["issue_type"], "series_id_not_found")

    def test_create_current_year_occurrence_rolls_back_when_venue_is_ambiguous(self):
        self.conn.execute("DELETE FROM event_occurrences WHERE occurrence_id = 'occ_1'")
        self.conn.commit()
        payload = {
            "request_type": "rdb_change_requests",
            "requests": [
                {
                    "request_id": "create_ambiguous_venue",
                    "change_type": "create_current_year_occurrence",
                    "series_id": "series_1",
                    "display_name": "第2回 サンプル盆踊り",
                    "event_year": 2026,
                    "date_start": "2026-07-20",
                    "venue": {"name": "候補が複数ある会場"},
                    "source": {
                        "url": "https://example.com/official",
                        "kind": "official_current_year",
                    },
                }
            ],
        }
        validate_payload(payload)

        with patch(
            "report_apply.apply_change_requests.ensure_venue",
            return_value={
                "status": "ambiguous",
                "venue_id": None,
                "candidates": [{"venue_id": "venue_a"}, {"venue_id": "venue_b"}],
            },
        ):
            applied, issues = apply_payload(
                self.conn,
                payload,
                "2026-07-21T00:00:00+00:00",
            )

        self.assertEqual(applied["requests_applied"], [])
        self.assertEqual(applied["requests_unresolved"], ["create_ambiguous_venue"])
        self.assertEqual(issues[0]["issue_type"], "ambiguous_venue")
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM event_occurrences WHERE series_id = 'series_1' AND event_year = 2026"
            ).fetchone()[0],
            0,
        )

    def test_create_current_year_occurrence_marks_past_event_ended(self):
        self.conn.execute("DELETE FROM event_occurrences WHERE occurrence_id = 'occ_1'")
        self.conn.commit()
        payload = {
            "request_type": "rdb_change_requests",
            "requests": [
                {
                    "request_id": "create_ended_2026",
                    "change_type": "create_current_year_occurrence",
                    "series_id": "series_1",
                    "display_name": "終了済み盆踊り",
                    "event_year": 2026,
                    "date_start": "2026-07-10",
                    "date_end": "2026-07-11",
                    "venue": {"name": "終了済み会場"},
                    "source": {
                        "url": "https://example.com/official-ended",
                        "kind": "official_current_year",
                    },
                }
            ],
        }
        validate_payload(payload)

        on_final_day, first_issues = apply_payload(
            self.conn,
            payload,
            "2026-07-11T00:00:00+00:00",
        )
        applied, issues = apply_payload(
            self.conn,
            payload,
            "2026-07-21T00:00:00+00:00",
        )

        self.assertEqual(first_issues, [])
        self.assertEqual(on_final_day["requests_applied"][0]["date_status"], "confirmed")
        self.assertEqual(issues, [])
        self.assertEqual(applied["requests_applied"][0]["date_status"], "ended")
        occurrence = self.conn.execute(
            """
            SELECT date_status, current_event_state, date_certainty_tier
            FROM event_occurrences
            WHERE series_id = 'series_1' AND event_year = 2026
            """
        ).fetchone()
        self.assertEqual(tuple(occurrence), ("ended", "ended", "confirmed"))
        occurrence_date = self.conn.execute(
            """
            SELECT date_type
            FROM occurrence_dates
            WHERE occurrence_id = ?
            """,
            (applied["requests_applied"][0]["occurrence_id"],),
        ).fetchone()
        self.assertEqual(occurrence_date[0], "ended")

    def test_confirm_current_year_date_reuses_existing_exact_date_row(self):
        self.conn.execute(
            """
            INSERT INTO occurrence_dates (
              occurrence_date_id, occurrence_id, date_start, date_end,
              date_type, confidence, basis, created_at
            ) VALUES (
              'legacy_date_id', 'occ_1', '2026-07-20', '2026-07-21',
              'confirmed', 'confirmed', 'legacy import', 'now'
            )
            """
        )
        payload = {
            "request_type": "rdb_change_requests",
            "requests": [
                {
                    "request_id": "confirm_existing_date",
                    "change_type": "confirm_current_year_date",
                    "occurrence_id": "occ_1",
                    "event_year": 2026,
                    "date_start": "2026-07-20",
                    "date_end": "2026-07-21",
                    "source": {
                        "url": "https://example.com/current-year",
                        "kind": "official_current_year",
                    },
                }
            ],
        }
        validate_payload(payload)

        applied, issues = apply_payload(
            self.conn,
            payload,
            "2026-07-22T00:00:00+00:00",
        )

        self.assertEqual(issues, [])
        self.assertEqual(applied["requests_applied"][0]["date_status"], "ended")
        dates = self.conn.execute(
            """
            SELECT occurrence_date_id, date_type, basis
            FROM occurrence_dates
            WHERE occurrence_id = 'occ_1'
            """
        ).fetchall()
        self.assertEqual(
            [tuple(row) for row in dates],
            [
                (
                    "legacy_date_id",
                    "ended",
                    "current-year source: https://example.com/current-year",
                )
            ],
        )

    def test_applies_four_finite_change_types(self):
        payload = {
            "request_type": "rdb_change_requests",
            "requests": [
                {
                    "request_id": "confirm_date",
                    "change_type": "confirm_current_year_date",
                    "occurrence_id": "occ_1",
                    "event_year": 2026,
                    "date_start": "2026-07-20",
                    "source": {
                        "url": "https://example.com/official",
                        "kind": "official_current_year",
                        "title": "公式発表",
                        "text_excerpt": "2026年7月20日開催",
                    },
                },
                {
                    "request_id": "historical",
                    "change_type": "add_historical_reference",
                    "occurrence_id": "occ_1",
                    "event_year": 2026,
                    "historical_year": 2025,
                    "historical_date": "2025-07-21",
                    "source": {
                        "url": "https://www.youtube.com/watch?v=sample",
                        "platform": "youtube",
                        "kind": "historical_occurrence_video",
                        "title": "2025実績",
                    },
                },
                {
                    "request_id": "venue",
                    "change_type": "update_venue",
                    "occurrence_id": "occ_1",
                    "venue": {"name": "新会場", "area": "中央区", "address": "東京都中央区2-2"},
                    "source": {"url": "https://example.com/venue", "kind": "official_current_year"},
                },
                {
                    "request_id": "songs",
                    "change_type": "add_song_evidence",
                    "occurrence_id": "occ_1",
                    "evidence_mode": "historical_youtube",
                    "songs": [{"title": "東京音頭"}, {"title": "大東京音頭", "uncertain": True}],
                    "source": {
                        "url": "https://www.youtube.com/watch?v=songs",
                        "platform": "youtube",
                        "kind": "historical_occurrence_video",
                    },
                },
            ],
        }
        validate_payload(payload)

        applied, issues = apply_payload(self.conn, payload, "2026-07-16T00:00:00+00:00")
        self.conn.commit()

        self.assertEqual(issues, [])
        self.assertEqual(len(applied["requests_applied"]), 4)
        occurrence = self.conn.execute(
            "SELECT date_start, date_status, lifecycle_status, venue_id FROM event_occurrences WHERE occurrence_id = 'occ_1'"
        ).fetchone()
        self.assertEqual(occurrence[0], "2026-07-20")
        self.assertEqual(occurrence[1], "confirmed")
        self.assertEqual(occurrence[2], "published")
        self.assertNotEqual(occurrence[3], "venue_old")
        historical_dates = self.conn.execute(
            "SELECT COUNT(*) FROM occurrence_dates WHERE occurrence_id = 'occ_1' AND date_type = 'historical_reference'"
        ).fetchone()[0]
        self.assertEqual(historical_dates, 1)
        song_count = self.conn.execute("SELECT COUNT(*) FROM occurrence_songs WHERE occurrence_id = 'occ_1'").fetchone()[0]
        self.assertEqual(song_count, 2)

    def test_historical_reference_date_reuses_existing_natural_key(self):
        self.conn.execute(
            """
            INSERT INTO occurrence_dates(
              occurrence_date_id, occurrence_id, date_start, date_end, date_type,
              confidence, basis, created_at
            ) VALUES ('legacy_date_id', 'occ_1', '2025-07-21', '2025-07-21', 'historical_reference', 'confirmed', 'legacy', 'now')
            """
        )
        self.conn.commit()
        payload = {
            "request_type": "rdb_change_requests",
            "requests": [
                {
                    "request_id": "historical",
                    "change_type": "add_historical_reference",
                    "occurrence_id": "occ_1",
                    "event_year": 2026,
                    "historical_year": 2025,
                    "historical_date": "2025-07-21",
                    "source": {
                        "url": "https://www.youtube.com/watch?v=sample",
                        "platform": "youtube",
                        "kind": "historical_occurrence_video",
                    },
                }
            ],
        }

        applied, issues = apply_payload(self.conn, payload, "2026-07-16T00:00:00+00:00")
        self.conn.commit()

        self.assertEqual(issues, [])
        self.assertEqual(len(applied["requests_applied"]), 1)
        dates = self.conn.execute(
            """
            SELECT occurrence_date_id, source_evidence_id
            FROM occurrence_dates
            WHERE occurrence_id = 'occ_1'
              AND date_start = '2025-07-21'
              AND date_type = 'historical_reference'
            """
        ).fetchall()
        self.assertEqual(len(dates), 1)
        self.assertEqual(dates[0][0], "legacy_date_id")
        self.assertTrue(dates[0][1])

    def test_historical_reference_note_does_not_mutate_occurrence_detail(self):
        self.conn.execute(
            "UPDATE event_occurrences SET detail = '公開用の説明' WHERE occurrence_id = 'occ_1'"
        )
        self.conn.commit()
        payload = {
            "request_type": "rdb_change_requests",
            "requests": [
                {
                    "request_id": "historical_with_internal_note",
                    "change_type": "add_historical_reference",
                    "occurrence_id": "occ_1",
                    "event_year": 2026,
                    "historical_year": 2025,
                    "historical_date": "2025-07-21",
                    "note": "public historical_reference import candidate: internal only",
                    "source": {
                        "url": "https://example.com/2025-result",
                        "kind": "historical_occurrence_page",
                    },
                }
            ],
        }

        applied, issues = apply_payload(self.conn, payload, "2026-07-17T00:00:00+00:00")
        self.conn.commit()

        self.assertEqual(issues, [])
        self.assertEqual(applied["requests_applied"][0]["changed_fields"], [])
        detail = self.conn.execute(
            "SELECT detail FROM event_occurrences WHERE occurrence_id = 'occ_1'"
        ).fetchone()[0]
        self.assertEqual(detail, "公開用の説明")

    def test_apply_refuses_dry_run_only_requests(self):
        payload = {
            "request_type": "rdb_change_requests",
            "requests": [
                {
                    "request_id": "sample_only",
                    "change_type": "update_venue",
                    "occurrence_id": "occ_1",
                    "dry_run_only": True,
                    "venue": {"name": "新会場"},
                    "source": {"url": "https://example.com/sample", "kind": "official_current_year"},
                }
            ],
        }
        validate_payload(payload)

        with self.assertRaisesRegex(ValueError, "dry_run_only"):
            validate_apply_allowed(payload)


class SqliteConnectHelperTests(unittest.TestCase):
    def test_closes_connection_after_with_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "helper.sqlite"
            setup_conn = sqlite3.connect(db_path)
            setup_conn.execute("CREATE TABLE t (x INTEGER)")
            setup_conn.commit()
            setup_conn.close()

            with apply_change_requests.sqlite_connect(db_path) as conn:
                conn.execute("SELECT 1")

            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")


class RunConnectionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)

        self.master_db = self.tmp_path / "master.sqlite"
        conn = sqlite3.connect(self.master_db)
        conn.executescript(SCHEMA)
        conn.execute(
            """
            INSERT INTO venues(
              venue_id, canonical_name, normalized_name, area, address,
              review_status, created_at, updated_at
            ) VALUES ('venue_old', '旧会場', '旧会場', '中央区', '東京都中央区1-1', 'active', 'now', 'now')
            """
        )
        conn.execute(
            """
            INSERT INTO event_series(
              series_id, series_key, canonical_name, normalized_name,
              annual_months_json, status, created_at, updated_at
            ) VALUES ('series_1', 'sample', 'サンプル盆踊り', 'サンプル盆踊り', '[]', 'active', 'now', 'now')
            """
        )
        conn.execute(
            """
            INSERT INTO event_occurrences(
              occurrence_id, series_id, event_year, occurrence_sequence,
              display_name, venue_id, date_status, lifecycle_status,
              confidence, created_at, updated_at
            ) VALUES ('occ_1', 'series_1', 2026, 1, 'サンプル盆踊り', 'venue_old', 'unknown', 'draft', 'unknown', 'now', 'now')
            """
        )
        conn.commit()
        conn.close()

        self.requests_path = self.tmp_path / "requests.json"
        self.requests_path.write_text(
            json.dumps(
                {
                    "request_type": "rdb_change_requests",
                    "requests": [
                        {
                            "request_id": "confirm_date",
                            "change_type": "confirm_current_year_date",
                            "occurrence_id": "occ_1",
                            "event_year": 2026,
                            "date_start": "2026-07-20",
                            "source": {"url": "https://example.com/official", "kind": "official_current_year"},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def _make_args(self, apply=False, confirm=""):
        return argparse.Namespace(
            requests=self.requests_path,
            master_db=self.master_db,
            out_db=self.tmp_path / "out.sqlite",
            out_json=self.tmp_path / "out.json",
            out_md=self.tmp_path / "out.md",
            apply=apply,
            confirm=confirm,
        )

    def _wrap_sqlite_connect(self, opened):
        real_sqlite_connect = apply_change_requests.sqlite_connect

        def wrapper(path):
            ctx = real_sqlite_connect(path)
            opened.append(ctx.thing)
            return ctx

        return wrapper

    def test_dry_run_closes_target_connection(self):
        opened = []
        with patch.object(apply_change_requests, "sqlite_connect", side_effect=self._wrap_sqlite_connect(opened)):
            apply_change_requests.run(self._make_args(apply=False))

        self.assertEqual(len(opened), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            opened[0].execute("SELECT 1")

    def test_apply_closes_preflight_and_target_connections(self):
        opened = []
        preflight_db = self.tmp_path / "preflight.sqlite"
        backup_dir = self.tmp_path / "backups"
        with patch.object(apply_change_requests, "sqlite_connect", side_effect=self._wrap_sqlite_connect(opened)), \
                patch.object(apply_change_requests, "PREFLIGHT_DB", preflight_db), \
                patch.object(apply_change_requests, "BACKUP_DIR", backup_dir), \
                patch.object(apply_change_requests, "refresh_manifest_database_state"):
            apply_change_requests.run(self._make_args(apply=True, confirm="APPLY CHANGE REQUESTS"))

        self.assertEqual(len(opened), 2)
        for conn in opened:
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
