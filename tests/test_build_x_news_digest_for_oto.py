import unittest

from build_x_news_digest_for_oto import build_candidates


class BuildRareSignalCandidatesTest(unittest.TestCase):
    def catalog(self):
        return {
            "events": [
                {"id": "event_known", "name": "築地本願寺納涼盆踊り大会", "area": "中央区", "venue": "築地本願寺"},
            ],
            "venues": [
                {"id": "venue_known", "name": "築地本願寺", "area": "中央区"},
                {"id": "venue_satake", "name": "佐竹商店街", "area": "台東区"},
            ],
            "songs": [
                {"id": "song_tokyo", "name": "東京音頭"},
            ],
        }

    def test_builds_new_event_candidate_from_x_post(self):
        voices = [
            {
                "source": "x",
                "url": "https://x.com/example/status/1",
                "account": "@bon",
                "text": "7月に佐竹商店街で佐竹ゲバゲバ盆踊りを開催。曲目は東京音頭。",
            }
        ]
        data = build_candidates(voices, self.catalog())
        self.assertEqual(len(data), 1)
        row = data[0]
        self.assertEqual(row["information_type"], "new_event_candidate")
        self.assertEqual(row["promotion_target"], "event")
        self.assertEqual(row["novelty_assessment"], "new")
        self.assertIn("佐竹ゲバゲバ盆踊り", row["possible_event_name"])
        self.assertEqual(row["matched_existing_venues"][0]["name"], "佐竹商店街")
        self.assertEqual(row["oto_review_status"], "pending")
        self.assertEqual(row["oto_interpreted_summary"], "")
        self.assertNotIn("7月に佐竹商店街で佐竹ゲバゲバ盆踊りを開催", row["machine_digest_summary"])

    def test_builds_event_update_candidate_for_known_event_with_date(self):
        voices = [
            {
                "source": "x_whitelist",
                "url": "https://x.com/example/status/2",
                "text": "築地本願寺納涼盆踊り大会は2026年7月29日から開催予定です。",
            }
        ]
        data = build_candidates(voices, self.catalog())
        self.assertEqual(len(data), 1)
        row = data[0]
        self.assertEqual(row["information_type"], "event_update_candidate")
        self.assertEqual(row["novelty_assessment"], "update")
        self.assertEqual(row["matched_existing_events"][0]["name"], "築地本願寺納涼盆踊り大会")

    def test_ignores_non_x_sources_and_irrelevant_x(self):
        voices = [
            {"source": "youtube", "url": "https://example.test/1", "text": "佐竹ゲバゲバ盆踊り"},
            {"source": "x", "url": "https://x.com/example/status/3", "text": "今日は暑いですね"},
        ]
        self.assertEqual(build_candidates(voices, self.catalog()), [])

    def test_song_candidates_are_not_buried_after_new_events(self):
        voices = [
            {
                "source": "x",
                "url": "https://x.com/example/status/event",
                "text": "8月に佐竹商店街で佐竹ゲバゲバ盆踊りを開催。",
            },
            {
                "source": "x",
                "url": "https://x.com/example/status/song",
                "text": "盆踊りの曲目に白浜音頭が入っているらしい。",
            },
        ]
        rows = build_candidates(voices, self.catalog())
        self.assertEqual([row["information_type"] for row in rows], ["new_song_candidate", "new_event_candidate"])


if __name__ == "__main__":
    unittest.main()
