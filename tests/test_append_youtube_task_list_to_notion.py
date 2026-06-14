import unittest

from append_youtube_task_list_to_notion import task_blocks


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
