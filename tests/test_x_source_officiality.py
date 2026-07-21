import unittest

from collection_support.x_source_officiality import assess_source_officiality


class XSourceOfficialityTest(unittest.TestCase):
    def test_registered_official_social_source_is_confirmed(self):
        result = assess_source_officiality(
            {
                "source_urls": ["https://x.com/iri2choukai/status/2069959259895496872"],
                "source_authors": ["@iri2choukai"],
            }
        )

        self.assertEqual(result["classification"], "registered_official_social")
        self.assertEqual(result["handle"], "@iri2choukai")

    def test_org_profile_and_schedule_post_becomes_candidate(self):
        result = assess_source_officiality(
            {
                "source_authors": ["@town"],
                "possible_event_name": "中央納涼盆踊り",
                "possible_venue": "中央公園",
                "source_text_excerpt": "中央納涼盆踊りを8月3日 18:30から中央公園で開催します。",
            },
            account_profiles={
                "town": {
                    "handle": "@town",
                    "name": "中央町会",
                    "description": "東京都中央区の町会公式広報です。",
                    "location": "東京都中央区",
                }
            },
        )

        self.assertEqual(result["classification"], "candidate_official_social")
        self.assertIn("organization_profile", result["reasons"][0])
        self.assertEqual(result["recommended_action"], "review_account_then_register_if_confirmed")

    def test_personal_profile_stays_unknown(self):
        result = assess_source_officiality(
            {
                "source_authors": ["@fan"],
                "possible_event_name": "中央納涼盆踊り",
                "source_text_excerpt": "中央納涼盆踊りに行ってきた。楽しかった。",
            },
            account_profiles={
                "fan": {
                    "handle": "@fan",
                    "name": "盆踊り好き",
                    "description": "盆踊り巡りが趣味です。",
                }
            },
        )

        self.assertEqual(result["classification"], "unknown_or_personal_social")


if __name__ == "__main__":
    unittest.main()
