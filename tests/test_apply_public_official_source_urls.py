import unittest

from apply_public_official_source_urls import apply_sources


class ApplyPublicOfficialSourceUrlsTest(unittest.TestCase):
    def test_applies_official_source_by_exact_event_and_venue(self):
        evergreen = {
            "events": [{
                "event_name": "神田明神納涼祭り アニソン盆踊り",
                "venue": "神田明神境内",
                "official_sources": ["https://example.com/official"],
                "official_source_type": "official",
            }]
        }
        public = [{
            "name": "神田明神納涼祭り アニソン盆踊り",
            "venue": "神田明神境内",
            "source_urls": [],
        }]

        summary = apply_sources(evergreen, public)

        self.assertEqual(summary["matched"], 1)
        self.assertEqual(summary["updated"], 1)
        self.assertEqual(public[0]["source_urls"][0]["url"], "https://example.com/official")
        self.assertEqual(public[0]["source_urls"][0]["kind"], "official")

    def test_prefers_2026_when_name_has_year_suffix(self):
        evergreen = {
            "events": [{
                "event_name": "郡上おどり in 青山",
                "venue": "秩父宮ラグビー場駐車場",
                "official_sources": ["https://example.com/2026/detail"],
                "official_source_type": "official",
            }]
        }
        public = [
            {"name": "郡上おどり in 青山 2025", "venue": "秩父宮ラグビー場駐車場", "source_urls": []},
            {"name": "郡上おどり in 青山 2026", "venue": "秩父宮ラグビー場駐車場", "source_urls": []},
        ]

        summary = apply_sources(evergreen, public)

        self.assertEqual(summary["matched"], 1)
        self.assertEqual(summary["updated"], 1)
        self.assertEqual(public[0]["source_urls"], [])
        self.assertEqual(public[1]["source_urls"][0]["url"], "https://example.com/2026/detail")

    def test_excludes_stale_urls(self):
        evergreen = {
            "events": [{
                "event_name": "築地本願寺納涼盆踊り大会",
                "venue": "築地本願寺",
                "official_sources": ["https://tsukijihongwanji.jp/news/10279/"],
                "official_source_type": "official",
            }]
        }
        public = [{"name": "築地本願寺納涼盆踊り大会", "venue": "築地本願寺", "source_urls": []}]

        summary = apply_sources(evergreen, public)

        self.assertEqual(summary["matched"], 0)
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(public[0]["source_urls"], [])


if __name__ == "__main__":
    unittest.main()
