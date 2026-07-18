import json
import unittest
from collections import Counter
from pathlib import Path

from review_inbox_predicted_occurrence_date_review_adapter import (
    DEFAULT_INPUT as DATE_REVIEW_INPUT,
    PredictedOccurrenceDateReviewAdapter,
    build_snapshot as build_date_review_snapshot,
)
from review_inbox_predicted_occurrence_research_adapter import (
    DEFAULT_INPUT as RESEARCH_INPUT,
    PredictedOccurrenceResearchAdapter,
    build_snapshot as build_research_snapshot,
)
from review_inbox_source_adapter import adapt_source_payload


LIFECYCLE_FIELDS = {
    "status",
    "decision",
    "decided_by",
    "decided_at",
    "closed_at",
    "decision_route",
}


class ReviewInboxPredictedAdaptersTest(unittest.TestCase):
    def test_real_research_input_has_eight_future_review_items(self):
        snapshot = build_research_snapshot(RESEARCH_INPUT)

        self.assertEqual(snapshot["source_id"], "predicted_occurrence_research")
        self.assertEqual(snapshot["item_count"], 8)
        self.assertEqual(snapshot["selection"]["mode"], "all")
        self.assertEqual(len(snapshot["selection"]["source_keys"]), 8)
        self.assertEqual(len(set(snapshot["selection"]["source_keys"])), 8)
        self.assertEqual({item["kind"] for item in snapshot["items"]}, {"predicted_date"})
        self.assertEqual({item["time_scope"] for item in snapshot["items"]}, {"future"})
        self.assertEqual({item["event_year"] for item in snapshot["items"]}, {2026})
        self.assertEqual(
            Counter(item["priority_label"] for item in snapshot["items"]),
            {"P0": 4, "P1": 3, "P2": 1},
        )
        self.assertEqual(
            Counter(item["recommended_action"] for item in snapshot["items"]),
            {
                "source_recheck_before_promotion": 4,
                "queue_for_source_recheck": 3,
                "keep_prediction_queue_only": 1,
            },
        )
        for item in snapshot["items"]:
            self.assertFalse(LIFECYCLE_FIELDS.intersection(item))

    def test_real_date_review_input_has_twelve_separate_future_items(self):
        snapshot = build_date_review_snapshot(DATE_REVIEW_INPUT)

        self.assertEqual(snapshot["source_id"], "predicted_occurrence_date_review")
        self.assertEqual(snapshot["item_count"], 12)
        self.assertEqual(snapshot["selection"]["mode"], "all")
        self.assertEqual(len(snapshot["selection"]["source_keys"]), 12)
        self.assertEqual(len(set(snapshot["selection"]["source_keys"])), 12)
        self.assertEqual({item["kind"] for item in snapshot["items"]}, {"predicted_date"})
        self.assertEqual({item["time_scope"] for item in snapshot["items"]}, {"future"})
        self.assertEqual({item["event_year"] for item in snapshot["items"]}, {2026})
        self.assertEqual(
            Counter(item["recommended_action"] for item in snapshot["items"]),
            {
                "review_prediction_queue": 8,
                "verify_prediction_curated_match": 1,
                "verify_prediction_supersession": 3,
            },
        )
        for item in snapshot["items"]:
            self.assertFalse(LIFECYCLE_FIELDS.intersection(item))
            self.assertIn("review_action", item["payload"])
            self.assertIn("current_status", item["payload"])
            self.assertNotIn("decision", item)

    def test_overlapping_prediction_ids_remain_distinct_between_sources(self):
        research = build_research_snapshot(RESEARCH_INPUT)
        date_review = build_date_review_snapshot(DATE_REVIEW_INPUT)
        research_by_key = {item["source_key"]: item for item in research["items"]}
        date_by_key = {item["source_key"]: item for item in date_review["items"]}
        overlap = set(research_by_key).intersection(date_by_key)

        self.assertEqual(len(overlap), 8)
        for source_key in overlap:
            self.assertNotEqual(
                research_by_key[source_key]["inbox_id"],
                date_by_key[source_key]["inbox_id"],
            )

    def test_research_rejects_unknown_action_and_date_review_keeps_status_in_payload(self):
        research_payload = json.loads(RESEARCH_INPUT.read_text(encoding="utf-8"))
        research_payload["items"][0]["recommended_action"] = "confirm_current_year_date"
        with self.assertRaisesRegex(ValueError, "unsupported.*research action"):
            adapt_source_payload(PredictedOccurrenceResearchAdapter(), research_payload)

        date_payload = json.loads(DATE_REVIEW_INPUT.read_text(encoding="utf-8"))
        item = adapt_source_payload(PredictedOccurrenceDateReviewAdapter(), date_payload)[0]
        self.assertIn("current_status", item["payload"])
        self.assertNotIn("status", item)
        self.assertNotIn("decision", item)


if __name__ == "__main__":
    unittest.main()
