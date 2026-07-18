import copy
import json
import unittest
from collections import Counter

from review_inbox_historical_reference_adapter import (
    DEFAULT_INPUT,
    HistoricalReferenceAdapter,
    build_snapshot,
)
from review_inbox_source_adapter import LIFECYCLE_FIELDS, adapt_source_payload


class ReviewInboxHistoricalReferenceAdapterTest(unittest.TestCase):
    def test_real_rend6_input_has_sixteen_reference_review_items(self):
        snapshot = build_snapshot(DEFAULT_INPUT)

        self.assertEqual(snapshot["source_id"], "historical_reference")
        self.assertEqual(snapshot["item_count"], 16)
        self.assertEqual(snapshot["selection"]["mode"], "all")
        self.assertEqual(len(set(snapshot["selection"]["source_keys"])), 16)
        self.assertEqual({item["kind"] for item in snapshot["items"]}, {"historical_reference"})
        self.assertEqual({item["time_scope"] for item in snapshot["items"]}, {"reference"})
        self.assertEqual(Counter(item["event_year"] for item in snapshot["items"]), {2025: 13, 2026: 3})
        self.assertEqual(
            Counter(item["recommended_action"] for item in snapshot["items"]),
            {
                "review_historical_reference": 13,
                "research_multi_year_history": 2,
                "review_prediction_queue": 1,
            },
        )
        for item in snapshot["items"]:
            self.assertFalse(LIFECYCLE_FIELDS.intersection(item))
            self.assertFalse(
                item["recommended_action"].startswith(("promote_", "auto_promote_", "apply_"))
            )

    def test_unknown_action_and_stale_identity_fail_closed(self):
        payload = json.loads(DEFAULT_INPUT.read_text(encoding="utf-8"))

        unknown = copy.deepcopy(payload)
        unknown["candidates"][0]["recommended_action"] = "promote_current_year"
        with self.assertRaisesRegex(ValueError, "unsupported historical reference action"):
            adapt_source_payload(HistoricalReferenceAdapter(), unknown)

        unresolved = copy.deepcopy(payload)
        unresolved["candidates"][0]["current_identity"]["occurrence_resolved"] = False
        with self.assertRaisesRegex(ValueError, "not current-identity resolved"):
            adapt_source_payload(HistoricalReferenceAdapter(), unresolved)

        mismatch = copy.deepcopy(payload)
        mismatch["candidates"][0]["occurrence_series_id"] = "different_series"
        with self.assertRaisesRegex(ValueError, "does not belong"):
            adapt_source_payload(HistoricalReferenceAdapter(), mismatch)


if __name__ == "__main__":
    unittest.main()
