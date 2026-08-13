import json
import sqlite3
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from master_rdb import audit as audit_master_rdb
import master_rdb.master_db as master_db
from report_apply import apply_firsthand_field_report as script
class ApplyFirsthandFieldReportTest(unittest.TestCase):
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
        self.venue_id = master_db.stable_id("venue", "杜松ホーム", "東京都品川区")
        conn.execute(
            """
            INSERT INTO venues(
              venue_id, origin, canonical_name, normalized_name, area, address,
              review_status, created_at, updated_at
            ) VALUES (?, 'curated', ?, ?, '品川区', '東京都品川区', 'active', ?, ?)
            """,
            (self.venue_id, "杜松ホーム", master_db.normalize_text("杜松ホーム"), now, now),
        )
        self.series_id = master_db.stable_id("series", master_db.normalize_text("品川第一盆踊り"))
        conn.execute(
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
        conn.execute(
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

    def test_dry_run_existing_event_songs_with_explicit_occurrence_id(self):
        report_path = self._write_report(
            {
                "report_type": "existing_event_songs",
                "raw_note": "今年参加して東京音頭を聴いた",
                "event_name_hint": "品川第一盆踊り",
                "event_year": 2026,
                "event_date": "2026-07-25",
                "occurrence_id": self.occurrence_id,
                "songs": [{"title": "東京音頭"}],
            }
        )
        result = script.run(self._args(report_path))
        self.assertEqual(result["mode"], "dry_run")
        self.assertTrue(result["applied"]["resolved"])
        self.assertEqual(result["applied"]["occurrence_id"], self.occurrence_id)
        self.assertEqual(result["summary"]["issues_by_severity"], {})

        # dry run must never touch the master DB
        conn = sqlite3.connect(self.db_path)
        count = conn.execute("SELECT COUNT(*) FROM occurrence_songs").fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)

        dry_run_conn = sqlite3.connect(self.tmp_path / "dry_run.sqlite")
        dry_count = dry_run_conn.execute("SELECT COUNT(*) FROM occurrence_songs").fetchone()[0]
        dry_run_conn.close()
        self.assertEqual(dry_count, 1)

    def test_same_named_occurrences_without_id_block_write(self):
        # Two exact names are a real ambiguity; a merely longer similar name is not.
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        now = master_db.now_utc()
        other_series_id = master_db.stable_id("series", master_db.normalize_text("品川第一盆踊り duplicate"))
        conn.execute(
            """
            INSERT INTO event_series(
              series_id, origin, series_key, canonical_name, normalized_name,
              usual_venue_id, area, program_type, annual_months_json, status, created_at, updated_at
            ) VALUES (?, 'curated', ?, ?, ?, ?, '品川区', 'bon_odori', '[7]', 'active', ?, ?)
            """,
            (
                other_series_id,
                master_db.normalize_text("品川第一盆踊り duplicate"),
                "品川第一盆踊り duplicate",
                master_db.normalize_text("品川第一盆踊り duplicate"),
                self.venue_id,
                now,
                now,
            ),
        )
        other_occurrence_id = master_db.stable_id("occ", other_series_id, 2026, 1)
        conn.execute(
            """
            INSERT INTO event_occurrences(
              occurrence_id, origin, series_id, event_year, occurrence_sequence,
              display_name, venue_id, date_start, date_end, date_status,
              lifecycle_status, confidence, source_kind, created_at, updated_at
            ) VALUES (?, 'curated', ?, 2026, 1, ?, ?, '2026-07-26', '2026-07-26', 'confirmed',
              'published', 'confirmed', 'official_current_year', ?, ?)
            """,
            (other_occurrence_id, other_series_id, "品川第一盆踊り", self.venue_id, now, now),
        )
        conn.commit()
        conn.close()

        report_path = self._write_report(
            {
                "report_type": "existing_event_songs",
                "raw_note": "曖昧なイベント名で参加",
                "event_name_hint": "品川第一盆踊り",
                "event_year": 2026,
                "event_date": "2026-07-25",
                "songs": [{"title": "東京音頭"}],
            }
        )
        result = script.run(self._args(report_path))
        self.assertFalse(result["applied"]["resolved"])
        self.assertEqual(result["summary"]["issues_by_severity"].get("high"), 1)
        self.assertFalse(result["write_guard"]["db_committed"])

        conn = sqlite3.connect(self.db_path)
        count = conn.execute("SELECT COUNT(*) FROM occurrence_songs").fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)

    def test_apply_new_event_requires_confirm_phrase(self):
        report_path = self._write_report(
            {
                "report_type": "new_event",
                "raw_note": "新しい盆踊りに参加した",
                "event_name_hint": "新規テスト盆踊り",
                "event_year": 2026,
                "event_date": "2026-08-01",
                "venue": {"name": "新規テスト会場", "address": "東京都大田区9-9-9"},
                "songs": [{"title": "炭坑節"}],
            }
        )
        with self.assertRaises(ValueError):
            script.run(self._args(report_path, apply=True, confirm="WRONG PHRASE"))

    def test_apply_new_event_creates_venue_series_occurrence_and_songs(self):
        report_path = self._write_report(
            {
                "report_type": "new_event",
                "raw_note": "新しい盆踊りに参加して2曲聴いた",
                "event_name_hint": "新規テスト盆踊り",
                "event_year": 2026,
                "event_date": "2026-08-01",
                "venue": {"name": "新規テスト会場", "address": "東京都大田区9-9-9"},
                "songs": [{"title": "炭坑節"}, {"title": "うろ覚えの曲", "uncertain": True}],
            }
        )
        result = script.run(
            self._args(report_path, apply=True, confirm="APPLY FIRSTHAND FIELD REPORT")
        )
        self.assertEqual(result["mode"], "apply")
        self.assertTrue(result["applied"]["resolved"])
        self.assertTrue(result["write_guard"]["db_committed"])
        self.assertEqual(result["summary"]["issues_by_severity"], {})

        conn = sqlite3.connect(self.db_path)
        venue_count = conn.execute(
            "SELECT COUNT(*) FROM venues WHERE canonical_name = '新規テスト会場'"
        ).fetchone()[0]
        occurrence_count = conn.execute(
            "SELECT COUNT(*) FROM event_occurrences WHERE display_name = '新規テスト盆踊り'"
        ).fetchone()[0]
        song_count = conn.execute("SELECT COUNT(*) FROM occurrence_songs").fetchone()[0]
        source_kind = conn.execute(
            "SELECT source_kind FROM event_occurrences WHERE display_name = '新規テスト盆踊り'"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(venue_count, 1)
        self.assertEqual(occurrence_count, 1)
        self.assertEqual(song_count, 2)
        self.assertEqual(source_kind, "personal_firsthand_current_year")

    def test_double_apply_is_idempotent(self):
        report_path = self._write_report(
            {
                "report_type": "new_event",
                "raw_note": "冪等性チェック用イベント",
                "event_name_hint": "冪等テスト盆踊り",
                "event_year": 2026,
                "event_date": "2026-08-15",
                "venue": {"name": "冪等テスト会場", "address": "東京都世田谷区1-1-1"},
                "songs": [{"title": "炭坑節"}],
            }
        )
        script.run(self._args(report_path, apply=True, confirm="APPLY FIRSTHAND FIELD REPORT"))
        script.run(self._args(report_path, apply=True, confirm="APPLY FIRSTHAND FIELD REPORT"))

        conn = sqlite3.connect(self.db_path)
        venue_count = conn.execute(
            "SELECT COUNT(*) FROM venues WHERE canonical_name = '冪等テスト会場'"
        ).fetchone()[0]
        occurrence_count = conn.execute(
            "SELECT COUNT(*) FROM event_occurrences WHERE display_name = '冪等テスト盆踊り'"
        ).fetchone()[0]
        song_count = conn.execute(
            "SELECT COUNT(*) FROM occurrence_songs WHERE normalized_title = ?",
            (master_db.normalize_text("炭坑節"),),
        ).fetchone()[0]
        conn.close()
        self.assertEqual(venue_count, 1)
        self.assertEqual(occurrence_count, 1)
        self.assertEqual(song_count, 1)


if __name__ == "__main__":
    unittest.main()
