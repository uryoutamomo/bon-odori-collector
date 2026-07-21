import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apply_change_requests import apply_payload, validate_apply_allowed, validate_payload
from master_db import SCHEMA


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
            "apply_change_requests.ensure_venue",
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


if __name__ == "__main__":
    unittest.main()
