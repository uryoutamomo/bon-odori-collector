import unittest

from discover_youtube_channels import (
    build_candidates,
    enrich_video_candidate,
    event_name_is_noise,
    extract_chapter_setlist,
    filter_numbered_setlist,
    known_channel_ids,
)


class DiscoverYoutubeChannelsTest(unittest.TestCase):
    def test_enriches_video_with_event_and_setlist(self):
        video = {
            "video_id": "abc",
            "url": "https://www.youtube.com/watch?v=abc",
            "title": "納涼盆踊り 2025年8月1日",
            "description": "中央公園で開催\n1 東京音頭 https://youtu.be/song1\n2 炭坑節 https://youtu.be/song2",
            "channel_id": "UCabc",
            "channel_title": "盆踊り記録",
            "published_at": "2025-08-02T00:00:00Z",
        }
        row = enrich_video_candidate(video)
        self.assertEqual(row["event_date"], "2025-08-01")
        self.assertEqual(row["setlist_count"], 2)
        self.assertTrue(row["bon_context"])

    def test_scores_known_and_unknown_channels(self):
        videos = [
            enrich_video_candidate({
                "video_id": "abc",
                "url": "https://www.youtube.com/watch?v=abc",
                "title": "納涼盆踊り 2025年8月1日",
                "description": "1 東京音頭 https://youtu.be/song1\n2 炭坑節 https://youtu.be/song2",
                "channel_id": "UCabc",
                "channel_title": "盆踊り記録",
                "published_at": "2025-08-02T00:00:00Z",
            })
        ]
        channels, events = build_candidates(videos, {"UCknown"})
        self.assertEqual(channels[0]["channel_id"], "UCabc")
        self.assertFalse(channels[0]["already_known"])
        self.assertGreater(channels[0]["candidate_score"], 0)
        self.assertEqual(len(events), 1)

    def test_reads_known_channel_ids(self):
        self.assertEqual(
            known_channel_ids({"channels": [{"channel_id": "UC1"}, {"channel_id": ""}]}),
            {"UC1"},
        )

    def test_detects_description_noise_as_event_name(self):
        self.assertTrue(event_name_is_noise("※カメラの熱暴走により一部停止"))
        self.assertFalse(event_name_is_noise("山王音頭と民踊大会"))

    def test_extracts_chapter_setlist_without_related_video_noise(self):
        rows = extract_chapter_setlist(
            "\n".join([
                "00:00 ハイライト",
                "02:27 日本晴れ晴れ音頭",
                "07:25 炭坑節",
                "【4K】 関連動画",
                "https://youtu.be/example",
            ])
        )
        self.assertEqual([row["title"] for row in rows], ["日本晴れ晴れ音頭", "炭坑節"])

    def test_filters_numbered_related_video_noise(self):
        rows = filter_numbered_setlist([
            {"number": 20, "title": "25】", "url": "https://www.youtube.com/watch?v=x"},
            {"number": 1, "title": "東京音頭", "url": "https://www.youtube.com/watch?v=y"},
        ])
        self.assertEqual([row["title"] for row in rows], ["東京音頭"])


if __name__ == "__main__":
    unittest.main()
