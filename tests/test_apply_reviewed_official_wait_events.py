import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import apply_reviewed_official_wait_events as applier
from master_rdb.master_db import init_db


class ApplyReviewedOfficialWaitEventsTest(unittest.TestCase):
    def test_main_closes_its_connection_in_dry_run_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            master_db = tmp / "master.sqlite"
            conn = init_db(master_db)
            conn.commit()
            conn.close()

            opened_connections = []
            real_connect = sqlite3.connect

            def _tracking_connect(*args, **kwargs):
                conn = real_connect(*args, **kwargs)
                opened_connections.append(conn)
                return conn

            with (
                patch.object(applier, "OUT_DB", tmp / "dry_run.sqlite"),
                patch.object(applier, "OUT_JSON", tmp / "report.json"),
                patch.object(applier, "OUT_MD", tmp / "report.md"),
                patch.object(applier, "BACKUP_DIR", tmp / "backups"),
                patch.object(applier.sqlite3, "connect", side_effect=_tracking_connect),
                patch.object(sys, "argv", ["apply_reviewed_official_wait_events.py", "--master-db", str(master_db)]),
            ):
                applier.main()

        self.assertTrue(opened_connections)
        for conn in opened_connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
