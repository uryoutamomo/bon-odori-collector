import unittest

from build_youtube_nationwide_hold import build_hold


class BuildYoutubeNationwideHoldTest(unittest.TestCase):
    def test_groups_out_of_scope_rows_by_setlist_occurrence(self):
        hold = build_hold(
            {
                "rows": [
                    {
                        "action": "out_of_scope",
                        "video_id": "a",
                        "video_url": "https://www.youtube.com/watch?v=a",
                        "title": "横浜開港祭 BON ODORI 01",
                        "channel_title": "Channel A",
                        "published_at": "2026-06-05T00:00:00+00:00",
                        "detected_event_date": "2026-06-01",
                        "setlist_occurrences": [
                            {
                                "event_name": "横浜開港祭 BON ODORI",
                                "venue": "パシフィコ横浜プラザ広場",
                                "event_date": "2026-06-01",
                                "song_count": 14,
                            }
                        ],
                    },
                    {
                        "action": "out_of_scope",
                        "video_id": "b",
                        "video_url": "https://www.youtube.com/watch?v=b",
                        "title": "横浜開港祭 BON ODORI 02",
                        "channel_title": "Channel B",
                        "published_at": "2026-06-05T00:00:00+00:00",
                        "detected_event_date": "2026-06-01",
                        "setlist_occurrences": [
                            {
                                "event_name": "横浜開港祭 BON ODORI",
                                "venue": "パシフィコ横浜プラザ広場",
                                "event_date": "2026-06-01",
                                "song_count": 14,
                            }
                        ],
                    },
                    {"action": "ignore", "video_id": "c"},
                ]
            }
        )

        self.assertEqual(hold["candidate_count"], 1)
        self.assertEqual(hold["video_count"], 2)
        candidate = hold["candidates"][0]
        self.assertEqual(candidate["scope_status"], "hold_for_nationwide_expansion")
        self.assertEqual(candidate["event_name"], "横浜開港祭 BON ODORI")
        self.assertEqual(candidate["channels"], ["Channel A", "Channel B"])
        self.assertEqual(len(candidate["videos"]), 2)


if __name__ == "__main__":
    unittest.main()
