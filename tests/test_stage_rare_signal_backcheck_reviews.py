import unittest

from stage_rare_signal_backcheck_reviews import build


class StageRareSignalBackcheckReviewsTest(unittest.TestCase):
    def queue(self):
        return {
            "generated_at": "2026-06-27T00:00:00+00:00",
            "queue": [
                {
                    "candidate_id": "xoto_confirmed",
                    "promotion_target": "event",
                    "novelty_assessment": "new",
                    "primary_name": "佐竹ゲバゲバ盆踊り",
                    "possible_event_name": "佐竹ゲバゲバ盆踊り",
                    "possible_venue": "",
                    "possible_area": "台東区",
                    "possible_date_text": "7月",
                    "possible_song_names": [],
                    "oto_interpreted_summary": "佐竹商店街で佐竹ゲバゲバ盆踊りの開催情報があり、新規候補として裏どりする。",
                    "source_policy": "x_discovery_only_non_x_confirmation_required",
                    "internal_discovery_urls": ["https://x.com/example/status/1"],
                },
                {
                    "candidate_id": "xoto_pending",
                    "promotion_target": "event",
                    "primary_name": "未確認盆踊り",
                    "possible_event_name": "未確認盆踊り",
                },
            ],
        }

    def test_stages_only_confirmed_rows_with_non_x_url(self):
        reviews = {
            "reviews": [
                {
                    "candidate_id": "xoto_confirmed",
                    "decision": "confirm",
                    "confirmed_source_urls": ["https://example.com/satake-bonodori"],
                    "confirmed_source_type": "local_media",
                    "venue": "佐竹商店街",
                    "date_text": "2026年7月",
                    "public_summary": "佐竹商店街で佐竹ゲバゲバ盆踊りが開催される確認が取れた。",
                }
            ]
        }
        result = build(self.queue(), reviews)
        self.assertEqual(result["summary"]["staged_count"], 1)
        self.assertEqual(result["summary"]["skipped_count"], 1)
        row = result["event_candidates"][0]
        self.assertEqual(result["registration_candidates"], result["event_candidates"])
        self.assertTrue(row["ready_for_registration"])
        self.assertEqual(row["event_name"], "佐竹ゲバゲバ盆踊り")
        self.assertEqual(row["venue"], "佐竹商店街")
        self.assertEqual(row["date_text"], "2026年7月")
        self.assertEqual(row["confirmed_source_urls"], ["https://example.com/satake-bonodori"])
        self.assertEqual(row["internal_discovery_urls"], ["https://x.com/example/status/1"])

    def test_rejects_x_only_confirmation_url(self):
        reviews = {
            "reviews": [
                {
                    "candidate_id": "xoto_confirmed",
                    "decision": "confirm",
                    "confirmed_source_urls": ["https://x.com/example/status/1"],
                }
            ]
        }
        result = build(self.queue(), reviews)
        self.assertEqual(result["summary"]["staged_count"], 0)
        self.assertEqual(result["skipped"][0]["reason"], "missing_confirmable_source_url")

    def test_stages_registered_official_social_confirmation_url(self):
        reviews = {
            "reviews": [
                {
                    "candidate_id": "xoto_confirmed",
                    "decision": "confirm",
                    "confirmed_source_urls": [
                        "https://x.com/iri2choukai/status/2069959259895496872"
                    ],
                    "confirmed_source_type": "official_or_organizer_social",
                    "venue": "鉄砲洲公園",
                    "date_text": "2026年8月3日〜8月5日 18:45〜21:00",
                }
            ]
        }
        queue = self.queue()
        queue["queue"][0]["possible_event_name"] = "鉄砲洲納涼盆踊り"
        queue["queue"][0]["primary_name"] = "鉄砲洲納涼盆踊り"
        result = build(queue, reviews)
        row = result["event_candidates"][0]

        self.assertEqual(result["summary"]["staged_count"], 1)
        self.assertTrue(row["ready_for_registration"])
        self.assertEqual(row["confirmed_source_type"], "official_or_organizer_social")

    def test_confirmed_row_can_stage_but_remain_blocked_when_fields_are_missing(self):
        queue = self.queue()
        queue["queue"][0]["possible_area"] = ""
        queue["queue"][0]["possible_date_text"] = ""
        reviews = {
            "reviews": [
                {
                    "candidate_id": "xoto_confirmed",
                    "decision": "confirm",
                    "confirmed_source_urls": ["https://example.com/satake-bonodori"],
                }
            ]
        }
        result = build(queue, reviews)
        row = result["event_candidates"][0]
        self.assertFalse(row["ready_for_registration"])
        self.assertEqual(
            row["registration_blockers"],
            ["missing_venue_or_area", "missing_date_text"],
        )

    def test_hold_is_not_staged(self):
        reviews = {"reviews": [{"candidate_id": "xoto_confirmed", "decision": "hold"}]}
        result = build(self.queue(), reviews)
        self.assertEqual(result["summary"]["staged_count"], 0)
        self.assertEqual(result["skipped"][0]["reason"], "hold")

    def test_song_candidate_can_be_ready_without_event_date(self):
        queue = {
            "generated_at": "2026-06-27T00:00:00+00:00",
            "queue": [
                {
                    "candidate_id": "xoto_song",
                    "promotion_target": "song",
                    "primary_name": "白浜音頭",
                    "possible_song_names": ["白浜音頭"],
                    "oto_interpreted_summary": "白浜音頭が曲候補として言及されている。",
                    "internal_discovery_urls": ["https://x.com/example/status/3"],
                }
            ],
        }
        reviews = {
            "reviews": [
                {
                    "candidate_id": "xoto_song",
                    "decision": "confirm",
                    "confirmed_source_urls": ["https://example.com/shirahama-ondo"],
                    "confirmed_source_type": "official_program",
                }
            ]
        }
        result = build(queue, reviews)
        row = result["registration_candidates"][0]
        self.assertTrue(row["ready_for_registration"])
        self.assertEqual(row["promotion_target"], "song")
        self.assertEqual(row["song_names"], ["白浜音頭"])


if __name__ == "__main__":
    unittest.main()
