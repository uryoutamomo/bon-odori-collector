import json
import sqlite3
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import apply_reviewed_missing_source_urls as applier


class ApplyReviewedMissingSourceUrlsTest(unittest.TestCase):
    def make_db(self, path):
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE event_series (
              series_id TEXT PRIMARY KEY,
              canonical_name TEXT,
              source_url TEXT
            );
            CREATE TABLE event_occurrences (
              occurrence_id TEXT PRIMARY KEY,
              series_id TEXT,
              display_name TEXT,
              event_year INTEGER,
              venue_id TEXT,
              date_start TEXT,
              date_end TEXT,
              date_status TEXT,
              lifecycle_status TEXT,
              source_kind TEXT,
              source_url TEXT,
              updated_at TEXT
            );
            CREATE TABLE venues (venue_id TEXT PRIMARY KEY);
            """
        )
        conn.execute("INSERT INTO event_series VALUES (?, ?, ?)", ("ser1", "雷門盆踊り（浅草）", ""))
        conn.execute(
            """
            INSERT INTO event_occurrences VALUES (
              'occ1', 'ser1', '雷門盆踊り（浅草）', 2026, NULL, NULL, NULL,
              'unknown', '未確認', 'notion_events', '', 'old'
            )
            """
        )
        conn.commit()
        conn.close()

    def test_dry_run_fills_only_source_url_on_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            master_db = tmp / "master.sqlite"
            out_db = tmp / "dry.sqlite"
            review_json = tmp / "review.json"
            out_json = tmp / "out.json"
            out_md = tmp / "out.md"
            self.make_db(master_db)
            review_json.write_text(
                json.dumps(
                    {
                        "review": [
                            {
                                "review_action": "ready_source_url_candidate",
                                "occurrence_id": "occ1",
                                "event_name": "雷門盆踊り（浅草）",
                                "event_year": 2026,
                                "candidate_source_url": "https://x.com/STBA_Bonodori/status/2059220925862883623",
                                "candidate_source_kind": "retrospective_x_evidence",
                                "confidence": "medium",
                                "reason": "test",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = applier.run(
                Namespace(
                    master_db=master_db,
                    review_json=review_json,
                    out_db=out_db,
                    out_json=out_json,
                    out_md=out_md,
                    apply=False,
                    confirm="",
                )
            )

            self.assertEqual(result["summary"]["applied_count"], 1)
            with sqlite3.connect(master_db) as conn:
                original = conn.execute("SELECT source_url FROM event_occurrences").fetchone()[0]
            with sqlite3.connect(out_db) as conn:
                copied = conn.execute(
                    "SELECT source_kind, source_url FROM event_occurrences"
                ).fetchone()
            self.assertEqual(original, "")
            self.assertEqual(copied[0], "notion_events")
            self.assertEqual(copied[1], "https://x.com/STBA_Bonodori/status/2059220925862883623")


if __name__ == "__main__":
    unittest.main()
