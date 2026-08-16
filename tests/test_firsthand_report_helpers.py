import sqlite3
import tempfile
import unittest
from pathlib import Path

import master_rdb.master_db as master_db
from report_apply.firsthand_report_helpers import (
    add_firsthand_evidence,
    ensure_series_and_occurrence,
    ensure_venue,
    find_occurrence_candidates,
    find_venue_candidates,
    upsert_occurrence_song,
)


class FirsthandReportHelpersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "master.sqlite"
        conn = master_db.init_db(self.db_path)
        conn.close()
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.addCleanup(self.conn.close)
        self._seed()

    def _seed(self):
        now = master_db.now_utc()
        self.venue_id = master_db.stable_id("venue", "杜松ホーム", "東京都品川区")
        self.conn.execute(
            """
            INSERT INTO venues(
              venue_id, origin, canonical_name, normalized_name, area, address,
              access, scale, public_intro, past_memo, source_url, latitude, longitude,
              review_status, created_at, updated_at
            ) VALUES (?, 'curated', ?, ?, '品川区', '東京都品川区', NULL, NULL, NULL, NULL, NULL, NULL, NULL,
              'active', ?, ?)
            """,
            (self.venue_id, "杜松ホーム", master_db.normalize_text("杜松ホーム"), now, now),
        )
        self.series_id = master_db.stable_id("series", master_db.normalize_text("品川第一盆踊り"))
        self.conn.execute(
            """
            INSERT INTO event_series(
              series_id, origin, series_key, canonical_name, normalized_name,
              usual_venue_id, area, program_type, annual_months_json, status, created_at, updated_at
            ) VALUES (?, 'curated', ?, ?, ?, ?, '品川区', 'bon_odori', '[7]', 'active', ?, ?)
            """,
            (
                self.series_id,
                master_db.normalize_text("品川第一盆踊り"),
                "品川第一盆踊り",
                master_db.normalize_text("品川第一盆踊り"),
                self.venue_id,
                now,
                now,
            ),
        )
        self.occurrence_id = master_db.stable_id("occ", self.series_id, 2026, 1)
        self.conn.execute(
            """
            INSERT INTO event_occurrences(
              occurrence_id, origin, series_id, event_year, occurrence_sequence,
              display_name, venue_id, date_start, date_end, date_status,
              lifecycle_status, confidence, source_kind, created_at, updated_at
            ) VALUES (?, 'curated', ?, 2026, 1, ?, ?, '2026-07-25', '2026-07-25', 'confirmed',
              'published', 'confirmed', 'official_current_year', ?, ?)
            """,
            (self.occurrence_id, self.series_id, "品川第一盆踊り", self.venue_id, now, now),
        )
        self.conn.commit()

    def test_find_venue_candidates_exact_match(self):
        candidates = find_venue_candidates(self.conn, "杜松ホーム")
        self.assertEqual(candidates[0]["venue_id"], self.venue_id)
        self.assertGreaterEqual(candidates[0]["match_score"], 0.92)

    def test_find_venue_candidates_below_threshold_excluded(self):
        candidates = find_venue_candidates(self.conn, "まったく無関係な文字列XYZ")
        self.assertEqual(candidates, [])

    def test_ensure_venue_reuses_exact_match(self):
        result = ensure_venue(self.conn, "杜松ホーム", address="東京都品川区")
        self.assertEqual(result["status"], "reused")
        self.assertEqual(result["venue_id"], self.venue_id)
        count = self.conn.execute("SELECT COUNT(*) FROM venues").fetchone()[0]
        self.assertEqual(count, 1)

    def test_ensure_venue_creates_new_when_no_match(self):
        result = ensure_venue(self.conn, "新しい会場ABC", address="東京都大田区1-2-3")
        self.assertEqual(result["status"], "created")
        self.assertIsNotNone(result["venue_id"])
        count = self.conn.execute("SELECT COUNT(*) FROM venues").fetchone()[0]
        self.assertEqual(count, 2)

    def test_ensure_venue_ambiguous_when_duplicate_rows_have_no_address(self):
        now = master_db.now_utc()
        self.conn.execute("UPDATE venues SET address = NULL WHERE venue_id = ?", (self.venue_id,))
        other_id = master_db.stable_id("venue", "杜松ホーム", "other")
        self.conn.execute(
            """
            INSERT INTO venues(
              venue_id, origin, canonical_name, normalized_name, area, address,
              review_status, created_at, updated_at
            ) VALUES (?, 'curated', ?, ?, '品川区', NULL, 'active', ?, ?)
            """,
            (other_id, "杜松ホーム", master_db.normalize_text("杜松ホーム"), now, now),
        )
        self.conn.commit()
        before = self.conn.execute("SELECT COUNT(*) FROM venues").fetchone()[0]
        # SQLite permits multiple NULL values in UNIQUE(name, address); ensure_venue
        # coalesces those NULL addresses and must refuse to choose one.
        result = ensure_venue(self.conn, "杜松ホーム")
        self.assertEqual(result["status"], "ambiguous")
        self.assertIsNone(result["venue_id"])
        after = self.conn.execute("SELECT COUNT(*) FROM venues").fetchone()[0]
        self.assertEqual(before, after)

    def test_ensure_venue_creates_instead_of_absorbing_a_similar_name(self):
        now = master_db.now_utc()
        other_id = master_db.stable_id("venue", "杜松ホーム別館", "東京都品川区別")
        self.conn.execute(
            "INSERT INTO venues(venue_id,origin,canonical_name,normalized_name,area,address,review_status,created_at,updated_at) VALUES (?, 'curated', ?, ?, '品川区', '東京都品川区別', 'active', ?, ?)",
            (other_id, "杜松ホーム別館", master_db.normalize_text("杜松ホーム別館"), now, now),
        )
        self.conn.commit()
        # 6e1bb39: 'さくら公園' must not silently become '東葛西さくら公園'.
        result = ensure_venue(self.conn, "杜松ホーム", address="東京都品川区XYZ")
        self.assertEqual(result["status"], "created")
        self.assertNotEqual(result["venue_id"], other_id)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM venues").fetchone()[0], 3)
        self.assertEqual(self.conn.execute("SELECT canonical_name FROM venues WHERE venue_id=?", (other_id,)).fetchone()[0], "杜松ホーム別館")

    def test_find_occurrence_candidates_exact_name(self):
        candidates = find_occurrence_candidates(self.conn, "品川第一盆踊り", event_year=2026)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["occurrence_id"], self.occurrence_id)

    def test_find_occurrence_candidates_no_match(self):
        candidates = find_occurrence_candidates(self.conn, "まったく無関係のイベント名XYZ")
        self.assertEqual(candidates, [])

    def test_ensure_series_and_occurrence_creates_new(self):
        result = ensure_series_and_occurrence(
            self.conn, "新規盆踊りテスト", self.venue_id, 2026, "2026-08-01"
        )
        self.assertTrue(result["occurrence_created"])
        row = self.conn.execute(
            "SELECT source_kind, lifecycle_status FROM event_occurrences WHERE occurrence_id = ?",
            (result["occurrence_id"],),
        ).fetchone()
        self.assertEqual(row[0], "personal_firsthand_current_year")
        self.assertEqual(row[1], "published")

    def test_ensure_series_and_occurrence_reuses_existing_series_and_year(self):
        result = ensure_series_and_occurrence(
            self.conn, "品川第一盆踊り", self.venue_id, 2026, "2026-07-25"
        )
        self.assertFalse(result["occurrence_created"])
        self.assertEqual(result["occurrence_id"], self.occurrence_id)
        count = self.conn.execute("SELECT COUNT(*) FROM event_occurrences").fetchone()[0]
        self.assertEqual(count, 1)

    def test_add_firsthand_evidence_is_idempotent(self):
        first = add_firsthand_evidence(self.conn, self.occurrence_id, "去年の一次情報メモ", event_date="2026-07-25")
        second = add_firsthand_evidence(self.conn, self.occurrence_id, "去年の一次情報メモ", event_date="2026-07-25")
        self.assertEqual(first, second)
        count = self.conn.execute("SELECT COUNT(*) FROM evidence_items WHERE evidence_id = ?", (first,)).fetchone()[0]
        self.assertEqual(count, 1)

    def test_upsert_occurrence_song_is_idempotent(self):
        evidence_id = add_firsthand_evidence(self.conn, self.occurrence_id, "曲目メモ", event_date="2026-07-25")
        first = upsert_occurrence_song(self.conn, self.occurrence_id, "東京音頭", evidence_id)
        second = upsert_occurrence_song(self.conn, self.occurrence_id, "東京音頭", evidence_id)
        self.assertEqual(first["occurrence_song_id"], second["occurrence_song_id"])
        count = self.conn.execute(
            "SELECT COUNT(*) FROM occurrence_songs WHERE occurrence_song_id = ?",
            (first["occurrence_song_id"],),
        ).fetchone()[0]
        self.assertEqual(count, 1)
        row = self.conn.execute(
            "SELECT role, evidence_status, confidence FROM occurrence_songs WHERE occurrence_song_id = ?",
            (first["occurrence_song_id"],),
        ).fetchone()
        self.assertEqual(tuple(row), ("result", "observed", "high"))

    def test_upsert_occurrence_song_uncertain_sets_medium_confidence(self):
        evidence_id = add_firsthand_evidence(self.conn, self.occurrence_id, "うろ覚えの曲目", event_date="2026-07-25")
        applied = upsert_occurrence_song(self.conn, self.occurrence_id, "うろ覚えの曲", evidence_id, uncertain=True)
        confidence = self.conn.execute(
            "SELECT confidence FROM occurrence_songs WHERE occurrence_song_id = ?",
            (applied["occurrence_song_id"],),
        ).fetchone()[0]
        self.assertEqual(confidence, "medium")


if __name__ == "__main__":
    unittest.main()
