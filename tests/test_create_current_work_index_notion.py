import unittest

from create_current_work_index_notion import page_blocks


class CreateCurrentWorkIndexNotionTest(unittest.TestCase):
    def test_page_blocks_include_active_and_paused_work(self):
        blocks = page_blocks("https://example.com/youtube")
        text = str(blocks)
        self.assertIn("今動いているもの", text)
        self.assertIn("少しだけ休止中", text)
        self.assertIn("YouTubeデータ活用", text)
        self.assertIn("RDB集約", text)


if __name__ == "__main__":
    unittest.main()
