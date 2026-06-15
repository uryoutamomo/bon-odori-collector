import unittest

from add_current_work_to_first_look_notion import first_look_insert_after_id, first_look_link_block


class AddCurrentWorkToFirstLookNotionTest(unittest.TestCase):
    def test_link_block_contains_current_work_text_and_url(self):
        block = first_look_link_block("https://example.com/current")
        text = block["bulleted_list_item"]["rich_text"][0]["text"]
        self.assertEqual("今やっていること", text["content"])
        self.assertEqual("https://example.com/current", text["link"]["url"])

    def test_find_insert_position_inside_first_look_section(self):
        blocks = [
            {"id": "a", "type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "よく見るデータ"}]}},
            {"id": "b", "type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "まず見る"}]}},
            {"id": "c", "type": "callout", "callout": {}},
            {
                "id": "d",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"plain_text": "今後の対応を見る"}]},
            },
            {"id": "e", "type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "関連ページ"}]}},
        ]
        self.assertEqual("d", first_look_insert_after_id(blocks))

    def test_existing_current_work_link_skips_insert(self):
        blocks = [
            {"id": "b", "type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "まず見る"}]}},
            {
                "id": "c",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"plain_text": "今やっていること"}]},
            },
        ]
        self.assertIsNone(first_look_insert_after_id(blocks))


if __name__ == "__main__":
    unittest.main()
