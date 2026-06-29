import unittest

from promote_x_news_digest_reviews import build


class PromoteXNewsDigestReviewsTest(unittest.TestCase):
    def digest(self):
        return {
            "generated_at": "2026-06-27T00:00:00+00:00",
            "candidates": [
                {
                    "candidate_id": "xoto_1",
                    "source_urls": ["https://x.com/example/status/1"],
                    "source_authors": ["@bon"],
                    "source_text_excerpt": "7月に佐竹商店街で佐竹ゲバゲバ盆踊りを開催。",
                    "machine_digest_summary": "イベント候補に関するX由来情報。",
                    "information_type": "new_event_candidate",
                    "promotion_target": "event",
                    "novelty_assessment": "new",
                    "novelty_reason": "既存イベントに完全一致しない",
                    "possible_event_name": "佐竹ゲバゲバ盆踊り",
                    "possible_venue": "",
                    "possible_area": "台東区",
                    "possible_date_text": "7月",
                    "possible_song_names": [],
                    "matched_existing_events": [],
                    "matched_existing_venues": [{"name": "佐竹商店街"}],
                    "matched_existing_songs": [],
                    "web_backcheck_queries": ["佐竹ゲバゲバ盆踊り 台東区 盆踊り"],
                },
                {
                    "candidate_id": "xoto_2",
                    "source_urls": ["https://x.com/example/status/2"],
                    "machine_digest_summary": "ノイズ候補",
                    "promotion_target": "event",
                    "novelty_assessment": "new",
                },
            ],
        }

    def test_promotes_only_oto_reviewed_rows(self):
        reviews = {
            "reviews": [
                {
                    "candidate_id": "xoto_1",
                    "decision": "promote",
                    "oto_interpreted_summary": "佐竹商店街で佐竹ゲバゲバ盆踊りの開催情報が出ており、新規イベント候補として裏どりする。",
                    "oto_novelty_assessment": "new",
                    "promotion_target": "event",
                    "oto_notes": "X本文は内部確認用。公開文は要約を使う。",
                }
            ]
        }
        result = build(self.digest(), reviews)
        self.assertEqual(result["summary"]["promoted_count"], 1)
        row = result["candidates"][0]
        self.assertEqual(row["candidate_id"], "xoto_1")
        self.assertEqual(row["promotion_target"], "event")
        self.assertEqual(row["novelty_assessment"], "new")
        self.assertIn("新規イベント候補", row["oto_interpreted_summary"])
        self.assertIn("7月に佐竹商店街", row["internal_source_excerpt"])

    def test_skips_promote_without_oto_summary(self):
        reviews = {"reviews": [{"candidate_id": "xoto_1", "decision": "promote"}]}
        result = build(self.digest(), reviews)
        self.assertEqual(result["summary"]["promoted_count"], 0)
        self.assertEqual(result["skipped"][0]["reason"], "missing_oto_interpreted_summary")

    def test_review_can_clear_machine_hint_fields(self):
        reviews = {
            "reviews": [
                {
                    "candidate_id": "xoto_1",
                    "decision": "promote",
                    "oto_interpreted_summary": "佐竹商店街で佐竹ゲバゲバ盆踊りの開催情報が出ている。",
                    "possible_venue": "",
                }
            ]
        }
        result = build(self.digest(), reviews)
        self.assertEqual(result["candidates"][0]["possible_venue"], "")

    def test_reject_is_not_promoted(self):
        reviews = {
            "reviews": [
                {
                    "candidate_id": "xoto_1",
                    "decision": "reject",
                    "oto_interpreted_summary": "ノイズ",
                }
            ]
        }
        result = build(self.digest(), reviews)
        self.assertEqual(result["summary"]["promoted_count"], 0)
        self.assertEqual(result["skipped"][0]["reason"], "reject")


if __name__ == "__main__":
    unittest.main()
