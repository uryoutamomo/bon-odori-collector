import json
import sqlite3
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from master_rdb import audit as audit_master_rdb
import master_rdb.master_db as master_db
from report_apply import apply_official_notice_report as script
class ApplyOfficialNoticeReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)
        self.db_path = self.tmp_path / "master.sqlite"
        conn = master_db.init_db(self.db_path)
        conn.close()
        self._seed()

        patches = [
            mock.patch.object(script, "BACKUP_DIR", self.tmp_path / "backups"),
            mock.patch.object(script, "PREFLIGHT_DB", self.tmp_path / "preflight.sqlite"),
            mock.patch.object(script, "refresh_manifest_database_state", lambda *a, **k: None),
            mock.patch.object(audit_master_rdb, "NOTION_DB", self.tmp_path / "no_notion.sqlite"),
            mock.patch.object(audit_master_rdb, "SONG_OCCURRENCES", self.tmp_path / "no_song_occurrences.json"),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _seed(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        now = master_db.now_utc()
        self.venue_a_id = master_db.stable_id("venue", "京橋プラザ区民館", "")
        conn.execute(
            """
            INSERT INTO venues(venue_id, origin, canonical_name, normalized_name, area, address, review_status, created_at, updated_at)
            VALUES (?, 'curated', ?, ?, '中央区', '', 'active', ?, ?)
            """,
            (self.venue_a_id, "京橋プラザ区民館", master_db.normalize_text("京橋プラザ区民館"), now, now),
        )
        self.series_a_id = master_db.stable_id("series", master_db.normalize_text("新富町会納涼盆踊り大会"))
        conn.execute(
            """
            INSERT INTO event_series(series_id, origin, series_key, canonical_name, normalized_name, usual_venue_id, area, program_type, annual_months_json, status, created_at, updated_at)
            VALUES (?, 'curated', ?, ?, ?, ?, '中央区', 'bon_odori', '[7]', 'active', ?, ?)
            """,
            (
                self.series_a_id,
                master_db.normalize_text("新富町会納涼盆踊り大会"),
                "新富町会納涼盆踊り大会",
                master_db.normalize_text("新富町会納涼盆踊り大会"),
                self.venue_a_id,
                now,
                now,
            ),
        )
        self.occurrence_a_id = master_db.stable_id("occ", self.series_a_id, 2026, 1)
        conn.execute(
            """
            INSERT INTO event_occurrences(occurrence_id, origin, series_id, event_year, occurrence_sequence, display_name, venue_id, date_status, lifecycle_status, confidence, source_kind, created_at, updated_at)
            VALUES (?, 'curated', ?, 2026, 1, ?, ?, 'unknown', '未確認', 'unknown', 'notion_events', ?, ?)
            """,
            (self.occurrence_a_id, self.series_a_id, "新富町会納涼盆踊り大会", self.venue_a_id, now, now),
        )
        conn.commit()
        conn.close()

    def _write_report(self, payload, name="report.json"):
        path = self.tmp_path / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def _args(self, report_path, apply=False, confirm=""):
        return Namespace(
            report=report_path,
            master_db=self.db_path,
            out_db=self.tmp_path / "dry_run.sqlite",
            out_json=self.tmp_path / "report_out.json",
            out_md=self.tmp_path / "report_out.md",
            apply=apply,
            confirm=confirm,
        )

    def _base_report(self, events, skipped_events=None):
        return {
            "report_type": "official_notice",
            "reported_at": "2026-07-13T00:00:00+09:00",
            "source": {
                "report_id": "test_notice_report",
                "title": "テストチラシ",
                "account_key": "テスト町会連合",
                "raw_text": "テストチラシの全文",
            },
            "events": events,
            "skipped_events": skipped_events or [],
        }

    def test_partial_apply_when_one_of_three_events_is_unresolved(self):
        report = self._base_report(
            [
                {
                    "action": "confirm_existing",
                    "occurrence_id": self.occurrence_a_id,
                    "date_start": "2026-07-17",
                    "date_end": "2026-07-18",
                    "detail_addendum": "19:00-21:00開催。",
                    "songs": [],
                },
                {
                    "action": "confirm_existing",
                    "occurrence_id": "occ_does_not_exist",
                    "date_start": "2026-08-03",
                    "songs": [],
                },
                {
                    "action": "register_new",
                    "event_name_hint": "明石町会 納涼盆踊り",
                    "event_year": 2026,
                    "date_start": "2026-08-06",
                    "date_end": "2026-08-07",
                    "venue": {"name": "明石小学校", "area": "中央区"},
                    "songs": [{"title": "炭坑節"}],
                },
            ]
        )
        report_path = self._write_report(report)
        result = script.run(self._args(report_path, apply=True, confirm="APPLY OFFICIAL NOTICE FIELD REPORT"))

        self.assertTrue(result["write_guard"]["db_committed"])
        self.assertEqual(len(result["applied"]["events_applied"]), 2)
        self.assertEqual(result["applied"]["events_unresolved"], [1])
        self.assertEqual(result["summary"]["issues_by_severity"], {"medium": 1})
        registered = result["applied"]["events_applied"][1]
        self.assertTrue(registered["series_created"])
        self.assertEqual(registered["venue_status"], "created")

        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT date_start, date_status FROM event_occurrences WHERE occurrence_id = ?", (self.occurrence_a_id,)
        ).fetchone()
        self.assertEqual(row, ("2026-07-17", "confirmed"))
        akashi_count = conn.execute(
            "SELECT COUNT(*) FROM event_occurrences WHERE display_name = '明石町会 納涼盆踊り'"
        ).fetchone()[0]
        self.assertEqual(akashi_count, 1)
        conn.close()

    def test_apply_requires_confirm_phrase(self):
        report = self._base_report(
            [{"action": "confirm_existing", "occurrence_id": self.occurrence_a_id, "date_start": "2026-07-17", "songs": []}]
        )
        report_path = self._write_report(report)
        with self.assertRaises(ValueError):
            script.run(self._args(report_path, apply=True, confirm="WRONG PHRASE"))

    def test_evidence_is_shared_across_multiple_events(self):
        report = self._base_report(
            [
                {"action": "confirm_existing", "occurrence_id": self.occurrence_a_id, "date_start": "2026-07-17", "songs": []},
                {
                    "action": "register_new",
                    "event_name_hint": "明石町会 納涼盆踊り",
                    "event_year": 2026,
                    "date_start": "2026-08-06",
                    "venue": {"name": "明石小学校"},
                    "songs": [],
                },
            ]
        )
        report_path = self._write_report(report)
        result = script.run(self._args(report_path))
        evidence_id = result["applied"]["evidence_id"]

        conn = sqlite3.connect(self.tmp_path / "dry_run.sqlite")
        evidence_count = conn.execute("SELECT COUNT(*) FROM evidence_items WHERE evidence_id = ?", (evidence_id,)).fetchone()[0]
        link_count = conn.execute("SELECT COUNT(*) FROM occurrence_evidence_links WHERE evidence_id = ?", (evidence_id,)).fetchone()[0]
        conn.close()
        self.assertEqual(evidence_count, 1)
        self.assertEqual(link_count, 2)

    def test_register_new_song_uses_setlist_announced(self):
        report = self._base_report(
            [
                {
                    "action": "register_new",
                    "event_name_hint": "曲目告知イベント",
                    "event_year": 2026,
                    "date_start": "2026-08-20",
                    "venue": {"name": "テスト会場"},
                    "songs": [{"title": "東京音頭"}],
                }
            ]
        )
        report_path = self._write_report(report)
        result = script.run(self._args(report_path, apply=True, confirm="APPLY OFFICIAL NOTICE FIELD REPORT"))
        song = result["applied"]["events_applied"][0]["songs_applied"][0]

        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT role, evidence_status FROM occurrence_songs WHERE occurrence_song_id = ?", (song["occurrence_song_id"],)
        ).fetchone()
        conn.close()
        self.assertEqual(row, ("setlist", "announced"))

    def test_double_apply_is_idempotent(self):
        report = self._base_report(
            [
                {"action": "confirm_existing", "occurrence_id": self.occurrence_a_id, "date_start": "2026-07-17", "songs": []},
                {
                    "action": "register_new",
                    "event_name_hint": "冪等テストイベント",
                    "event_year": 2026,
                    "date_start": "2026-08-22",
                    "venue": {"name": "冪等テスト会場"},
                    "songs": [{"title": "炭坑節"}],
                },
            ]
        )
        report_path = self._write_report(report)
        script.run(self._args(report_path, apply=True, confirm="APPLY OFFICIAL NOTICE FIELD REPORT"))
        script.run(self._args(report_path, apply=True, confirm="APPLY OFFICIAL NOTICE FIELD REPORT"))

        conn = sqlite3.connect(self.db_path)
        occ_count = conn.execute(
            "SELECT COUNT(*) FROM event_occurrences WHERE display_name = '冪等テストイベント'"
        ).fetchone()[0]
        venue_count = conn.execute("SELECT COUNT(*) FROM venues WHERE canonical_name = '冪等テスト会場'").fetchone()[0]
        song_count = conn.execute(
            "SELECT COUNT(*) FROM occurrence_songs WHERE normalized_title = ?", (master_db.normalize_text("炭坑節"),)
        ).fetchone()[0]
        evidence_count = conn.execute("SELECT COUNT(*) FROM evidence_items").fetchone()[0]
        conn.close()
        self.assertEqual(occ_count, 1)
        self.assertEqual(venue_count, 1)
        self.assertEqual(song_count, 1)
        self.assertEqual(evidence_count, 1)

    def test_reapplying_notice_does_not_restore_detail_removed_by_curated_replacement(self):
        report = self._base_report(
            [
                {
                    "action": "confirm_existing",
                    "occurrence_id": self.occurrence_a_id,
                    "detail_addendum": "開催時間：18:00〜20:00。私人の情報源名。",
                    "songs": [],
                }
            ]
        )
        report_path = self._write_report(report)
        script.run(self._args(report_path, apply=True, confirm="APPLY OFFICIAL NOTICE FIELD REPORT"))

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE event_occurrences SET detail = ? WHERE occurrence_id = ?",
            ("開催時間：18:00〜20:00。", self.occurrence_a_id),
        )
        conn.commit()
        conn.close()

        script.run(self._args(report_path, apply=True, confirm="APPLY OFFICIAL NOTICE FIELD REPORT"))

        conn = sqlite3.connect(self.db_path)
        detail = conn.execute(
            "SELECT detail FROM event_occurrences WHERE occurrence_id = ?", (self.occurrence_a_id,)
        ).fetchone()[0]
        conn.close()
        self.assertEqual(detail, "開催時間：18:00〜20:00。")

    def test_reapplying_older_replacement_does_not_overwrite_newer_notice_replacement(self):
        report_a = self._base_report(
            [
                {
                    "action": "confirm_existing",
                    "occurrence_id": self.occurrence_a_id,
                    "date_start": "2026-07-17",
                    "venue": {"name": "京橋プラザ区民館", "area": "中央区"},
                    "detail_replacement": "A通知の本文。",
                    "songs": [{"title": "炭坑節"}],
                }
            ]
        )
        report_b = self._base_report(
            [
                {
                    "action": "confirm_existing",
                    "occurrence_id": self.occurrence_a_id,
                    "detail_replacement": "B通知の本文。",
                    "songs": [],
                }
            ]
        )
        report_b["source"]["report_id"] = "test_notice_report_b"
        report_a_path = self._write_report(report_a, "report-a.json")
        report_b_path = self._write_report(report_b, "report-b.json")

        script.run(self._args(report_a_path, apply=True, confirm="APPLY OFFICIAL NOTICE FIELD REPORT"))
        script.run(self._args(report_b_path, apply=True, confirm="APPLY OFFICIAL NOTICE FIELD REPORT"))
        script.run(self._args(report_a_path, apply=True, confirm="APPLY OFFICIAL NOTICE FIELD REPORT"))

        conn = sqlite3.connect(self.db_path)
        detail = conn.execute(
            "SELECT detail FROM event_occurrences WHERE occurrence_id = ?", (self.occurrence_a_id,)
        ).fetchone()[0]
        date_start = conn.execute(
            "SELECT date_start FROM event_occurrences WHERE occurrence_id = ?", (self.occurrence_a_id,)
        ).fetchone()[0]
        song_count = conn.execute("SELECT COUNT(*) FROM occurrence_songs").fetchone()[0]
        evidence_count = conn.execute("SELECT COUNT(*) FROM evidence_items").fetchone()[0]
        link_count = conn.execute(
            "SELECT COUNT(*) FROM occurrence_evidence_links WHERE occurrence_id = ?", (self.occurrence_a_id,)
        ).fetchone()[0]
        conn.close()
        self.assertEqual(detail, "B通知の本文。")
        self.assertEqual(date_start, "2026-07-17")
        self.assertEqual(song_count, 1)
        self.assertEqual(evidence_count, 2)
        self.assertEqual(link_count, 2)

    def test_rename_series_and_register_new_keeps_one_series_and_prior_alias(self):
        conn = sqlite3.connect(self.db_path)
        prior_occurrence_id = master_db.stable_id("occ", self.series_a_id, 2025, 1)
        conn.execute(
            "UPDATE event_occurrences SET occurrence_id = ?, event_year = 2025 WHERE occurrence_id = ?",
            (prior_occurrence_id, self.occurrence_a_id),
        )
        conn.commit()
        conn.close()
        report = self._base_report(
            [
                {
                    "action": "rename_series_and_register_new",
                    "source_occurrence_id": prior_occurrence_id,
                    "event_name_hint": "新富夏祭り",
                    "event_year": 2026,
                    "date_start": "2026-08-09",
                    "venue": {"name": "京橋プラザ区民館", "area": "中央区"},
                    "detail_addendum": "旧名称との同一性を確認して改名。",
                    "songs": [],
                }
            ]
        )
        result = script.run(self._args(self._write_report(report)))
        self.assertEqual(result["applied"]["events_applied"][0]["action"], "rename_series_and_register_new")

        conn = sqlite3.connect(self.tmp_path / "dry_run.sqlite")
        series = conn.execute(
            "SELECT canonical_name FROM event_series WHERE series_id = ?", (self.series_a_id,)
        ).fetchone()
        alias = conn.execute(
            "SELECT alias FROM event_series_aliases WHERE series_id = ?", (self.series_a_id,)
        ).fetchone()
        occurrences = conn.execute(
            "SELECT event_year, display_name FROM event_occurrences WHERE series_id = ? ORDER BY event_year", (self.series_a_id,)
        ).fetchall()
        conn.close()
        self.assertEqual(series, ("新富夏祭り",))
        self.assertEqual(alias, ("新富町会納涼盆踊り大会",))
        self.assertEqual(occurrences, [(2025, "新富夏祭り"), (2026, "新富夏祭り")])

    def test_add_occurrence_to_existing_series_uses_source_occurrence_series(self):
        conn = sqlite3.connect(self.db_path)
        prior_occurrence_id = master_db.stable_id("occ", self.series_a_id, 2025, 1)
        conn.execute(
            "UPDATE event_occurrences SET occurrence_id = ?, event_year = 2025 WHERE occurrence_id = ?",
            (prior_occurrence_id, self.occurrence_a_id),
        )
        conn.commit()
        conn.close()
        report = self._base_report(
            [
                {
                    "action": "add_occurrence_to_existing_series",
                    "source_occurrence_id": prior_occurrence_id,
                    "event_name_hint": "新富町会納涼盆踊り大会",
                    "event_year": 2026,
                    "date_start": "2026-08-09",
                    "venue": {"name": "京橋プラザ区民館", "area": "中央区"},
                    "songs": [],
                }
            ]
        )
        result = script.run(self._args(self._write_report(report)))
        applied = result["applied"]["events_applied"][0]
        self.assertEqual(applied["action"], "add_occurrence_to_existing_series")
        self.assertEqual(applied["series_id"], self.series_a_id)
        self.assertFalse(applied["series_created"])
        conn = sqlite3.connect(self.tmp_path / "dry_run.sqlite")
        occurrences = conn.execute(
            "SELECT event_year FROM event_occurrences WHERE series_id = ? ORDER BY event_year", (self.series_a_id,)
        ).fetchall()
        series_count = conn.execute("SELECT COUNT(*) FROM event_series").fetchone()[0]
        conn.close()
        self.assertEqual(occurrences, [(2025,), (2026,)])
        self.assertEqual(series_count, 1)

    def test_merge_existing_series_moves_current_occurrence_and_deletes_split_series(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        now = master_db.now_utc()
        prior_occurrence_id = master_db.stable_id("occ", self.series_a_id, 2025, 1)
        conn.execute(
            "UPDATE event_occurrences SET occurrence_id = ?, event_year = 2025 WHERE occurrence_id = ?",
            (prior_occurrence_id, self.occurrence_a_id),
        )
        split_series_id = master_db.stable_id("series", master_db.normalize_text("新富夏祭り"))
        split_occurrence_id = master_db.stable_id("occ", split_series_id, 2026, 1)
        conn.execute(
            """INSERT INTO event_series(series_id, origin, series_key, canonical_name, normalized_name, usual_venue_id, area, program_type, annual_months_json, status, created_at, updated_at)
               VALUES (?, 'curated', ?, '新富夏祭り', ?, ?, '中央区', 'bon_odori', '[8]', 'active', ?, ?)""",
            (split_series_id, master_db.normalize_text("新富夏祭り"), master_db.normalize_text("新富夏祭り"), self.venue_a_id, now, now),
        )
        conn.execute(
            """INSERT INTO event_occurrences(occurrence_id, origin, series_id, event_year, occurrence_sequence, display_name, venue_id, date_status, lifecycle_status, confidence, source_kind, created_at, updated_at)
               VALUES (?, 'curated', ?, 2026, 1, '新富夏祭り', ?, 'unknown', '未確認', 'unknown', 'notion_events', ?, ?)""",
            (split_occurrence_id, split_series_id, self.venue_a_id, now, now),
        )
        conn.commit()
        conn.close()
        report = self._base_report(
            [{
                "action": "merge_existing_series",
                "source_occurrence_id": prior_occurrence_id,
                "target_occurrence_id": split_occurrence_id,
                "event_name_hint": "新富夏祭り",
                "songs": [],
            }]
        )
        result = script.run(self._args(self._write_report(report)))
        self.assertEqual(result["applied"]["events_applied"][0]["action"], "merge_existing_series")
        conn = sqlite3.connect(self.tmp_path / "dry_run.sqlite")
        series = conn.execute("SELECT canonical_name FROM event_series WHERE series_id = ?", (self.series_a_id,)).fetchone()
        deleted = conn.execute("SELECT COUNT(*) FROM event_series WHERE series_id = ?", (split_series_id,)).fetchone()[0]
        occurrences = conn.execute("SELECT event_year, display_name FROM event_occurrences WHERE series_id = ? ORDER BY event_year", (self.series_a_id,)).fetchall()
        conn.close()
        self.assertEqual(series, ("新富夏祭り",))
        self.assertEqual(deleted, 0)
        self.assertEqual(occurrences, [(2025, "新富夏祭り"), (2026, "新富夏祭り")])

if __name__ == "__main__":
    unittest.main()
