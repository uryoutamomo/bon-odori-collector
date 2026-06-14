import unittest

from build_retrospective_harvest import build_from_voices


class RetrospectiveHarvestTest(unittest.TestCase):
    def test_builds_event_song_and_venue_candidates_from_voices(self):
        output = build_from_voices(
            [
                {
                    "account": "@a",
                    "date": "2025-06-10T10:00:00+00:00",
                    "tweet_id": "1",
                    "url": "https://x.com/a/status/1",
                    "text": "中央公園の祭りと盆踊りに6月20日行きます。曲目は東京音頭、炭坑節",
                },
                {
                    "account": "@b",
                    "date": "2025-06-11T10:00:00+00:00",
                    "tweet_id": "2",
                    "url": "https://x.com/b/status/2",
                    "text": "中央公園の盆踊り、6月21日開催情報です",
                },
            ],
            generated_at="2026-06-13T00:00:00+00:00",
        )

        kinds = {candidate["kind"] for candidate in output["candidates"]}
        self.assertIn("event", kinds)
        self.assertIn("song", kinds)
        self.assertIn("venue", kinds)
        self.assertEqual(output["voice_count"], 2)
        self.assertGreaterEqual(output["counts"]["suppressed_event_hint_count"], 1)

        event = next(candidate for candidate in output["candidates"] if candidate["kind"] == "event")
        self.assertEqual(event["venue"], "中央公園")
        self.assertEqual(event["month"], "06")
        self.assertEqual(event["normalized_event"], "")
        self.assertEqual(event["evidence"][0]["dancer_key"], "@a")
        self.assertEqual(event["evidence"][0]["observed_at"], "2025-06-10T10:00:00+00:00")

        song = next(candidate for candidate in output["candidates"] if candidate["kind"] == "song")
        self.assertEqual(song["venue"], "中央公園")
        self.assertEqual(song["month"], "06")
        self.assertTrue(song["candidate_key"].startswith("song:"))

    def test_uses_normalized_event_for_specific_event_names(self):
        output = build_from_voices(
            [
                {
                    "account": "odorer",
                    "date": "2025-07-10T10:00:00+00:00",
                    "tweet_id": "3",
                    "url": "https://x.com/odorer/status/3",
                    "text": "今年も浜町公園盆踊りに7月20日行きます",
                },
            ],
            generated_at="2026-06-13T00:00:00+00:00",
        )
        event = next(candidate for candidate in output["candidates"] if candidate["kind"] == "event")
        self.assertEqual(event["normalized_event"], "浜町公園")
        self.assertEqual(event["evidence"][0]["dancer_key"], "@odorer")


if __name__ == "__main__":
    unittest.main()
