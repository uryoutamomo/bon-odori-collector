import unittest

from apply_song_ocr_review import append_review
from build_song_ocr_queue import build
from collect import _x_map_to_voice


class SongOcrPipelineTest(unittest.TestCase):
    def test_x_map_to_voice_preserves_media_urls(self):
        voice = _x_map_to_voice({
            "id": "123",
            "text": "曲目リストです！ #盆踊り",
            "author": {"userName": "tester", "name": "Tester"},
            "extendedEntities": {
                "media": [
                    {"media_url_https": "https://pbs.twimg.com/media/example.jpg"},
                ],
            },
        })
        self.assertEqual(voice["media_urls"], ["https://pbs.twimg.com/media/example.jpg"])

    def test_x_map_to_voice_preserves_author_description(self):
        voice = _x_map_to_voice({
            "id": "description", "text": "盆踊り",
            "author": {"userName": "profile", "name": "Profile", "description": "盆オドラーです"},
        })
        self.assertEqual(voice["profile_description"], "盆オドラーです")

    def test_build_queues_setlist_posts_with_media(self):
        output = build([
            {
                "source": "x",
                "text": "山王音頭と民踊大会 曲目リストです！ #盆踊り",
                "url": "https://x.com/test/status/1",
                "media_urls": ["https://pbs.twimg.com/media/example.jpg"],
            },
            {
                "source": "x",
                "text": "ただの感想です",
                "url": "https://x.com/test/status/2",
            },
        ])
        self.assertEqual(output["count"], 1)
        self.assertEqual(output["items"][0]["status"], "needs_ocr")

    def test_append_review_adds_approved_ocr_result(self):
        manual = {"version": 1, "evidence": []}
        review = {
            "items": [
                {
                    "status": "approved",
                    "event_name": "山王音頭と民踊大会",
                    "venue": "山王パークタワー公開空地",
                    "event_date": "2026-06-13",
                    "url": "https://x.com/test/status/1",
                    "account": "@tester",
                    "reliability": 0.8,
                    "songs": ["東京音頭", "炭坑節", "山王音頭"],
                }
            ]
        }
        result = append_review(review, manual)
        self.assertEqual(len(result["appended"]), 1)
        self.assertEqual(manual["evidence"][0]["songs"], ["東京音頭", "炭坑節", "山王音頭"])


if __name__ == "__main__":
    unittest.main()
