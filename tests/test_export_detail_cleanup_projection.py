import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ExportDetailCleanupProjectionCliTest(unittest.TestCase):
    def test_direct_script_execution_resolves_repo_root_import(self):
        result = subprocess.run(
            [sys.executable, "scripts/export_detail_cleanup_projection.py", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--source-map-out", result.stdout)


if __name__ == "__main__":
    unittest.main()
