import sqlite3
import tempfile
import unittest
from pathlib import Path

from export_rdb_apply_plans import build_plans, write_plans


class ExportRdbApplyPlansTest(unittest.TestCase):
    def make_db(self):
        tempdir = tempfile.TemporaryDirectory()
        db_path = Path(tempdir.name) / "bon_odori.sqlite"
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE events (
              event_id TEXT PRIMARY KEY,
              event_name TEXT,
              start_date TEXT,
              end_date TEXT,
              status TEXT,
              detail TEXT,
              source_url TEXT
            );
            CREATE TABLE evidence_items (
              evidence_id TEXT PRIMARY KEY,
              platform TEXT NOT NULL,
              evidence_type TEXT NOT NULL,
              source_key TEXT,
              source_id TEXT,
              account_key TEXT,
              title TEXT,
              text_excerpt TEXT,
              url TEXT,
              published_at TEXT,
              detected_event_date TEXT,
              raw_status TEXT,
              raw_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE event_evidence_links (
              event_id TEXT NOT NULL,
              evidence_id TEXT NOT NULL,
              link_status TEXT NOT NULL,
              link_source TEXT NOT NULL,
              confidence REAL NOT NULL DEFAULT 0,
              notes TEXT,
              PRIMARY KEY (event_id, evidence_id, link_source)
            );
            CREATE TABLE song_evidence_links (
              song_id TEXT,
              song_title TEXT NOT NULL,
              evidence_id TEXT NOT NULL,
              occurrence_key TEXT,
              link_status TEXT NOT NULL,
              link_source TEXT NOT NULL,
              notes TEXT,
              PRIMARY KEY (song_title, evidence_id, occurrence_key, link_source)
            );
            """
        )
        self.addCleanup(tempdir.cleanup)
        return db_path, conn

    def test_exports_ready_event_and_song_review_rows(self):
        db_path, conn = self.make_db()
        conn.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("event1", "テスト盆踊り", "2026-07-01", "", "確認済み", "詳細", "https://notion.test/event1"),
        )
        conn.execute(
            "INSERT INTO evidence_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "youtube:v1",
                "youtube",
                "video",
                "youtube_active",
                "v1",
                "channel1",
                "テスト動画",
                "説明",
                "https://www.youtube.com/watch?v=v1",
                "2026-07-01T00:00:00+00:00",
                "2026-07-01",
                "append_existing_event",
                "{}",
            ),
        )
        conn.execute(
            "INSERT INTO event_evidence_links VALUES (?, ?, ?, ?, ?, ?)",
            ("event1", "youtube:v1", "matched_existing_event", "youtube_event_match", 0.95, ""),
        )
        conn.execute(
            "INSERT INTO song_evidence_links VALUES (?, ?, ?, ?, ?, ?, ?)",
            (None, "未登録音頭", "youtube:v1", "occ1", "unmatched_song", "youtube_setlist", ""),
        )
        conn.commit()
        conn.close()

        event_plan, song_source, summary = build_plans(db_path)

        self.assertEqual(event_plan["rows"][0]["status"], "ready")
        self.assertEqual(song_source["rows"][0]["term"], "未登録音頭")
        self.assertEqual(summary["song_review_candidates"], 1)

    def test_marks_event_no_action_when_notion_summary_present(self):
        db_path, conn = self.make_db()
        conn.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "event1",
                "山王音頭と民踊大会",
                "2026-06-13",
                "",
                "確認済み",
                "[youtube_evidence] YouTube実績証拠\n- 追加動画: 11件 (詳細は data/youtube_active_existing_event_update_apply_result.json)",
                "",
            ),
        )
        conn.execute(
            "INSERT INTO evidence_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "youtube:v1",
                "youtube",
                "video",
                "youtube_active",
                "v1",
                "channel1",
                "追加動画",
                "",
                "https://www.youtube.com/watch?v=v1",
                "",
                "",
                "append_existing_event",
                "{}",
            ),
        )
        conn.execute(
            "INSERT INTO event_evidence_links VALUES (?, ?, ?, ?, ?, ?)",
            ("event1", "youtube:v1", "matched_existing_event", "youtube_event_match", 0.95, ""),
        )
        conn.commit()
        conn.close()

        event_plan, _, summary = build_plans(db_path)

        self.assertEqual(event_plan["rows"][0]["status"], "no_action_summary_present")
        self.assertEqual(summary["event_plan_counts"], {"no_action_summary_present": 1})

    def test_marks_2025_backfill_event_for_batch_review(self):
        db_path, conn = self.make_db()
        conn.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("event1", "既存盆踊り", "2025-07-01", "", "確認済み", "詳細", ""),
        )
        conn.execute(
            "INSERT INTO evidence_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "youtube:v1",
                "youtube",
                "video",
                "youtube_active",
                "v1",
                "channel1",
                "2025動画",
                "",
                "https://www.youtube.com/watch?v=v1",
                "2025-07-01T00:00:00Z",
                "",
                "append_existing_event",
                "{}",
            ),
        )
        conn.execute(
            "INSERT INTO event_evidence_links VALUES (?, ?, ?, ?, ?, ?)",
            ("event1", "youtube:v1", "matched_existing_event", "youtube_event_match", 0.95, ""),
        )
        conn.commit()
        conn.close()

        event_plan, _, summary = build_plans(db_path)

        self.assertEqual(event_plan["rows"][0]["status"], "review_batch_2025_backfill")
        self.assertEqual(summary["event_plan_counts"], {"review_batch_2025_backfill": 1})

    def test_writes_plan_files(self):
        event_plan = {"generated_at": "now", "database": "db", "rows": []}
        song_source = {"generated_at": "now", "database": "db", "rows": []}
        summary = {"generated_at": "now"}
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            write_plans(
                event_plan,
                song_source,
                summary,
                temp / "event.json",
                temp / "event.md",
                temp / "song.json",
                temp / "song.md",
                temp / "summary.json",
            )
            self.assertTrue((temp / "event.json").exists())
            self.assertTrue((temp / "song.md").exists())


if __name__ == "__main__":
    unittest.main()
