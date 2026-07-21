import unittest

from youtube_backfill.build_youtube_event_review import build_rows, infer_event_name, infer_venue


class BuildYoutubeEventReviewTest(unittest.TestCase):
    def test_infers_event_and_venue_from_description(self):
        row = {
            "title": "レッツONDOアゲイン 鉄砲洲納涼盆踊り17 2025年8月4日 東京都中央区 鉄砲洲公園",
            "description_excerpt": "2025年8月4日に行われました、 「鉄砲洲納涼盆踊り」の様子です。 鉄砲洲児童公園盆踊り",
        }
        self.assertEqual(infer_event_name(row), "鉄砲洲納涼盆踊り")
        self.assertEqual(infer_venue(row), "鉄砲洲児童公園")

    def test_builds_existing_event_match(self):
        rows = build_rows(
            {
                "event_candidates": [
                    {
                        "video_id": "abc",
                        "url": "https://www.youtube.com/watch?v=abc",
                        "title": "山王音頭と民踊大会 2025年6月13日",
                        "description_excerpt": "赤坂日枝神社で行われました、 「山王音頭と民踊大会」の様子です。",
                        "event_date": "2025-06-13",
                        "channel_title": "和太鼓お祭りチャンネル",
                        "setlist_count": 10,
                    }
                ]
            },
            [
                {
                    "name": "山王音頭と民踊大会",
                    "venue": "山王パークタワー公開空地",
                    "date": "2026-06-13",
                    "date_end": "2026-06-15",
                }
            ],
            [{"venue": "山王パークタワー公開空地"}],
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["matched_public_event"]["name"], "山王音頭と民踊大会")
        self.assertEqual(rows[0]["review_priority"], "既存補強")


if __name__ == "__main__":
    unittest.main()
