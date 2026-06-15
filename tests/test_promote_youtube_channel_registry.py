import unittest

from promote_youtube_channel_registry import build_registry


class PromoteYoutubeChannelRegistryTest(unittest.TestCase):
    def test_promotes_high_adopt_to_active(self):
        registry = build_registry(
            {
                "generated_at": "2026-06-15T00:00:00+00:00",
                "rows": [
                    {
                        "channel_id": "UC123",
                        "channel_title": "Tokyo Lonely Walker",
                        "channel_url": "https://www.youtube.com/channel/UC123",
                        "decision": "adopt",
                        "priority": "high",
                        "review_reason": "東京圏。曜日誤記があるため日付検証と併用。",
                        "next_action": "東京圏の2025実績発掘に使う。",
                        "candidate_score": 90,
                        "bon_context_video_count": 4,
                        "event_date_candidate_count": 4,
                        "setlist_candidate_count": 1,
                    }
                ],
            },
            {"channels": []},
            generated_at="2026-06-15T01:00:00+00:00",
        )

        row = registry["channels"][0]
        self.assertEqual(row["status"], "active")
        self.assertTrue(row["collection_enabled"])
        self.assertEqual(
            row["rss_url"],
            "https://www.youtube.com/feeds/videos.xml?channel_id=UC123",
        )
        self.assertTrue(row["date_validation_required"])
        self.assertIn("setlist_extraction", row["trusted_for"])

    def test_promotes_normal_adopt_to_active_after_approval(self):
        registry = build_registry(
            {
                "rows": [
                    {
                        "channel_id": "UC456",
                        "channel_title": "Exploring Japan with Zen",
                        "channel_url": "https://www.youtube.com/channel/UC456",
                        "decision": "adopt",
                        "priority": "normal",
                        "review_reason": "公式URL候補を説明欄に記載。",
                        "next_action": "公式URL探索補助として使う。YouTube単独では本登録しない。",
                        "candidate_score": 40,
                    }
                ],
            },
            {"channels": []},
            generated_at="2026-06-15T01:00:00+00:00",
        )

        row = registry["channels"][0]
        self.assertEqual(row["status"], "active")
        self.assertTrue(row["collection_enabled"])
        self.assertIn("official_url_discovery", row["trusted_for"])

    def test_merges_existing_channel_analytics(self):
        registry = build_registry(
            {
                "rows": [
                    {
                        "channel_id": "UC999",
                        "channel_title": "祭のきせき　盆踊り",
                        "channel_url": "https://www.youtube.com/channel/UC999",
                        "already_known": True,
                        "decision": "already_registered",
                        "priority": "high",
                        "review_reason": "既存YouTubeチャンネルDBに登録済み。",
                        "next_action": "維持する。",
                        "candidate_score": 86,
                    }
                ],
            },
            {
                "channels": [
                    {
                        "channel_id": "UC999",
                        "video_count": 66,
                        "bon_odori_video_count": 64,
                        "last_published_at": "2026-06-06T05:00:36Z",
                    }
                ]
            },
            generated_at="2026-06-15T01:00:00+00:00",
        )

        row = registry["channels"][0]
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["source"], "existing_voices")
        self.assertEqual(row["metrics"]["analytics"]["video_count"], 66)
        self.assertEqual(row["last_collected_at"], "2026-06-06T05:00:36Z")


if __name__ == "__main__":
    unittest.main()
