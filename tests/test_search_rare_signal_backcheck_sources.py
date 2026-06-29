import unittest

from search_rare_signal_backcheck_sources import (
    build,
    classify_url,
    official_social_candidates,
    parse_rss,
)


class SearchRareSignalBackcheckSourcesTest(unittest.TestCase):
    def payload(self):
        return {
            "generated_at": "2026-06-27T00:00:00+00:00",
            "queue": [
                {
                    "candidate_id": "xoto_event",
                    "primary_name": "佐竹ゲバゲバ盆踊り",
                    "possible_event_name": "佐竹ゲバゲバ盆踊り",
                    "possible_venue": "佐竹商店街",
                    "possible_area": "台東区",
                    "possible_date_text": "7月",
                    "oto_interpreted_summary": "佐竹商店街で佐竹ゲバゲバ盆踊りの開催候補。",
                    "search_queries": ["佐竹ゲバゲバ盆踊り 台東区 盆踊り"],
                }
            ],
        }

    def test_collects_non_x_candidates_but_does_not_confirm(self):
        def fake_fetcher(query, timeout):
            return [
                {
                    "title": "佐竹ゲバゲバ盆踊り - 佐竹商店街",
                    "url": "https://satake-shotengai.example.jp/bonodori",
                    "description": "佐竹商店街で開催される盆踊りのお知らせです。",
                },
                {
                    "title": "X post",
                    "url": "https://x.com/example/status/1",
                    "description": "佐竹ゲバゲバ盆踊り",
                },
            ]

        result = build(self.payload(), fake_fetcher, queries_per_candidate=1)
        row = result["candidates"][0]

        self.assertTrue(result["policy"]["does_not_confirm"])
        self.assertEqual(row["backcheck_status"], "source_candidates_found")
        self.assertEqual(len(row["source_candidates"]), 1)
        self.assertEqual(row["source_candidates"][0]["source_type"], "official_or_public")
        self.assertEqual(result["summary"]["result_count"], 2)
        self.assertEqual(result["summary"]["candidate_source_count"], 1)

    def test_noise_result_is_not_kept(self):
        def fake_fetcher(query, timeout):
            return [
                {
                    "title": "Tokyo hotel map",
                    "url": "https://travel.example.com/maps/tokyo",
                    "description": "hotel map",
                }
            ]

        result = build(self.payload(), fake_fetcher, queries_per_candidate=1)
        self.assertEqual(result["candidates"][0]["backcheck_status"], "no_candidate_sources_found")
        self.assertEqual(result["summary"]["candidate_source_count"], 0)

    def test_parse_rss(self):
        xml = """<?xml version="1.0"?>
        <rss><channel><item><title>Title</title><link>https://example.jp</link>
        <description>Description</description></item></channel></rss>"""
        rows = parse_rss(xml)
        self.assertEqual(rows[0]["title"], "Title")
        self.assertEqual(rows[0]["url"], "https://example.jp")

    def test_classify_social(self):
        self.assertEqual(classify_url("https://x.com/example/status/1"), "social")

    def test_registered_official_social_source_is_kept_from_internal_url(self):
        payload = {
            "generated_at": "2026-06-27T00:00:00+00:00",
            "queue": [
                {
                    "candidate_id": "xoto_teppozu",
                    "primary_name": "鉄砲洲納涼盆踊り",
                    "possible_event_name": "鉄砲洲納涼盆踊り",
                    "possible_venue": "鉄砲洲公園",
                    "possible_date_text": "2026年8月3日〜8月5日 18:45〜21:00",
                    "oto_interpreted_summary": "町会公式Xによる鉄砲洲納涼盆踊り告知。",
                    "search_queries": [],
                    "internal_discovery_urls": [
                        "https://x.com/iri2choukai/status/2069959259895496872"
                    ],
                }
            ],
        }

        result = build(payload, queries_per_candidate=1)
        row = result["candidates"][0]

        self.assertEqual(row["backcheck_status"], "source_candidates_found")
        self.assertEqual(row["source_candidates"][0]["source_type"], "official_or_organizer_social")
        self.assertEqual(row["source_candidates"][0]["account"], "@iri2choukai")
        self.assertEqual(result["summary"]["official_social_source_count"], 1)

    def test_registered_official_social_source_candidate_shape(self):
        rows = official_social_candidates(
            {
                "internal_discovery_urls": [
                    "https://x.com/iri2choukai/status/2069959259895496872"
                ],
                "oto_interpreted_summary": "summary",
            }
        )

        self.assertEqual(rows[0]["relevance_hint"], "registered_official_social_account")
        self.assertEqual(rows[0]["account_name"], "入船二丁目町会")


if __name__ == "__main__":
    unittest.main()
