import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from report_apply import apply_detail_cleanup_repair as repair


class ApplyDetailCleanupRepairTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.master = root / "master.sqlite"
        self.out_db = root / "preview.sqlite"
        self.out_json = root / "result.json"
        self.out_md = root / "result.md"
        self.ids = [f"occ_{index:02}" for index in range(14)]
        with closing(sqlite3.connect(self.master)) as conn:
            conn.executescript("""
                CREATE TABLE event_occurrences(
                    occurrence_id TEXT PRIMARY KEY, detail TEXT, updated_at TEXT, source_url TEXT
                );
                CREATE TABLE unrelated(id TEXT PRIMARY KEY, value TEXT);
            """)
            for occurrence_id in self.ids:
                conn.execute("INSERT INTO event_occurrences VALUES (?, ?, ?, ?)", (occurrence_id, f"old {occurrence_id}", "old", "source"))
            conn.execute("INSERT INTO unrelated VALUES ('only', 'unchanged')")
            conn.commit()
        report = {
            "report_type": "detail_cleanup_repair",
            "events": [{"occurrence_id": occurrence_id, "action": "confirm_existing", "detail_replacement": f"new {occurrence_id}"} for occurrence_id in self.ids],
            "expected_current_detail_sha256": {occurrence_id: repair.digest(f"old {occurrence_id}") for occurrence_id in self.ids},
        }
        report["report_sha256"] = repair.report_digest(report)
        self.report = root / "report.json"
        self.report.write_text(json.dumps(report), encoding="utf-8")

    def args(self, *, apply=False, confirm=""):
        return SimpleNamespace(report=self.report, master_db=self.master, out_db=self.out_db, out_json=self.out_json, out_md=self.out_md, apply=apply, confirm=confirm)

    @patch("report_apply.apply_detail_cleanup_repair.table_counts", return_value={"event_occurrences": 14, "unrelated": 1})
    @patch("report_apply.apply_detail_cleanup_repair.audit_db", return_value={"issue_count": 0})
    def test_dry_run_changes_only_detail_and_timestamp(self, _audit, _counts):
        result = repair.run(self.args())
        self.assertEqual(result["mode"], "dry_run")
        with closing(sqlite3.connect(self.master)) as conn:
            self.assertEqual(conn.execute("SELECT detail FROM event_occurrences WHERE occurrence_id = 'occ_00'").fetchone()[0], "old occ_00")
        with closing(sqlite3.connect(self.out_db)) as conn:
            self.assertEqual(conn.execute("SELECT detail FROM event_occurrences WHERE occurrence_id = 'occ_00'").fetchone()[0], "new occ_00")
            self.assertEqual(conn.execute("SELECT value FROM unrelated WHERE id = 'only'").fetchone()[0], "unchanged")

    def test_one_hash_mismatch_updates_nothing(self):
        report = json.loads(self.report.read_text(encoding="utf-8"))
        report["expected_current_detail_sha256"]["occ_07"] = "0" * 64
        report["report_sha256"] = repair.report_digest(report)
        with closing(sqlite3.connect(self.master)) as conn:
            with self.assertRaisesRegex(ValueError, "precondition mismatch"):
                repair.apply(conn, report, "new-time")
            self.assertEqual(conn.execute("SELECT detail FROM event_occurrences WHERE occurrence_id = 'occ_00'").fetchone()[0], "old occ_00")
            self.assertEqual(conn.execute("SELECT detail FROM event_occurrences WHERE occurrence_id = 'occ_13'").fetchone()[0], "old occ_13")

    def test_wrong_confirmation_does_not_touch_master(self):
        with self.assertRaisesRegex(ValueError, "--confirm"):
            repair.run(self.args(apply=True, confirm="wrong"))
        with closing(sqlite3.connect(self.master)) as conn:
            self.assertEqual(conn.execute("SELECT detail FROM event_occurrences WHERE occurrence_id = 'occ_00'").fetchone()[0], "old occ_00")


if __name__ == "__main__":
    unittest.main()
