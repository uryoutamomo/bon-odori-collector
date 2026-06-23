import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import audit_master_rdb
from master_db import init_db


class AuditMasterRdbTest(unittest.TestCase):
    def test_missing_notion_snapshot_does_not_create_empty_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db = tmp / "master.sqlite"
            missing_notion = tmp / "missing_notion.sqlite"
            conn = init_db(db)
            conn.close()

            result = audit_master_rdb.audit(
                Namespace(
                    db=db,
                    notion_db=missing_notion,
                    song_occurrences=tmp / "missing_song_occurrences.json",
                    manifest=tmp / "missing_manifest.json",
                    out_json=tmp / "audit.json",
                    out_md=tmp / "audit.md",
                )
            )

            self.assertFalse(missing_notion.exists())
            self.assertNotIn("high", result["issues_by_severity"])
            self.assertIsNone(result["source_counts"]["notion_venues"])


if __name__ == "__main__":
    unittest.main()
