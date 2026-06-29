import unittest

from export_rare_signal_backcheck_reviews import build


class ExportRareSignalBackcheckReviewsTest(unittest.TestCase):
    def test_confirm_decision_extracts_non_x_url_from_note(self):
        staged = {
            "generated_at": "2026-06-27T00:00:00+00:00",
            "source_id": "rare_signal_backcheck",
            "rows": [
                {
                    "item_id": "rare_signal_backcheck:xoto_1|佐竹ゲバゲバ盆踊り",
                    "source_id": "rare_signal_backcheck",
                    "decision": "accept",
                    "apply_value": "confirm_non_x_source",
                    "note": "公式確認 https://example.com/satake  Xは https://x.com/example/status/1",
                    "reviewer": "内田さん",
                    "reviewed_at": "2026-06-27T00:01:00+00:00",
                    "raw": {
                        "candidate_id": "xoto_1",
                        "possible_event_name": "佐竹ゲバゲバ盆踊り",
                        "possible_venue": "佐竹商店街",
                        "possible_area": "台東区",
                        "possible_date_text": "2026年7月",
                        "oto_interpreted_summary": "佐竹商店街で佐竹ゲバゲバ盆踊りが開催される候補。",
                    },
                }
            ],
        }
        result = build(staged)
        self.assertEqual(result["summary"]["review_count"], 1)
        self.assertEqual(result["summary"]["confirmed_count"], 1)
        review = result["reviews"][0]
        self.assertEqual(review["candidate_id"], "xoto_1")
        self.assertEqual(review["decision"], "confirm")
        self.assertEqual(review["confirmed_source_urls"], ["https://example.com/satake"])
        self.assertEqual(review["venue"], "佐竹商店街")
        self.assertEqual(review["date_text"], "2026年7月")

    def test_confirm_without_non_x_url_is_held_with_warning(self):
        staged = {
            "rows": [
                {
                    "source_id": "rare_signal_backcheck",
                    "decision": "accept",
                    "apply_value": "confirm_non_x_source",
                    "note": "Xのみ https://x.com/example/status/1",
                    "raw": {"candidate_id": "xoto_1"},
                }
            ]
        }
        result = build(staged)
        review = result["reviews"][0]
        self.assertEqual(review["decision"], "hold")
        self.assertEqual(review["review_warning"], "confirm_without_confirmable_url_in_note")
        self.assertEqual(result["summary"]["confirmed_count"], 0)

    def test_confirm_accepts_registered_official_social_url(self):
        staged = {
            "rows": [
                {
                    "source_id": "rare_signal_backcheck",
                    "decision": "accept",
                    "apply_value": "confirm_non_x_source",
                    "note": "町会公式X https://x.com/iri2choukai/status/2069959259895496872",
                    "raw": {
                        "candidate_id": "xoto_teppozu",
                        "possible_event_name": "鉄砲洲納涼盆踊り",
                    },
                }
            ]
        }
        result = build(staged)
        review = result["reviews"][0]

        self.assertEqual(review["decision"], "confirm")
        self.assertEqual(review["confirmed_source_type"], "official_or_organizer_social")
        self.assertEqual(
            review["confirmed_source_urls"],
            ["https://x.com/iri2choukai/status/2069959259895496872"],
        )


if __name__ == "__main__":
    unittest.main()
