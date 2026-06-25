import json
import sqlite3
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

import apply_notion_drift_public_intro as script


class ApplyNotionDriftPublicIntroTest(unittest.TestCase):
    def make_db(self, path):
        with sqlite3.connect(path) as conn:
            conn.executescript(
                """
                CREATE TABLE event_series (
                  series_id TEXT PRIMARY KEY,
                  canonical_name TEXT NOT NULL,
                  public_intro TEXT,
                  updated_at TEXT
                );
                CREATE TABLE notion_sync_jobs (
                  job_id TEXT PRIMARY KEY,
                  requested_by TEXT
                );
                """
            )
            conn.execute(
                "INSERT INTO event_series VALUES (?, ?, ?, ?)",
                ("ser1", "SHIBUYA MIYASHITA PARK BON DANCE", "", "old"),
            )
            conn.commit()

    def make_decisions(self, path):
        payload = {
            "decisions": [
                {
                    "decision_id": "notion_drift_001",
                    "entity_type": "event_series",
                    "entity_id": "ser1",
                    "title": "SHIBUYA MIYASHITA PARK BON DANCE",
                    "field": "public_intro",
                    "notion_snapshot_value": "渋谷・宮下公園の芝生の上で開かれる現代型の盆踊り。",
                    "decision": "candidate_copy_notion_public_intro",
                    "apply_ready": True,
                    "reason": "test",
                }
            ]
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def base_args(self, tmp, apply=False):
        return Namespace(
            master_db=tmp / "master.sqlite",
            decisions=tmp / "decisions.json",
            out_db=tmp / "dry.sqlite",
            out_json=tmp / "out.json",
            out_md=tmp / "out.md",
            apply=apply,
            confirm=script.CONFIRM if apply else "",
        )

    def test_dry_run_writes_only_to_copy(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            self.make_db(tmp / "master.sqlite")
            self.make_decisions(tmp / "decisions.json")

            result = script.run(self.base_args(tmp))

            self.assertFalse(result["applied"])
            self.assertEqual(result["summary"]["applied_count"], 1)
            with sqlite3.connect(tmp / "master.sqlite") as conn:
                original = conn.execute("SELECT public_intro FROM event_series").fetchone()[0]
            with sqlite3.connect(tmp / "dry.sqlite") as conn:
                copied = conn.execute("SELECT public_intro FROM event_series").fetchone()[0]
            self.assertEqual(original, "")
            self.assertEqual(copied, "渋谷・宮下公園の芝生の上で開かれる現代型の盆踊り。")

    def test_apply_is_rdb_only_and_does_not_queue_notion_sync(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            self.make_db(tmp / "master.sqlite")
            self.make_decisions(tmp / "decisions.json")

            with mock.patch.object(script, "BACKUP_DIR", tmp / "backups"):
                with mock.patch.object(script, "refresh_manifest_database_state"):
                    result = script.run(self.base_args(tmp, apply=True))

            self.assertTrue(result["applied"])
            self.assertEqual(result["summary"]["applied_count"], 1)
            with sqlite3.connect(tmp / "master.sqlite") as conn:
                intro = conn.execute("SELECT public_intro FROM event_series").fetchone()[0]
                jobs = conn.execute("SELECT COUNT(*) FROM notion_sync_jobs").fetchone()[0]
            self.assertEqual(intro, "渋谷・宮下公園の芝生の上で開かれる現代型の盆踊り。")
            self.assertEqual(jobs, 0)


if __name__ == "__main__":
    unittest.main()
