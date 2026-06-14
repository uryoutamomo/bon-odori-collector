import unittest

from collect import VOICE_TEXT_MAX_CHARS, _parse_voice_entry


class CollectVoicesTest(unittest.TestCase):
    def test_voice_text_keeps_youtube_setlist_beyond_old_500_char_limit(self):
        long_setlist = "\n".join(f"{i} 東京音頭{i}" for i in range(1, 180))
        entry = {
            "title": "東京音頭 飛鳥山公園輪踊り 2026年5月24日 東京都北区 #盆踊り",
            "link": "https://www.youtube.com/watch?v=main",
            "summary": long_setlist,
        }
        feed_meta = {
            "source": "youtube",
            "account": "@wadaikoCH",
            "name": "和太鼓お祭りCH",
        }

        voice = _parse_voice_entry(entry, feed_meta)

        self.assertGreater(len(voice["text"]), 500)
        self.assertLessEqual(len(voice["text"]), VOICE_TEXT_MAX_CHARS)

    def test_voice_media_urls_include_urls_from_html_description(self):
        entry = {
            "title": "荒川音頭 飛鳥山公園輪踊り 2026年5月24日 東京都北区 #盆踊り",
            "link": "https://www.youtube.com/watch?v=main",
            "summary": (
                '1 東京音頭 <a href="https://youtu.be/aaa111">https://youtu.be/aaa111</a>\n'
                '2 荒川音頭 <a href="https://www.youtube.com/watch?v=bbb222">動画</a>'
            ),
        }
        feed_meta = {
            "source": "youtube",
            "account": "@wadaikoCH",
            "name": "和太鼓お祭りCH",
        }

        voice = _parse_voice_entry(entry, feed_meta)

        self.assertIn("https://youtu.be/aaa111", voice["media_urls"])
        self.assertIn("https://www.youtube.com/watch?v=bbb222", voice["media_urls"])


if __name__ == "__main__":
    unittest.main()
