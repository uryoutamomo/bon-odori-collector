import tempfile
import unittest
from pathlib import Path

import guard_git_large_files as guard


class GuardGitLargeFilesTest(unittest.TestCase):
    def test_classifies_warn_and_block_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            warn_file = root / "warn.bin"
            block_file = root / "block.bin"
            small_file = root / "small.bin"
            warn_file.write_bytes(b"0" * 6)
            block_file.write_bytes(b"0" * 10)
            small_file.write_bytes(b"0" * 3)

            rows = guard.classify_files(
                root,
                [Path("warn.bin"), Path("block.bin"), Path("small.bin")],
                warn_bytes=5,
                block_bytes=9,
            )

            self.assertEqual(
                [(row["path"], row["severity"]) for row in rows],
                [("block.bin", "block"), ("warn.bin", "warn")],
            )


if __name__ == "__main__":
    unittest.main()
