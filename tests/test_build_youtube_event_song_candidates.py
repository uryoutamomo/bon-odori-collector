import unittest

from build_youtube_event_song_candidates import build_output


class BuildYoutubeEventSongCandidatesTest(unittest.TestCase):
    def test_builds_event_song_links_with_video_evidence(self):
        output = build_output({
            "event_candidates": [
                {
                    "url": "https://www.youtube.com/watch?v=abc",
                    "title": "山王音頭と民踊大会",
                    "channel_id": "UCabc",
                    "channel_title": "盆踊り記録",
                    "thumbnail_url": "https://img.youtube.com/abc.jpg",
                    "description_excerpt": "説明文抜粋",
                    "event_date": "2025-06-13",
                    "event_name_hint": "山王音頭と民踊大会",
                    "venue_hint": "赤坂日枝神社",
                    "setlist_sample": [
                        {"number": 1, "title": "東京音頭", "url": "https://youtu.be/song1"},
                        {"number": 2, "title": "炭坑節", "url": "https://youtu.be/song2"},
                    ],
                }
            ]
        })
        self.assertEqual(output["event_count"], 1)
        self.assertEqual(output["event_song_candidate_count"], 2)
        self.assertEqual(output["events"][0]["song_count"], 2)
        self.assertEqual(output["rows"][0]["source_video_url"], "https://www.youtube.com/watch?v=abc")
        self.assertEqual(output["rows"][0]["thumbnail_url"], "https://img.youtube.com/abc.jpg")
        self.assertEqual(output["events"][0]["description_excerpt"], "説明文抜粋")


if __name__ == "__main__":
    unittest.main()
