import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "legacy" / "notion-notes" / "append_youtube_task_list_to_notion.py"
SPEC = importlib.util.spec_from_file_location("append_youtube_task_list_to_notion", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
task_blocks = MODULE.task_blocks


class AppendYoutubeTaskListToNotionTest(unittest.TestCase):
    def test_task_blocks_include_policy_and_tasks(self):
        blocks = task_blocks()
        text = str(blocks)
        self.assertIn("YouTube", text)
        self.assertIn("既存イベント追記候補", text)
        self.assertIn("サムネイル", text)
        self.assertTrue(any(block["type"] == "to_do" for block in blocks))


if __name__ == "__main__":
    unittest.main()
