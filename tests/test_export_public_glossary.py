import unittest

from export_public_glossary import replace_song_glossary_items, song_public_description


class ExportPublicGlossaryTest(unittest.TestCase):
    def test_song_public_description_uses_rank_genre_and_source_count(self):
        description = song_public_description(
            "東京音頭",
            {
                "description": "盆踊り会場の曲目として確認されている曲です。",
                "bon_usage_rank": "定番",
                "song_genre": "音頭",
                "genre_basis": "曲名と利用実績から判断",
                "source_count": 12,
            },
        )

        self.assertIn("定番曲", description)
        self.assertIn("「音頭」系", description)
        self.assertIn("確認根拠は 12 件", description)

    def test_replace_song_glossary_items_preserves_existing_reading(self):
        items = [
            {
                "term": "東京音頭",
                "reading": "とうきょうおんど",
                "category": "曲名",
                "category_label": "曲名・踊り名",
            },
            {
                "term": "櫓",
                "reading": "やぐら",
                "category": "用語",
                "category_label": "用語",
            },
        ]
        songs = [
            {
                "term": "東京音頭",
                "reading": "",
                "category": "曲名",
                "category_label": "曲名・踊り名",
            }
        ]

        merged = replace_song_glossary_items(items, songs)

        self.assertEqual([item["term"] for item in merged], ["櫓", "東京音頭"])
        self.assertEqual(merged[1]["reading"], "とうきょうおんど")


if __name__ == "__main__":
    unittest.main()
