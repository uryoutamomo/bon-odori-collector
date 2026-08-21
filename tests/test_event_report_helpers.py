import sqlite3
import tempfile
import unittest
from pathlib import Path

import master_rdb.master_db as master_db
from report_apply.event_report_helpers import (
    confirm_occurrence_schedule_venue,
    ensure_series_and_occurrence,
    ensure_venue,
    explicit_tokyo23_ward,
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

    def test_confirm_occurrence_schedule_venue_detail_replacement_overwrites(self):
        """detail_replacement は既存の文面を丸ごと置き換える。

        追記しかできないと、公開してはいけない記述（私人の情報源名やXの個人
        アカウント名）を後から取り除けない。2026-08-08 の方針決定で必要になった。
        """
        confirm_occurrence_schedule_venue(
            self.conn, self.occurrence_id,
            detail_addendum="出典：地域情報サイト。@someone の報告で確認。",
            source_kind="official_current_year",
        )
        confirm_occurrence_schedule_venue(
            self.conn, self.occurrence_id,
            detail_replacement="現地の参加報告で開催を確認済み。",
            source_kind="official_current_year",
        )
        detail = self.conn.execute(
            "SELECT detail FROM event_occurrences WHERE occurrence_id = ?", (self.occurrence_id,)
        ).fetchone()[0]
        self.assertEqual(detail, "現地の参加報告で開催を確認済み。")
        self.assertNotIn("@someone", detail)
        self.assertNotIn("地域情報サイト", detail)

    def test_confirm_occurrence_schedule_venue_rejects_addendum_and_replacement_together(self):
        """どちらが最終形か決まらないので、同時指定は拒否する。"""
        with self.assertRaises(ValueError):
            confirm_occurrence_schedule_venue(
                self.conn, self.occurrence_id,
                detail_addendum="足す文。",
                detail_replacement="置き換える文。",
                source_kind="official_current_year",
            )

    def test_confirm_occurrence_schedule_venue_updates_venue_and_date(self):
        result = confirm_occurrence_schedule_venue(
            self.conn,
            self.occurrence_id,
            venue_id=self.other_venue_id,
            date_start="2026-08-03",
            date_end="2026-08-05",
            source_kind="official_current_year",
            as_of_date="2026-08-01",
        )
        self.assertIn("venue_id", result["changed_fields"])
        self.assertIn("date_start", result["changed_fields"])
        self.assertIn("current_event_state", result["changed_fields"])
        row = self.conn.execute(
            "SELECT venue_id, date_start, date_end, date_status, lifecycle_status, confidence, source_kind, current_event_state, date_certainty_tier FROM event_occurrences WHERE occurrence_id = ?",
            (self.occurrence_id,),
        ).fetchone()
        self.assertEqual(
            tuple(row), (self.other_venue_id, "2026-08-03", "2026-08-05", "confirmed", "published", "high", "official_current_year", "confirmed", "confirmed")
        )
        date_count = self.conn.execute("SELECT COUNT(*) FROM occurrence_dates WHERE occurrence_id = ?", (self.occurrence_id,)).fetchone()[0]
        self.assertEqual(date_count, 1)

    def test_confirm_occurrence_schedule_venue_marks_past_schedule_ended(self):
        result = confirm_occurrence_schedule_venue(
            self.conn, self.occurrence_id, date_start="2026-07-13", date_end="2026-07-15",
            source_kind="official_current_year", as_of_date="2026-07-30",
        )
        self.assertIn("current_event_state", result["changed_fields"])
        row = self.conn.execute(
            "SELECT current_event_state, date_certainty_tier FROM event_occurrences WHERE occurrence_id = ?", (self.occurrence_id,)
        ).fetchone()
        self.assertEqual(tuple(row), ("ended", "confirmed"))

    def test_confirm_schedule_date_correction_replaces_only_confirmed_cache(self):
        confirm_occurrence_schedule_venue(
            self.conn, self.occurrence_id, date_start="2026-08-07", date_end="2026-08-09",
            source_kind="official_current_year", as_of_date="2026-08-01",
        )
        historical_id = master_db.stable_id("date", self.occurrence_id, "2025-08-09", "2025-08-11", "historical_reference")
        self.conn.execute(
            """INSERT INTO occurrence_dates(
                occurrence_date_id, occurrence_id, date_start, date_end, date_type,
                confidence, basis, created_at
            ) VALUES (?, ?, '2025-08-09', '2025-08-11', 'historical_reference', 'medium', '', ?)""",
            (historical_id, self.occurrence_id, master_db.now_utc()),
        )
        confirm_occurrence_schedule_venue(
            self.conn, self.occurrence_id, date_start="2026-08-07", date_end="2026-08-16",
            source_kind="official_current_year", as_of_date="2026-08-01",
        )
        rows = self.conn.execute(
            """SELECT date_start, date_end, date_type FROM occurrence_dates
               WHERE occurrence_id = ? ORDER BY date_type, date_start""",
            (self.occurrence_id,),
        ).fetchall()
        self.assertEqual([tuple(row) for row in rows], [
            ("2026-08-07", "2026-08-16", "confirmed"),
            ("2025-08-09", "2025-08-11", "historical_reference"),
        ])

    def test_ended_schedule_correction_replaces_only_current_year_cache(self):
        confirm_occurrence_schedule_venue(
            self.conn,
            self.occurrence_id,
            date_start="2026-07-01",
            date_end="2026-07-02",
            date_status="ended",
            source_kind="official_current_year",
            as_of_date="2026-08-01",
        )
        historical_id = master_db.stable_id(
            "date", self.occurrence_id, "2025-07-01", "2025-07-02", "historical_reference"
        )
        self.conn.execute(
            """INSERT INTO occurrence_dates(
                occurrence_date_id, occurrence_id, date_start, date_end, date_type,
                confidence, basis, created_at
            ) VALUES (?, ?, '2025-07-01', '2025-07-02', 'historical_reference', 'medium', '', ?)""",
            (historical_id, self.occurrence_id, master_db.now_utc()),
        )

        confirm_occurrence_schedule_venue(
            self.conn,
            self.occurrence_id,
            date_start="2026-07-03",
            date_end="2026-07-04",
            date_status="ended",
            source_kind="official_current_year",
            as_of_date="2026-08-01",
        )

        rows = self.conn.execute(
            """SELECT date_start, date_end, date_type FROM occurrence_dates
               WHERE occurrence_id = ? ORDER BY date_type, date_start""",
            (self.occurrence_id,),
        ).fetchall()
        self.assertEqual(
            [tuple(row) for row in rows],
            [
                ("2026-07-03", "2026-07-04", "ended"),
                ("2025-07-01", "2025-07-02", "historical_reference"),
            ],
        )

    def test_confirm_occurrence_schedule_venue_uses_existing_date_for_venue_only_update(self):
        self.conn.execute(
            "UPDATE event_occurrences SET date_start='2026-07-13', date_end='2026-07-15' WHERE occurrence_id=?", (self.occurrence_id,)
        )
        result = confirm_occurrence_schedule_venue(
            self.conn, self.occurrence_id, venue_id=self.other_venue_id, as_of_date="2026-07-30"
        )
        self.assertIn("current_event_state", result["changed_fields"])
        row = self.conn.execute(
            "SELECT current_event_state, date_certainty_tier FROM event_occurrences WHERE occurrence_id = ?", (self.occurrence_id,)
        ).fetchone()
        self.assertEqual(tuple(row), ("ended", "confirmed"))

    def test_confirm_occurrence_schedule_venue_keeps_state_when_venue_only_update_has_no_dates(self):
        result = confirm_occurrence_schedule_venue(
            self.conn, self.occurrence_id, venue_id=self.other_venue_id, as_of_date="2026-07-30"
        )
        self.assertNotIn("current_event_state", result["changed_fields"])
        row = self.conn.execute(
            "SELECT current_event_state, date_certainty_tier FROM event_occurrences WHERE occurrence_id = ?", (self.occurrence_id,)
        ).fetchone()
        self.assertEqual(tuple(row), ("predicted", "historical_reference"))

    def test_ensure_series_and_occurrence_uses_given_source_kind(self):
        result = ensure_series_and_occurrence(
            self.conn, "新規テストイベント", self.venue_id, 2026, "2026-08-06", source_kind="official_current_year"
        )
        row = self.conn.execute(
            "SELECT source_kind, lifecycle_status FROM event_occurrences WHERE occurrence_id = ?", (result["occurrence_id"],)
        ).fetchone()
        self.assertEqual(tuple(row), ("official_current_year", "published"))

    def test_ensure_venue_fills_area_only_from_an_explicit_ward(self):
        cases = (
            ("北区立堀船公園", "", "北区"),
            ("鵜の木児童公園", "東京都大田区鵜の木2丁目12-4", "大田区"),
            ("堀船公園（北区）", "", "北区"),
        )
        for name, address, expected_area in cases:
            with self.subTest(name=name):
                result = ensure_venue(self.conn, name, address=address)
                area = self.conn.execute(
                    "SELECT area FROM venues WHERE venue_id = ?", (result["venue_id"],)
                ).fetchone()[0]
                self.assertEqual(area, expected_area)
                self.assertEqual(result["area_source"], "explicit_ward_in_name_or_address")

    def test_ensure_venue_does_not_guess_ward_from_town_station_or_non_tokyo_ward(self):
        cases = (
            ("花保広場（花保さくら公園 南花畑3-1）", ""),
            ("新小岩駅南口 駅前広場", ""),
            ("港北公園", "神奈川県横浜市港北区1-1"),
            ("中央公園", "兵庫県神戸市中央区1-1"),
        )
        for name, address in cases:
            with self.subTest(name=name):
                result = ensure_venue(self.conn, name, address=address)
                area = self.conn.execute(
                    "SELECT area FROM venues WHERE venue_id = ?", (result["venue_id"],)
                ).fetchone()[0]
                self.assertIsNone(area)

    def test_ensure_venue_backfills_blank_area_when_exact_venue_is_reused(self):
        result = ensure_venue(self.conn, "北区立堀船公園")
        self.conn.execute("UPDATE venues SET area = NULL WHERE venue_id = ?", (result["venue_id"],))

        reused = ensure_venue(self.conn, "北区立堀船公園")

        area = self.conn.execute(
            "SELECT area FROM venues WHERE venue_id = ?", (result["venue_id"],)
        ).fetchone()[0]
        self.assertEqual(reused["status"], "reused")
        self.assertEqual(area, "北区")

    def test_explicit_tokyo23_ward_fails_closed_on_conflicting_wards(self):
        self.assertIsNone(explicit_tokyo23_ward("北区立公園", "東京都大田区1-1"))

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

    def test_upsert_occurrence_song_current_evidence_clears_inherited_year(self):
        historical_evidence_id = master_db.stable_id("ev", "historical_song_evidence")
        current_evidence_id = master_db.stable_id("ev", "current_song_evidence")
        for evidence_id in (historical_evidence_id, current_evidence_id):
            upsert_evidence_item(
                self.conn,
                evidence_id,
                platform="web",
                evidence_type="video_description",
                source_key=evidence_id,
                text_excerpt="曲目実績",
            )
        upsert_occurrence_song(
            self.conn,
            self.occurrence_id,
            "東京音頭",
            historical_evidence_id,
            role="result",
            evidence_status="observed",
            basis_key="historical_youtube",
            evidence_note="前年実績。",
            inherited_from_year=2025,
        )
        self.conn.execute(
            "UPDATE occurrence_songs SET probability = 51 WHERE occurrence_id = ? AND normalized_title = ?",
            (self.occurrence_id, master_db.normalize_text("東京音頭")),
        )
        upsert_occurrence_song(
            self.conn,
            self.occurrence_id,
            "東京音頭",
            current_evidence_id,
            role="result",
            evidence_status="observed",
            basis_key="firsthand_observed",
            evidence_note="今年実績。",
        )

        row = self.conn.execute(
            "SELECT inherited_from_year, probability, evidence_status FROM occurrence_songs "
            "WHERE occurrence_id = ? AND normalized_title = ?",
            (self.occurrence_id, master_db.normalize_text("東京音頭")),
        ).fetchone()
        self.assertEqual(tuple(row), (None, None, "observed"))

    def test_same_year_additional_evidence_invalidates_probability(self):
        first_evidence_id = master_db.stable_id("ev", "historical_source_one")
        second_evidence_id = master_db.stable_id("ev", "historical_source_two")
        for evidence_id in (first_evidence_id, second_evidence_id):
            upsert_evidence_item(
                self.conn,
                evidence_id,
                platform="web",
                evidence_type="historical_occurrence_report",
                source_key=evidence_id,
                text_excerpt="2025年の曲目実績",
                event_date="2025-08-22",
            )
        upsert_occurrence_song(
            self.conn,
            self.occurrence_id,
            "東京音頭",
            first_evidence_id,
            role="result",
            evidence_status="observed",
            basis_key="historical_curated_report",
            evidence_note="2025年実績その1。",
            inherited_from_year=2025,
        )
        self.conn.execute(
            "UPDATE occurrence_songs SET probability = 51 WHERE occurrence_id = ? AND normalized_title = ?",
            (self.occurrence_id, master_db.normalize_text("東京音頭")),
        )

        upsert_occurrence_song(
            self.conn,
            self.occurrence_id,
            "東京音頭",
            second_evidence_id,
            role="result",
            evidence_status="observed",
            basis_key="historical_curated_report",
            evidence_note="2025年実績その2。",
            inherited_from_year=2025,
        )

        probability = self.conn.execute(
            "SELECT probability FROM occurrence_songs WHERE occurrence_id = ? AND normalized_title = ?",
            (self.occurrence_id, master_db.normalize_text("東京音頭")),
        ).fetchone()[0]
        self.assertIsNone(probability)


if __name__ == "__main__":
    unittest.main()
