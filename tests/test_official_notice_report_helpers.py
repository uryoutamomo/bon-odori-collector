import sqlite3
import tempfile
import unittest
from pathlib import Path

import master_db
from report_apply.official_notice_report_helpers import (
    ensure_series_and_occurrence,
    link_notice_evidence,
    upsert_announced_song,
    upsert_notice_evidence,
)


class OfficialNoticeReportHelpersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "master.sqlite"
        conn = master_db.init_db(self.db_path)
        conn.close()
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.addCleanup(self.conn.close)
        now = master_db.now_utc()
        self.venue_id = master_db.stable_id("venue", "明石小学校", "")
        self.conn.execute(
            """
            INSERT INTO venues(
              venue_id, origin, canonical_name, normalized_name, area, address,
              review_status, created_at, updated_at
            ) VALUES (?, 'curated', ?, ?, '中央区', '', 'active', ?, ?)
            """,
            (self.venue_id, "明石小学校", master_db.normalize_text("明石小学校"), now, now),
        )
        self.conn.commit()

    def test_upsert_notice_evidence_writes_web_poster_post(self):
        evidence_id = master_db.stable_id("ev", "official_notice", "test_report", "京橋五の部連合町会")
        upsert_notice_evidence(
            self.conn, evidence_id, title="令和8年 納涼マップ", text_excerpt="チラシ全文", account_key="京橋五の部連合町会"
        )
        row = self.conn.execute(
            "SELECT platform, evidence_type, source_key, account_key FROM evidence_items WHERE evidence_id = ?", (evidence_id,)
        ).fetchone()
        self.assertEqual(tuple(row), ("web", "poster_post", "京橋五の部連合町会", "京橋五の部連合町会"))

    def test_ensure_series_and_occurrence_defaults_to_official_current_year(self):
        result = ensure_series_and_occurrence(self.conn, "明石町会 納涼盆踊り", self.venue_id, 2026, "2026-08-06", "2026-08-07")
        row = self.conn.execute(
            "SELECT source_kind, lifecycle_status, date_status FROM event_occurrences WHERE occurrence_id = ?", (result["occurrence_id"],)
        ).fetchone()
        self.assertEqual(tuple(row), ("official_current_year", "published", "confirmed"))

    def test_ensure_series_and_occurrence_accepts_third_party_source_kind(self):
        result = ensure_series_and_occurrence(
            self.conn, "非公式回覧イベント", self.venue_id, 2026, "2026-08-10", source_kind="third_party_current_year"
        )
        source_kind = self.conn.execute(
            "SELECT source_kind FROM event_occurrences WHERE occurrence_id = ?", (result["occurrence_id"],)
        ).fetchone()[0]
        self.assertEqual(source_kind, "third_party_current_year")

    def test_upsert_announced_song_writes_setlist_announced(self):
        evidence_id = master_db.stable_id("ev", "official_notice", "test_report_songs", "町会")
        upsert_notice_evidence(self.conn, evidence_id, title="チラシ", text_excerpt="曲目告知あり", account_key="町会")
        result = ensure_series_and_occurrence(self.conn, "曲目テストイベント", self.venue_id, 2026, "2026-08-06")
        link_notice_evidence(self.conn, result["occurrence_id"], evidence_id)
        applied = upsert_announced_song(self.conn, result["occurrence_id"], "炭坑節", evidence_id)
        row = self.conn.execute(
            "SELECT role, evidence_status FROM occurrence_songs WHERE occurrence_song_id = ?", (applied["occurrence_song_id"],)
        ).fetchone()
        self.assertEqual(tuple(row), ("setlist", "announced"))


if __name__ == "__main__":
    unittest.main()
