import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from review_inbox_missing_source_url_adapter import (
    DEFAULT_INPUT as SOURCE_URL_INPUT,
    MissingSourceUrlAdapter,
    build_snapshot as build_source_url_snapshot,
)
from review_inbox_missing_venue_adapter import (
    DEFAULT_INPUT as VENUE_INPUT,
    MissingVenueAdapter,
    build_snapshot as build_venue_snapshot,
)
from review_inbox_source_adapter import LIFECYCLE_FIELDS, adapt_source_payload


class ReviewInboxMissingAdaptersTest(unittest.TestCase):
    def test_real_source_url_input_is_a_valid_empty_current_snapshot(self):
        snapshot = build_source_url_snapshot(SOURCE_URL_INPUT)

        self.assertEqual(snapshot["source_id"], "missing_source_url")
        self.assertEqual(snapshot["item_count"], 0)
        self.assertEqual(snapshot["selection"], {"mode": "all", "source_keys": []})

    def test_source_url_actions_only_research_or_stage_change_request(self):
        payload = {
            "review": [
                {
                    "occurrence_id": "occ_research",
                    "event_name": "Research event",
                    "event_year": 2026,
                    "review_action": "source_research_required",
                },
                {
                    "occurrence_id": "occ_candidate",
                    "event_name": "Candidate event",
                    "event_year": 2025,
                    "review_action": "ready_source_url_candidate",
                    "candidate_source_url": "https://example.com/evidence",
                },
            ]
        }
        items = adapt_source_payload(MissingSourceUrlAdapter(), payload)

        self.assertEqual(
            [item["recommended_action"] for item in items],
            ["research_missing_source_url", "stage_source_url_change_request"],
        )
        self.assertEqual([item["time_scope"] for item in items], ["future", "historical"])
        for item in items:
            self.assertFalse(LIFECYCLE_FIELDS.intersection(item))
            self.assertNotIn(item["recommended_action"], {"fill_source_url", "confirm_current_year_date"})

    def test_real_venue_input_has_two_separate_future_research_items(self):
        snapshot = build_venue_snapshot(VENUE_INPUT)

        self.assertEqual(snapshot["source_id"], "missing_venue")
        self.assertEqual(snapshot["item_count"], 2)
        self.assertEqual(snapshot["selection"]["mode"], "all")
        self.assertEqual(len(set(snapshot["selection"]["source_keys"])), 2)
        self.assertEqual({item["kind"] for item in snapshot["items"]}, {"venue_review"})
        self.assertEqual({item["time_scope"] for item in snapshot["items"]}, {"future"})
        self.assertEqual({item["event_year"] for item in snapshot["items"]}, {2026})
        self.assertEqual(
            Counter(item["recommended_action"] for item in snapshot["items"]),
            {
                "research_event_name_and_venue": 1,
                "research_missing_venue": 1,
            },
        )
        for item in snapshot["items"]:
            self.assertFalse(LIFECYCLE_FIELDS.intersection(item))
            self.assertNotIn(item["recommended_action"], {"update_venue", "confirm_current_year_date"})

    def test_unknown_actions_fail_closed(self):
        source_payload = {
            "review": [{
                "occurrence_id": "occ_one",
                "event_name": "One",
                "event_year": 2026,
                "review_action": "fill_source_url",
            }]
        }
        with self.assertRaisesRegex(ValueError, "unsupported missing source URL action"):
            adapt_source_payload(MissingSourceUrlAdapter(), source_payload)

        venue_payload = json.loads(VENUE_INPUT.read_text(encoding="utf-8"))
        venue_payload["review"][0]["review_action"] = "update_venue"
        with self.assertRaisesRegex(ValueError, "unsupported missing venue action"):
            adapt_source_payload(MissingVenueAdapter(), venue_payload)

    def test_duplicate_occurrence_ids_fail_stable_id_validation(self):
        payload = json.loads(VENUE_INPUT.read_text(encoding="utf-8"))
        payload["review"].append(dict(payload["review"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate stable ids"):
            adapt_source_payload(MissingVenueAdapter(), payload)


if __name__ == "__main__":
    unittest.main()
