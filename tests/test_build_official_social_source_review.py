import unittest

from build_official_social_source_review import build


class BuildOfficialSocialSourceReviewTest(unittest.TestCase):
    def test_builds_review_queue_for_candidate_official_accounts(self):
        payload = {
            "generated_at": "2026-06-29T00:00:00+00:00",
            "candidates": [
                {
                    "candidate_id": "xoto_town",
                    "source_urls": ["https://x.com/town/status/1"],
                    "source_authors": ["@town"],
                    "possible_event_name": "中央納涼盆踊り",
                    "possible_venue": "中央公園",
                    "possible_date_text": "8月3日 18:30",
                    "source_officiality": {
                        "classification": "candidate_official_social",
                        "score": 8,
                        "handle": "@town",
                        "account_name": "中央町会",
                        "reasons": ["organization_profile:町会"],
                    },
                },
                {
                    "candidate_id": "xoto_fan",
                    "source_authors": ["@fan"],
                    "source_officiality": {
                        "classification": "unknown_or_personal_social",
                        "score": 0,
                        "handle": "@fan",
                    },
                },
            ],
        }

        result = build(payload)

        self.assertEqual(result["summary"]["candidate_account_count"], 1)
        self.assertEqual(result["accounts"][0]["handle"], "@town")
        self.assertEqual(result["accounts"][0]["recommendation"], "register_if_profile_confirms_org")


if __name__ == "__main__":
    unittest.main()
