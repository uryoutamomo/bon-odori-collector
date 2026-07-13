import sqlite3
import tempfile
import unittest
from pathlib import Path

import master_db
from event_report_helpers import (
    confirm_occurrence_schedule_venue,
    ensure_series_and_occurrence,
    ensure_venue,
    link_occurrence_evidence,
    upsert_evidence_item,
    upsert_occurrence_song,
)


class EventReportHelpersTest(unittest.TestCase):
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
        self.venue_id = master_db.stable_id("venue", "鉄砲洲公園", "")
        self.conn.execute(
            """
            INSERT INTO venues(
              venue_id, origin, canonical_name, normalized_name, area, address,
              review_status, created_at, updated_at
            ) VALUES (?, 'curated', ?, ?, '中央区', '', 'active', ?, ?)
            """,
            (self.venue_id, "鉄砲洲公園", master_db.normalize_text("鉄砲洲公園"), now, now),
        )
        self.other_venue_id = master_db.stable_id("venue", "京橋公園", "")
        self.conn.execute(
            """
            INSERT INTO venues(
              venue_id, origin, canonical_name, normalized_name, area, address,
              review_status, created_at, updated_at
            ) VALUES (?, 'curated', ?, ?, '中央区', '', 'active', ?, ?)
            """,
            (self.other_venue_id, "京橋公園", master_db.normalize_text("京橋公園"), now, now),
        )
        self.series_id = master_db.stable_id("series", master_db.normalize_text("鉄砲洲納涼盆踊り"))
        self.conn.execute(
            """
            INSERT INTO event_series(
              series_id, origin, series_key, canonical_name, normalized_name,
              usual_venue_id, area, program_type, annual_months_json, status, created_at, updated_at
            ) VALUES (?, 'curated', ?, ?, ?, ?, '中央区', 'bon_odori', '[8]', 'active', ?, ?)
            """,
            (
                self.series_id,
                master_db.normalize_text("鉄砲洲納涼盆踊り"),
                "鉄砲洲納涼盆踊り",
                master_db.normalize_text("鉄砲洲納涼盆踊り"),
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
              lifecycle_status, confidence, source_kind, detail, created_at, updated_at
            ) VALUES (?, 'curated', ?, 2026, 1, ?, ?, NULL, NULL, 'unknown',
              '未確認', 'unknown', 'notion_events', '', ?, ?)
            """,
            (self.occurrence_id, self.series_id, "鉄砲洲納涼盆踊り", self.venue_id, now, now),
        )
        self.conn.commit()

    def test_confirm_occurrence_schedule_venue_detail_only(self):
        result = confirm_occurrence_schedule_venue(
            self.conn, self.occurrence_id, detail_addendum="5日中止の場合は6日に順延。", source_kind="official_current_year"
        )
        self.assertEqual(result["changed_fields"], ["detail"])
        row = self.conn.execute(
            "SELECT venue_id, date_start, date_status, detail FROM event_occurrences WHERE occurrence_id = ?",
            (self.occurrence_id,),
        ).fetchone()
        self.assertEqual(row[0], self.venue_id)
        self.assertIsNone(row[1])
        self.assertEqual(row[2], "unknown")
        self.assertEqual(row[3], "5日中止の場合は6日に順延。")

    def test_confirm_occurrence_schedule_venue_detail_addendum_is_idempotent(self):
        confirm_occurrence_schedule_venue(self.conn, self.occurrence_id, detail_addendum="順延あり。", source_kind="official_current_year")
        result = confirm_occurrence_schedule_venue(self.conn, self.occurrence_id, detail_addendum="順延あり。", source_kind="official_current_year")
        self.assertEqual(result["changed_fields"], [])
        detail = self.conn.execute("SELECT detail FROM event_occurrences WHERE occurrence_id = ?", (self.occurrence_id,)).fetchone()[0]
        self.assertEqual(detail.count("順延あり。"), 1)

    def test_confirm_occurrence_schedule_venue_updates_venue_and_date(self):
        result = confirm_occurrence_schedule_venue(
            self.conn,
            self.occurrence_id,
            venue_id=self.other_venue_id,
            date_start="2026-08-03",
            date_end="2026-08-05",
            source_kind="official_current_year",
        )
        self.assertIn("venue_id", result["changed_fields"])
        self.assertIn("date_start", result["changed_fields"])
        row = self.conn.execute(
            "SELECT venue_id, date_start, date_end, date_status, lifecycle_status, confidence, source_kind FROM event_occurrences WHERE occurrence_id = ?",
            (self.occurrence_id,),
        ).fetchone()
        self.assertEqual(
            tuple(row), (self.other_venue_id, "2026-08-03", "2026-08-05", "confirmed", "published", "high", "official_current_year")
        )
        date_count = self.conn.execute("SELECT COUNT(*) FROM occurrence_dates WHERE occurrence_id = ?", (self.occurrence_id,)).fetchone()[0]
        self.assertEqual(date_count, 1)

    def test_ensure_series_and_occurrence_uses_given_source_kind(self):
        result = ensure_series_and_occurrence(
            self.conn, "新規テストイベント", self.venue_id, 2026, "2026-08-06", source_kind="official_current_year"
        )
        row = self.conn.execute(
            "SELECT source_kind, lifecycle_status FROM event_occurrences WHERE occurrence_id = ?", (result["occurrence_id"],)
        ).fetchone()
        self.assertEqual(tuple(row), ("official_current_year", "published"))

    def test_upsert_evidence_item_and_link_occurrence_evidence_shared_across_occurrences(self):
        other_occurrence_id = master_db.stable_id("occ", self.series_id, 2027, 1)
        now = master_db.now_utc()
        self.conn.execute(
            """
            INSERT INTO event_occurrences(
              occurrence_id, origin, series_id, event_year, occurrence_sequence,
              display_name, venue_id, date_status, lifecycle_status, confidence, source_kind,
              created_at, updated_at
            ) VALUES (?, 'curated', ?, 2027, 1, ?, ?, 'unknown', '未確認', 'unknown', 'notion_events', ?, ?)
            """,
            (other_occurrence_id, self.series_id, "鉄砲洲納涼盆踊り", self.venue_id, now, now),
        )
        self.conn.commit()

        evidence_id = master_db.stable_id("ev", "test_shared_evidence")
        upsert_evidence_item(
            self.conn,
            evidence_id,
            platform="web",
            evidence_type="poster_post",
            source_key="test_account",
            text_excerpt="共有チラシの内容",
        )
        link_occurrence_evidence(self.conn, self.occurrence_id, evidence_id, "date_venue_program")
        link_occurrence_evidence(self.conn, other_occurrence_id, evidence_id, "date_venue_program")

        evidence_count = self.conn.execute("SELECT COUNT(*) FROM evidence_items WHERE evidence_id = ?", (evidence_id,)).fetchone()[0]
        self.assertEqual(evidence_count, 1)
        link_count = self.conn.execute("SELECT COUNT(*) FROM occurrence_evidence_links WHERE evidence_id = ?", (evidence_id,)).fetchone()[0]
        self.assertEqual(link_count, 2)

    def test_upsert_occurrence_song_uses_given_role_and_evidence_status(self):
        evidence_id = master_db.stable_id("ev", "test_song_evidence")
        upsert_evidence_item(
            self.conn, evidence_id, platform="web", evidence_type="poster_post", source_key="test_account", text_excerpt="曲目告知"
        )
        applied = upsert_occurrence_song(
            self.conn,
            self.occurrence_id,
            "炭坑節",
            evidence_id,
            role="setlist",
            evidence_status="announced",
            basis_key="official_notice",
            evidence_note="公式掲示物の告知曲目。",
        )
        row = self.conn.execute(
            "SELECT role, evidence_status FROM occurrence_songs WHERE occurrence_song_id = ?", (applied["occurrence_song_id"],)
        ).fetchone()
        self.assertEqual(tuple(row), ("setlist", "announced"))


if __name__ == "__main__":
    unittest.main()
