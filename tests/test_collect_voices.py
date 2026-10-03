import json
import os
import tempfile
import unittest
from unittest.mock import patch

import collect
from collect import VOICE_TEXT_MAX_CHARS, _load_active_youtube_registry_feeds, _parse_voice_entry, _voice_feeds


class CollectVoicesTest(unittest.TestCase):
    def test_partial_rss_failure_does_not_advance_seen_or_return_partial_items(self):
        feeds = [
            {"name": "good", "rss_url": "https://good.test", "source": "youtube", "account": "a"},
            {"name": "bad", "rss_url": "https://bad.test", "source": "youtube", "account": "b"},
        ]
        entry = {"title": "new", "link": "https://youtube.test/new", "summary": "text"}
        good = type("Feed", (), {"bozo": False, "entries": [entry]})()
        parser = type("Parser", (), {"parse": staticmethod(lambda _url: None)})()
        with (
            patch.object(collect, "_HAS_FEEDPARSER", True),
            patch.object(collect, "_voice_feeds", return_value=feeds),
            patch.object(collect, "feedparser", parser, create=True),
            patch.object(parser, "parse", side_effect=[good, OSError("down")]),
        ):
            result = collect.collect_voices_outcome({"https://old.test"})
        self.assertEqual(result.state, "failed")
        self.assertEqual(result.items, [])
        self.assertEqual(result.seen_urls, ["https://old.test"])

    def test_missing_parser_is_explicit_skip(self):
        with patch.object(collect, "_HAS_FEEDPARSER", False):
            result = collect.collect_voices_outcome({"https://old.test"})
        self.assertEqual(result.state, "skipped")
        self.assertEqual(result.seen_urls, ["https://old.test"])

    def test_compatibility_collector_does_not_turn_failure_into_empty_result(self):
        with patch.object(collect, "collect_voices_outcome", return_value=collect.VoiceCollectionResult(
            "failed", failures=["rss:test:bozo"]
        )):
            with self.assertRaises(collect.VoiceCollectionError):
                collect.collect_voices(set())
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
