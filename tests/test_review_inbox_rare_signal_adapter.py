import copy
import unittest
from pathlib import Path

from review_inbox_parity import build_parity_report, item_payload_hash
from review_inbox_rare_signal_adapter import (
    RareSignalAdapter,
    build_snapshot,
    immutable_source_reference,
)
from review_inbox_source_adapter import (
    LIFECYCLE_FIELDS,
    adapt_source_payload,
    input_sha256,
)


FIXTURE = Path(__file__).parent / "fixtures" / "rare_signal_backcheck_two_examples.json"


class ReviewInboxRareSignalAdapterTest(unittest.TestCase):
    def test_canary_selection_requires_one_exact_stable_key(self):
        source_key = "new_event_candidate|event|x-status:2000000000000000001"
        snapshot = build_snapshot(FIXTURE, canary_source_key=source_key)

        self.assertEqual(snapshot["item_count"], 1)
        self.assertEqual(snapshot["selection"], {"mode": "canary", "source_keys": [source_key]})
        self.assertEqual(snapshot["items"][0]["source_key"], source_key)

        with self.assertRaisesRegex(ValueError, "exactly one item"):
            build_snapshot(FIXTURE, canary_source_key="missing")

    def test_contract_examples_have_stable_lineage_and_zero_diff_parity(self):
        snapshot = build_snapshot(FIXTURE)

        self.assertEqual(snapshot["source_id"], "rare_signal")
        self.assertEqual(snapshot["item_count"], 2)
        self.assertEqual(snapshot["input_sha256"], input_sha256(FIXTURE.read_bytes()))
        self.assertEqual(len(snapshot["input_sha256"]), 64)
        self.assertEqual(snapshot["write_mode"], "snapshot_only_default_off")
        self.assertEqual({item["kind"] for item in snapshot["items"]}, {"rare_signal"})
        self.assertEqual({item["time_scope"] for item in snapshot["items"]}, {"future"})
        self.assertEqual(
            [item["recommended_action"] for item in snapshot["items"]],
            ["research_non_x_confirmation", "review_registered_official_social"],
        )
        self.assertEqual(
            snapshot["selection"]["source_keys"],
            [
                "new_event_candidate|event|x-status:2000000000000000001",
                "event_update_candidate|event|x-status:2069959259895496872",
            ],
        )
        for item in snapshot["items"]:
            self.assertFalse(LIFECYCLE_FIELDS.intersection(item))

        report = build_parity_report([snapshot], {"items": copy.deepcopy(snapshot["items"])})
        self.assertTrue(report["summary"]["parity"])
        self.assertEqual(report["summary"]["expected_count"], 2)
        self.assertEqual(report["summary"]["content_mismatch_count"], 0)

    def test_mutable_candidate_text_and_candidate_id_do_not_change_stable_id(self):
        payload = {
            "queue": [
                {
                    "candidate_id": "old_generated_id",
                    "information_type": "event_update_candidate",
                    "promotion_target": "event",
                    "primary_name": "Before",
                    "oto_interpreted_summary": "Before summary",
                    "next_action": "find_non_x_confirmation",
                    "internal_discovery_urls": [
                        "https://x.com/example/status/2069959259895496872?utm_source=test"
                    ],
                }
            ]
        }
        before = adapt_source_payload(RareSignalAdapter(), payload)[0]
        changed = copy.deepcopy(payload)
        changed["queue"][0]["candidate_id"] = "new_generated_id"
        changed["queue"][0]["primary_name"] = "After"
        changed["queue"][0]["oto_interpreted_summary"] = "Changed summary"
        changed["queue"][0]["internal_discovery_urls"] = [
            "https://twitter.com/example/status/2069959259895496872"
        ]
        after = adapt_source_payload(RareSignalAdapter(), changed)[0]

        self.assertEqual(before["source_key"], after["source_key"])
        self.assertEqual(before["inbox_id"], after["inbox_id"])
        self.assertNotEqual(item_payload_hash(before), item_payload_hash(after))

    def test_generic_urls_are_canonical_and_fragments_are_ignored(self):
        first = immutable_source_reference("HTTPS://Example.JP/event/?b=2&a=1#details")
        second = immutable_source_reference("https://example.jp/event?a=1&b=2")
        self.assertEqual(first, second)

    def test_x_status_identity_ignores_default_port(self):
        self.assertEqual(
            immutable_source_reference("https://x.com:443/example/status/1234567890"),
            "x-status:1234567890",
        )

    def test_unknown_action_target_and_duplicate_identity_fail_closed(self):
        base = {
            "candidate_id": "xoto_one",
            "information_type": "new_event_candidate",
            "promotion_target": "event",
            "primary_name": "One",
            "next_action": "find_non_x_confirmation",
            "internal_discovery_urls": ["https://x.com/example/status/1234567890"],
        }
        unknown_target = {"queue": [{**base, "promotion_target": "public_apply"}]}
        with self.assertRaisesRegex(ValueError, "unsupported rare signal promotion target"):
            adapt_source_payload(RareSignalAdapter(), unknown_target)

        unknown_action = {"queue": [{**base, "next_action": "apply_to_master_db"}]}
        with self.assertRaisesRegex(ValueError, "unsupported rare signal action"):
            adapt_source_payload(RareSignalAdapter(), unknown_action)

        duplicate = {"queue": [base, {**base, "candidate_id": "different_generated_id"}]}
        with self.assertRaisesRegex(ValueError, "duplicate stable ids"):
            adapt_source_payload(RareSignalAdapter(), duplicate)


if __name__ == "__main__":
    unittest.main()
