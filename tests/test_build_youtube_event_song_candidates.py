import unittest
from unittest.mock import patch

from build_youtube_event_song_candidates import build_output, extract_chapter_songs


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

    def test_extracts_pop_song_chapters_from_full_description(self):
        description = "\n".join([
            "0:00 OP",
            "0:13 TM NETWORK - Get Wild【途中切れ】",
            "2:25 ROSÉ & Bruno Mars - APT. 【途中から】",
            "39:37 荻野目洋子 - ダンシング・ヒーロー / Yoko Oginome - Eat You Up",
            "1:07:04 提灯 / lantern",
            "1:07:17 END",
        ])

        rows = extract_chapter_songs(description)

        self.assertEqual([row["title"] for row in rows], [
            "TM NETWORK - Get Wild",
            "ROSÉ & Bruno Mars - APT.",
            "荻野目洋子 - ダンシング・ヒーロー / Yoko Oginome - Eat You Up",
        ])

    def test_build_output_enriches_short_setlist_from_channel_candidate_description(self):
        payload = {
            "event_candidates": [
                {
                    "url": "https://www.youtube.com/watch?v=abc",
                    "title": "歌舞伎町BON ODORI",
                    "channel_id": "UCabc",
                    "channel_title": "Tokyo Lonely Walker",
                    "thumbnail_url": "https://img.youtube.com/abc.jpg",
                    "description_excerpt": "説明文抜粋",
                    "event_date": "2025-08-16",
                    "event_name_hint": "歌舞伎町BON ODORI",
                    "venue_hint": "歌舞伎町シネシティ広場",
                    "setlist_sample": [
                        {"number": 1, "title": "ダンシング・ヒーロー", "url": "", "source": "chapter"},
                    ],
                }
            ]
        }
        channel_payload = {
            "channels": [
                {
                    "sample_videos": [
                        {
                            "url": "https://www.youtube.com/watch?v=abc",
                            "description": "0:13 Get Wild\n2:25 APT.\n39:37 ダンシング・ヒーロー",
                        }
                    ]
                }
            ]
        }

        with patch("build_youtube_event_song_candidates.load_json", return_value=channel_payload):
            output = build_output(payload)

        self.assertEqual(output["events"][0]["song_count"], 3)

    def test_fills_english_event_date_from_full_channel_description(self):
        payload = {
            "event_candidates": [
                {
                    "url": "https://www.youtube.com/watch?v=oku",
                    "title": "Oku-Asakusa Bon Odori 2025",
                    "event_name_hint": "Oku-Asakusa Bon Odori 2025",
                    "venue_hint": "Taito-ku",
                    "event_date": "",
                    "setlist_sample": [],
                }
            ]
        }
        channel_payload = {
            "channels": [
                {
                    "sample_videos": [
                        {
                            "url": "https://www.youtube.com/watch?v=oku",
                            "description": "\n".join([
                                "Oku-Asakusa Bon Odori on Saturday night, June 28th, 2025.",
                                "05:54 - Oku-Asakusa Bon Odori Festival 2025",
                                "06:35 - Furusato Ondo",
                                "11:10 - Omedeta Ondo",
                            ]),
                        }
                    ]
                }
            ]
        }

        with patch("build_youtube_event_song_candidates.load_json", return_value=channel_payload):
            output = build_output(payload)

        self.assertEqual(output["events"][0]["event_date"], "2025-06-28")
        self.assertEqual(
            sorted(song["title"] for song in output["events"][0]["songs"]),
            ["Furusato Ondo", "Omedeta Ondo"],
        )


if __name__ == "__main__":
    unittest.main()
