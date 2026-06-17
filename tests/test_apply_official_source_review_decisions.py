import unittest

from apply_official_source_review_decisions import apply_row, clean_event_name


class ApplyOfficialSourceReviewDecisionsTest(unittest.TestCase):
    def test_clean_event_name_removes_date_and_time(self):
        self.assertEqual(
            clean_event_name("「喜多見盆踊り大会」 7月26日(土)-27日(日)。"),
            "「喜多見盆踊り大会」",
        )
        self.assertEqual(
            clean_event_name("納涼盆踊り大会 8月3日(日)-4日(月) 19:00-。"),
            "納涼盆踊り大会",
        )

    def test_apply_row_reuses_unique_venue_match(self):
        events = [{
            "venue": "小田急線喜多見駅前 南口広場",
            "event_name": "喜多見盆踊り大会",
            "official_sources": [],
            "aliases": [],
            "confirmation_terms": [],
        }]
        result = apply_row(events, {
            "decision": "hp",
            "source_url": "https://kitaminavi.com/topic/1337",
            "venue": "小田急線喜多見駅前 南口広場",
            "event_name": "「喜多見盆踊り大会」 7月26日(土)-27日(日)。",
            "event_month": "7月",
        })

        self.assertFalse(result["created_event"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["official_sources"], ["https://kitaminavi.com/topic/1337"])
        self.assertIn("「喜多見盆踊り大会」 7月26日(土)-27日(日)。", events[0]["aliases"])


if __name__ == "__main__":
    unittest.main()
