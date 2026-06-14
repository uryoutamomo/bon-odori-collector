import unittest

from build_youtube_channels import build_channels


class BuildYoutubeChannelsTest(unittest.TestCase):
    def test_groups_by_channel_id_and_scores_setlist_sources(self):
        voices = [
            {
                "source": "youtube",
                "account": "@wadaikoCH",
                "name": "和太鼓お祭りCH",
                "url": "https://www.youtube.com/watch?v=aaa",
                "title": "東京音頭 盆踊り",
                "text": "盆踊りの説明です。1 東京音頭 https://youtu.be/song1",
                "media_urls": ["https://youtu.be/song1"],
                "youtube_channel_id": "UCaaa",
                "youtube_channel_title": "和太鼓お祭りチャンネル",
                "youtube_published_at": "2026-06-13T10:00:00Z",
                "thumbnail_url": "https://img.youtube.com/aaa.jpg",
            },
            {
                "source": "youtube",
                "account": "@wadaikoCH",
                "name": "和太鼓お祭りCH",
                "url": "https://www.youtube.com/watch?v=bbb",
                "title": "炭坑節 盆踊り",
                "text": "盆踊りの説明です。2 炭坑節 https://youtu.be/song2",
                "media_urls": ["https://youtu.be/song2"],
                "youtube_channel_id": "UCaaa",
                "youtube_channel_title": "和太鼓お祭りチャンネル",
                "youtube_published_at": "2026-06-14T10:00:00Z",
                "thumbnail_url": "https://img.youtube.com/bbb.jpg",
            },
        ]
        setlists = {
            "occurrences": [
                {
                    "occurrence_key": "event1",
                    "accounts": ["@wadaikoCH"],
                    "event_name_hint": "山王音頭と民踊大会",
                    "venue": "赤坂日枝神社",
                    "event_date": "2026-06-13",
                    "song_count": 15,
                    "confidence": "high",
                }
            ]
        }
        rows = build_channels(voices, setlists)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["channel_id"], "UCaaa")
        self.assertEqual(row["channel_url"], "https://www.youtube.com/channel/UCaaa")
        self.assertEqual(row["accounts"], ["@wadaikoCH"])
        self.assertEqual(row["video_count"], 2)
        self.assertEqual(row["setlist_occurrence_count"], 1)
        self.assertEqual(row["setlist_song_count"], 15)
        self.assertEqual(row["venue_date_success_count"], 1)
        self.assertEqual(row["representative_thumbnail_url"], "https://img.youtube.com/bbb.jpg")
        self.assertGreater(row["auto_score"], 0)
        self.assertEqual(row["events"][0]["event_name"], "山王音頭と民踊大会")

    def test_falls_back_to_account_when_channel_id_is_missing(self):
        rows = build_channels(
            [
                {
                    "source": "youtube",
                    "account": "@legacy",
                    "name": "旧フィード",
                    "url": "https://youtu.be/abc",
                    "title": "盆踊り",
                    "text": "盆踊り",
                }
            ],
            {"occurrences": []},
        )
        self.assertEqual(rows[0]["channel_key"], "@legacy")
        self.assertEqual(rows[0]["channel_id"], "")
        self.assertEqual(rows[0]["channel_title"], "旧フィード")


if __name__ == "__main__":
    unittest.main()
