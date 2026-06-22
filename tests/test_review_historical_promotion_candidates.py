import unittest

import review_historical_promotion_candidates as reviewer


class ReviewHistoricalPromotionCandidatesTest(unittest.TestCase):
    def test_existing_references_are_not_classified_ready_again(self):
        row = {
            "candidate_id": "cand1",
            "target_event_name": "山王音頭と民踊大会",
            "target_occurrence_id": "occ1",
            "event_year": 2026,
            "date_start": "",
            "date_end": "",
            "date_status": "unknown",
            "venue_id": "ven1",
            "venue": "山王パークタワー公開空地",
            "match_score": 100,
            "promotion_confidence": "high",
            "auto_promote_eligible": 1,
            "historical_years_json": "[2024, 2025]",
            "exact_dates_json": '{"2024": ["2024-06-13"], "2025": ["2025-06-13"]}',
            "year_only_evidence_json": "{}",
            "existing_historical_reference_dates": 2,
            "evidence_url_count": 4,
            "song_title_count": 2,
        }

        result = reviewer.classify(row)

        self.assertEqual(result["review_action"], "already_has_historical_reference")
        self.assertEqual(result["insertable_historical_years"], [2024, 2025])
        self.assertIn("historical_reference_already_recorded", result["review_reasons"])


if __name__ == "__main__":
    unittest.main()
