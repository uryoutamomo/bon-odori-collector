import unittest

from plan_youtube_event_updates import build_plan, clean_song_title


class PlanYoutubeEventUpdatesTest(unittest.TestCase):
    def test_matches_existing_public_event_and_cleans_songs(self):
        youtube = {
            "events": [
                {
                    "event_key": "yt1",
                    "event_name": "歌舞伎町 BON ODORI 2025",
                    "venue": "歌舞伎町 シネシティ広場",
                    "event_date": "2025-09-16",
                    "source_video_url": "https://www.youtube.com/watch?v=abc",
                    "source_video_title": "歌舞伎町 BON ODORI 2025",
                    "songs": [
                        {"title": "荻野目洋子 - ダンシング・ヒーロー / Yoko Oginome - Eat You Up"}
                    ],
                }
            ]
        }
        public_events = [
            {"name": "盆踊り大会", "venue": "木場二丁目公園", "area": "江東区"},
            {"name": "歌舞伎町BON ODORI", "venue": "歌舞伎町シネシティ広場", "area": "新宿区"}
        ]
        plan = build_plan(youtube, public_events)
        self.assertEqual(plan["rows"][0]["action"], "append_evidence_to_existing_event")
        self.assertEqual(plan["rows"][0]["matched_public_event"]["name"], "歌舞伎町BON ODORI")
        self.assertEqual(plan["rows"][0]["songs"][0]["title"], "ダンシング・ヒーロー")

    def test_corrects_source_date_when_video_published_near_public_event_date(self):
        youtube = {
            "events": [
                {
                    "event_key": "yt1",
                    "event_name": "歌舞伎町 BON ODORI 2025",
                    "venue": "歌舞伎町 シネシティ広場",
                    "event_date": "2025-09-16",
                    "source_published_at": "2025-08-17T08:00:05Z",
                    "source_video_url": "https://www.youtube.com/watch?v=abc",
                    "source_video_title": "歌舞伎町 BON ODORI 2025",
                    "songs": [
                        {"title": "Bon Jovi - Livin' on a Prayer"},
                        {"title": "B'z - ultra soul"},
                        {"title": "TRF - EZ DO DANCE"},
                    ],
                }
            ]
        }
        public_events = [
            {
                "name": "歌舞伎町BON ODORI",
                "venue": "歌舞伎町シネシティ広場",
                "area": "新宿区",
                "date": "2025-08-16",
            }
        ]

        plan = build_plan(youtube, public_events)

        self.assertEqual(plan["rows"][0]["youtube_event_date"], "2025-08-16")
        self.assertEqual(plan["rows"][0]["source_event_date"], "2025-09-16")
        self.assertEqual(plan["rows"][0]["event_date_correction"]["from"], "2025-09-16")

    def test_marks_out_of_scope_candidate(self):
        plan = build_plan(
            {
                "events": [
                    {
                        "event_key": "yt2",
                        "event_name": "はかた夏まつり2025",
                        "venue": "博多駅前",
                        "event_date": "2025-08-17",
                        "source_video_url": "https://www.youtube.com/watch?v=def",
                        "songs": [{"title": "ダンシングヒーロー盆踊り"}],
                    }
                ]
            },
            [],
        )
        self.assertEqual(plan["rows"][0]["action"], "hold_out_of_public_scope")

    def test_clean_song_title(self):
        self.assertEqual(clean_song_title("東京音頭 / Tokyo Ondo"), "東京音頭")
        self.assertEqual(clean_song_title("ダンシングヒーロー盆踊り"), "ダンシングヒーロー")


if __name__ == "__main__":
    unittest.main()
