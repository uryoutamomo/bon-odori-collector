import unittest

from fetch_youtube_2025_backfill import active_channels, item_to_voice, merge_voices


class FetchYoutube2025BackfillTest(unittest.TestCase):
    def test_active_channels_filters_registry(self):
        registry = {
            "channels": [
                {"channel_id": "a", "status": "active", "collection_enabled": True},
                {"channel_id": "b", "status": "watch", "collection_enabled": True},
                {"channel_id": "c", "status": "active", "collection_enabled": False},
            ]
        }

        self.assertEqual([row["channel_id"] for row in active_channels(registry)], ["a"])
        self.assertEqual([row["channel_id"] for row in active_channels(registry, include_channel_ids=["b"])], [])

    def test_item_to_voice_maps_youtube_metadata(self):
        voice = item_to_voice(
            {
                "snippet": {
                    "title": "盆踊り 2025",
                    "description": "公式 https://example.com",
                    "publishedAt": "2025-08-01T00:00:00Z",
                    "resourceId": {"videoId": "abc123"},
                    "thumbnails": {"default": {"url": "https://i.example/thumb.jpg"}},
                }
            },
            {"channel_id": "chan1", "channel_title": "Test Channel"},
        )

        self.assertEqual(voice["url"], "https://www.youtube.com/watch?v=abc123")
        self.assertEqual(voice["youtube_channel_id"], "chan1")
        self.assertEqual(voice["media_urls"], ["https://example.com"])

    def test_merge_voices_adds_new_and_updates_longer_text(self):
        existing = [
            {
                "source": "youtube",
                "url": "https://www.youtube.com/watch?v=abc123",
                "date": "2025-01-01T00:00:00Z",
                "text": "short",
            }
        ]
        additions = [
            {
                "source": "youtube",
                "url": "https://www.youtube.com/watch?v=abc123",
                "date": "2025-01-01T00:00:00Z",
                "text": "longer description",
            },
            {
                "source": "youtube",
                "url": "https://www.youtube.com/watch?v=def456",
                "date": "2025-02-01T00:00:00Z",
                "text": "new",
            },
        ]

        merged, added, updated = merge_voices(existing, additions)

        self.assertEqual(added, 1)
        self.assertEqual(updated, 1)
        self.assertEqual(len(merged), 2)


if __name__ == "__main__":
    unittest.main()
