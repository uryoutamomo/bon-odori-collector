import unittest
from datetime import datetime, timezone

from build_event_poster_ocr_queue import build


class BuildEventPosterOcrQueueTest(unittest.TestCase):
    def test_trusted_informant_media_post_becomes_critical_ocr_candidate(self):
        rows = [
            {
                "source": "x",
                "account": "@gPVEQeAD9U10257",
                "name": "なつたろ",
                "url": "https://x.com/gPVEQeAD9U10257/status/1",
                "tweet_id": "1",
                "date": "2026-07-11T12:00:00+09:00",
                "text": "盆踊りのポスターが出ていました",
                "media_urls": ["https://pbs.twimg.com/media/poster.jpg"],
            }
        ]
        informants = {
            "gpveqead9u10257": {
                "handle": "@gPVEQeAD9U10257",
                "name": "なつたろ",
                "usefulness_rank": "S",
            }
        }

        output = build(rows, informants=informants)

        self.assertEqual(output["count"], 1)
        item = output["items"][0]
        self.assertEqual(item["priority"], "critical")
        self.assertEqual(item["evidence_type"], "trusted_field_reporter_poster_image")
        self.assertEqual(item["assumed_source_confidence"], "high")
        self.assertTrue(item["trusted_informant"])

    def test_non_media_post_is_not_queued(self):
        output = build(
            [
                {
                    "source": "x",
                    "account": "@gPVEQeAD9U10257",
                    "text": "盆踊りのポスターが出ていました",
                }
            ],
            informants={"gpveqead9u10257": {"handle": "@gPVEQeAD9U10257"}},
        )

        self.assertEqual(output["count"], 0)

    def test_default_daily_build_can_ignore_old_posts(self):
        rows = [
            {
                "source": "x",
                "account": "@poster",
                "url": "https://x.com/poster/status/old",
                "tweet_id": "old",
                "date": "2026-01-01T00:00:00+00:00",
                "text": "盆踊りのポスターです。8月2日開催。",
                "media_urls": ["https://pbs.twimg.com/media/old.jpg"],
            }
        ]

        output = build(
            rows,
            informants={},
            max_age_days=90,
            now=datetime(2026, 7, 11, tzinfo=timezone.utc),
        )

        self.assertEqual(output["count"], 0)


if __name__ == "__main__":
    unittest.main()
