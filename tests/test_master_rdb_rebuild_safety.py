import tempfile
import unittest
from pathlib import Path

from master_db import init_db


class MasterRdbRebuildSafetyTest(unittest.TestCase):
    def test_existing_db_requires_explicit_force_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "master.sqlite"
            path.write_text("existing", encoding="utf-8")

            with self.assertRaises(SystemExit):
                init_db(path)

    def test_force_rebuild_replaces_existing_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "master.sqlite"
            path.write_text("existing", encoding="utf-8")

            conn = init_db(path, force_rebuild_from_snapshot=True)
            try:
                row = conn.execute("SELECT name FROM sqlite_master WHERE name = 'schema_migrations'").fetchone()
                self.assertIsNotNone(row)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
