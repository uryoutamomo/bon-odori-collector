import unittest

from youtube_channels.backfill_youtube_descriptions import apply_snippets, plan_backfill, video_id_from_url


class YoutubeDescriptionBackfillTest(unittest.TestCase):
    def test_extracts_video_id_from_youtube_urls(self):
        self.assertEqual(video_id_from_url("https://youtu.be/abc123?si=x"), "abc123")
        self.assertEqual(video_id_from_url("https://www.youtube.com/watch?v=def456&t=1"), "def456")

    def test_plans_unique_youtube_videos(self):
        voices = [
            {"source": "youtube", "url": "https://youtu.be/abc123", "text": "short"},
            {"source": "youtube", "url": "https://www.youtube.com/watch?v=abc123", "text": "short"},
            {"source": "x", "url": "https://youtu.be/ignored", "text": "short"},
        ]
        plan = plan_backfill(voices)
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["video_id"], "abc123")

    def test_applies_description_without_touching_non_youtube(self):
        voices = [
            {"source": "youtube", "url": "https://youtu.be/abc123", "text": "short"},
            {"source": "x", "url": "https://x.com/example", "text": "unchanged"},
        ]
        result = apply_snippets(
            voices,
            {
                "abc123": {
                    "title": "Video title",
                    "description": "full description https://youtu.be/song1",
                    "channelId": "UCabc",
                    "channelTitle": "盆踊りチャンネル",
                    "publishedAt": "2026-06-01T00:00:00Z",
                    "thumbnails": {"high": {"url": "https://img.youtube.com/high.jpg"}},
                }
            },
        )
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["expanded"], 1)
        self.assertEqual(result["media_updated"], 1)
        self.assertEqual(result["metadata_updated"], 1)
        self.assertEqual(voices[0]["text"], "full description https://youtu.be/song1")
        self.assertEqual(voices[0]["media_urls"], ["https://youtu.be/song1"])
        self.assertEqual(voices[0]["youtube_channel_id"], "UCabc")
        self.assertEqual(voices[0]["youtube_channel_title"], "盆踊りチャンネル")
        self.assertEqual(voices[0]["thumbnail_url"], "https://img.youtube.com/high.jpg")
        self.assertEqual(voices[1]["text"], "unchanged")


if __name__ == "__main__":
    unittest.main()
