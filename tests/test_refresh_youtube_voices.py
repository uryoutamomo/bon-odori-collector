import json
import os
import tempfile
import unittest
from unittest import mock

import refresh_youtube_voices


class RefreshYoutubeVoicesTest(unittest.TestCase):
    def test_refresh_updates_existing_youtube_voice_and_adds_new_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "voices.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    [
                        {
                            "source": "youtube",
                            "url": "https://www.youtube.com/watch?v=old",
                            "text": "x" * 500,
                        },
                        {
                            "source": "x",
                            "url": "https://x.com/example/status/1",
                            "text": "keep",
                        },
                    ],
                    f,
                    ensure_ascii=False,
                )

            fresh = [
                {
                    "source": "youtube",
                    "url": "https://www.youtube.com/watch?v=old",
                    "text": "y" * 800,
                    "media_urls": ["https://youtu.be/old"],
                },
                {
                    "source": "youtube",
                    "url": "https://www.youtube.com/watch?v=new",
                    "text": "new",
                },
            ]
            with mock.patch.object(refresh_youtube_voices.collect, "collect_voices", return_value=(fresh, [])):
                result = refresh_youtube_voices.refresh_youtube_voices(path)

            with open(path, "r", encoding="utf-8") as f:
                voices = json.load(f)

            self.assertEqual(result["fetched_youtube"], 2)
            self.assertEqual(result["updated_existing"], 1)
            self.assertEqual(result["added_new"], 1)
            self.assertEqual(voices[0]["url"], "https://www.youtube.com/watch?v=new")
            self.assertEqual(len(voices[1]["text"]), 800)
            self.assertEqual(voices[2]["text"], "keep")


if __name__ == "__main__":
    unittest.main()
