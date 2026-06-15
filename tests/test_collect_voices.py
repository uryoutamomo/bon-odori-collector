import json
import os
import tempfile
import unittest

from collect import VOICE_TEXT_MAX_CHARS, _load_active_youtube_registry_feeds, _parse_voice_entry, _voice_feeds


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

    def test_voice_entry_keeps_youtube_channel_id_from_feed_meta(self):
        entry = {
            "title": "盆踊り",
            "link": "https://www.youtube.com/watch?v=main",
            "summary": "東京音頭",
        }
        feed_meta = {
            "source": "youtube",
            "account": "UC123",
            "name": "Tokyo Walk",
            "channel_id": "UC123",
        }

        voice = _parse_voice_entry(entry, feed_meta)

        self.assertEqual(voice["youtube_channel_id"], "UC123")
        self.assertEqual(voice["youtube_channel_title"], "Tokyo Walk")

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

    def test_load_active_youtube_registry_feeds_filters_watch_and_hold(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "registry.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "channels": [
                            {
                                "channel_id": "UC_ACTIVE",
                                "channel_title": "Active Channel",
                                "rss_url": "https://www.youtube.com/feeds/videos.xml?channel_id=UC_ACTIVE",
                                "status": "active",
                                "collection_enabled": True,
                            },
                            {
                                "channel_id": "UC_WATCH",
                                "channel_title": "Watch Channel",
                                "rss_url": "https://www.youtube.com/feeds/videos.xml?channel_id=UC_WATCH",
                                "status": "watch",
                                "collection_enabled": False,
                            },
                        ]
                    },
                    f,
                )

            feeds = _load_active_youtube_registry_feeds(path)

        self.assertEqual(len(feeds), 1)
        self.assertEqual(feeds[0]["name"], "Active Channel")
        self.assertEqual(feeds[0]["account"], "UC_ACTIVE")

    def test_voice_feeds_deduplicates_static_youtube_rss(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "registry.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "channels": [
                            {
                                "channel_id": "UCNF_5e3ZvziJueTWvTPATGw",
                                "channel_title": "和太鼓お祭りチャンネル",
                                "rss_url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCNF_5e3ZvziJueTWvTPATGw",
                                "status": "active",
                                "collection_enabled": True,
                            },
                            {
                                "channel_id": "UC_NEW",
                                "channel_title": "New Active",
                                "rss_url": "https://www.youtube.com/feeds/videos.xml?channel_id=UC_NEW",
                                "status": "active",
                                "collection_enabled": True,
                            },
                        ]
                    },
                    f,
                )

            feeds = _voice_feeds(path)

        rss_urls = [feed["rss_url"] for feed in feeds]
        self.assertEqual(
            rss_urls.count("https://www.youtube.com/feeds/videos.xml?channel_id=UCNF_5e3ZvziJueTWvTPATGw"),
            1,
        )
        self.assertIn("https://www.youtube.com/feeds/videos.xml?channel_id=UC_NEW", rss_urls)


if __name__ == "__main__":
    unittest.main()
