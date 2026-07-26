import unittest

from youtube_backfill.plan_youtube_event_updates import build_plan, clean_song_title, match_public_event


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

    def test_holds_new_candidate_when_date_has_review_flags(self):
        plan = build_plan(
            {
                "events": [
                    {
                        "event_key": "yt-shibuya",
                        "event_name": "渋谷盆踊り 2025",
                        "venue": "SHIBUYA109前",
                        "event_date": "2025-08-03",
                        "date_review_flags": [
                            {
                                "type": "weekday_mismatch",
                                "date": "2025-08-03",
                                "claimed_weekday": "Sat",
                                "actual_weekday": "Sun",
                            }
                        ],
                        "source_video_url": "https://www.youtube.com/watch?v=shibuya",
                        "songs": [{"title": "渋谷音頭"}, {"title": "東京音頭"}],
                    }
                ]
            },
            [],
        )

        self.assertEqual(plan["rows"][0]["action"], "needs_research")
        self.assertEqual(plan["rows"][0]["priority"], "高")
        self.assertEqual(plan["rows"][0]["date_review_flags"][0]["type"], "weekday_mismatch")

    def test_matches_oku_asakusa_english_alias_to_existing_event(self):
        youtube = {
            "events": [
                {
                    "event_key": "yt-oku",
                    "event_name": "Oku-Asakusa Bon Odori Festival 2025",
                    "venue": "Taito-ku Tokyo",
                    "event_date": "2025-06-28",
                    "source_video_url": "https://www.youtube.com/watch?v=oku",
                    "songs": [
                        {"title": "Tokyo Ondo"},
                        {"title": "Tanko Bushi"},
                    ],
                }
            ]
        }
        public_events = [
            {
                "name": "奥浅草盆踊り",
                "venue": "隅田公園",
                "area": "台東区",
                "date": "2026-06-27",
            }
        ]

        plan = build_plan(youtube, public_events)

        self.assertEqual(plan["rows"][0]["action"], "append_evidence_to_existing_event")
        self.assertEqual(plan["rows"][0]["matched_public_event"]["name"], "奥浅草盆踊り")

    def test_matches_curated_romanized_aliases_to_current_public_events(self):
        cases = [
            (
                "Jiyugaoka Bon Odori Dance festival / 自由が丘盆踊り 2025",
                "in front of Jiyugaoka Station",
                "自由が丘納涼盆踊り大会",
                "自由が丘駅前ロータリー 特設会場",
                "目黒区",
            ),
            (
                "Marunouchi Bon Odori Dance festival DJ J-POP Time",
                "in front of Tokyo Station",
                "丸の内de盆踊り",
                "行幸通り",
                "千代田区",
            ),
            (
                "Shibuya Bon Odori Dance festival 2025",
                "in front of Shibuya 109",
                "第7回 渋谷盆踊り",
                "渋谷109前",
                "渋谷区",
            ),
            (
                "Kanda Myojin Shrine Bon Dance 2025",
                "Kanda Myojin Shrine",
                "神田明神納涼祭り",
                "神田明神境内",
                "千代田区",
            ),
        ]
        for title, description, event_name, venue, area in cases:
            with self.subTest(event=event_name):
                match = match_public_event(
                    {
                        "event_name": title,
                        "venue": "",
                        "source_video_title": title,
                        "description_excerpt": description,
                    },
                    [{"name": event_name, "venue": venue, "area": area}],
                )
                self.assertEqual(match["name"], event_name)
                self.assertEqual(match["score"], 110)
                self.assertEqual(
                    match["reasons"],
                    ["event_alias_in_youtube", "venue_alias_in_youtube"],
                )

    def test_does_not_match_post_event_street_scene(self):
        match = match_public_event(
            {
                "event_name": "Right after Shibuya Bon Odori",
                "venue": "",
                "source_video_title": (
                    "Right after Shibuya Bon Odori, Shibuya Crossing Is Overflowing with Tourists!"
                ),
            },
            [{"name": "第7回 渋谷盆踊り", "venue": "渋谷109前", "area": "渋谷区"}],
        )

        self.assertIsNone(match)

    def test_clean_song_title(self):
        self.assertEqual(clean_song_title("東京音頭 / Tokyo Ondo"), "東京音頭")
        self.assertEqual(clean_song_title("ダンシングヒーロー盆踊り"), "ダンシングヒーロー")


if __name__ == "__main__":
    unittest.main()
