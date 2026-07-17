import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from review_inbox_source_adapter import adapt_source_payload, load_adapted_source


class FutureSourceAdapter:
    source_id = "future_fixture"

    def adapt(self, payload):
        rows = payload["rows"]
        first = rows.pop(0)
        return [
            {
                "kind": "official_source",
                "domain": "公式情報",
                "title": first["event_name"],
                "event_name": first["event_name"],
                "source_key": first["key"],
                "source_url": first["url"],
                "recommended_action": "review_official_source",
                "payload": first,
            }
        ]


def source_payload():
    return {
        "rows": [
            {
                "key": "marunouchi|2026",
                "event_name": "丸の内de盆踊り",
                "url": "https://example.com/marunouchi",
            }
        ]
    }


class ReviewInboxSourceAdapterTest(unittest.TestCase):
    def test_adapter_isolated_from_input_and_emits_stable_future_item(self):
        payload = source_payload()
        before = copy.deepcopy(payload)

        first = adapt_source_payload(FutureSourceAdapter(), payload)
        second = adapt_source_payload(FutureSourceAdapter(), payload)

        self.assertEqual(payload, before)
        self.assertEqual(first, second)
        self.assertEqual(first[0]["source_id"], "future_fixture")
        self.assertEqual(first[0]["time_scope"], "future")
        self.assertTrue(first[0]["inbox_id"].startswith("inbox_"))
        self.assertNotIn("status", first[0])

    def test_loader_records_exact_input_file_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.json"
            raw = (json.dumps(source_payload(), ensure_ascii=False, indent=2) + "\n").encode()
            path.write_bytes(raw)

            result = load_adapted_source(FutureSourceAdapter(), path)

        self.assertEqual(result["input_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["input_size_bytes"], len(raw))
        self.assertEqual(result["item_count"], 1)

    def test_duplicate_stable_ids_are_rejected(self):
        class DuplicateAdapter:
            source_id = "duplicate"

            def adapt(self, payload):
                item = {"kind": "term", "title": "盆踊り", "source_key": "same"}
                return [item, dict(item)]

        with self.assertRaisesRegex(ValueError, "duplicate stable ids"):
            adapt_source_payload(DuplicateAdapter(), {})

    def test_adapter_cannot_write_decision_lifecycle(self):
        class DecisionAdapter:
            source_id = "unsafe"

            def adapt(self, payload):
                return [
                    {
                        "kind": "term",
                        "title": "盆踊り",
                        "source_key": "term|bonodori",
                        "decision": "accepted",
                    }
                ]

        with self.assertRaisesRegex(ValueError, "cannot set lifecycle fields"):
            adapt_source_payload(DecisionAdapter(), {})

    def test_adapter_rejects_unknown_time_scope(self):
        class InvalidScopeAdapter:
            source_id = "invalid_scope"

            def adapt(self, payload):
                return [
                    {
                        "kind": "term",
                        "title": "盆踊り",
                        "source_key": "term|bonodori",
                        "time_scope": "current",
                    }
                ]

        with self.assertRaisesRegex(ValueError, "unsupported review inbox time_scope"):
            adapt_source_payload(InvalidScopeAdapter(), {})


if __name__ == "__main__":
    unittest.main()
