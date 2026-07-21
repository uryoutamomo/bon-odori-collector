import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from review_inbox_adapters.parity import build_parity_report, load_adapted_snapshot
from review_inbox_adapters.registered_event_investigation_adapter import (
    SHIROKANE_CANARY_SOURCE_KEY,
    RegisteredEventInvestigationAdapter,
    build_snapshot,
)
from review_inbox_adapters.source_adapter import adapt_source_payload, write_adapted_snapshot


FIXTURE = Path(__file__).parent / "fixtures" / "registered_event_investigation_shirokane.json"
EXPECTED_FIXTURE_SHA256 = "6fa38f4bec732163a3ab2187d2f29346d750edd8fa7ce156fe06d102eee364c6"
EXPECTED_INBOX_ID = "inbox_707cbf17503827d2"
EXPECTED_PAYLOAD_HASH = "1293d3f0934bcd7dad33484206f210f68d53d0ae39396162173739f5c2fd87a5"


def task(**overrides):
    value = {
        "task_id": "evtinv_fixture",
        "scope": "primary_unconfirmed",
        "occurrence_id": "occ_fixture",
        "event_name": "未来イベント",
        "event_year": 2026,
        "missing_date": True,
        "missing_venue": False,
        "known_venue_names": ["未来公園"],
        "source_url": "https://example.com/future",
        "needs_name_review": False,
        "needs_occurrence_split": False,
        "priority_score": 9,
        "priority_label": "P1",
        "recommended_action": "pre_cutover_quick_research",
    }
    value.update(overrides)
    return value


class RegisteredEventInvestigationAdapterTest(unittest.TestCase):
    def test_shirokane_canary_is_future_occurrence_creation_without_lifecycle(self):
        snapshot = build_snapshot(FIXTURE, canary=True)
        item = snapshot["items"][0]

        self.assertEqual(snapshot["selection"], {
            "mode": "canary",
            "source_keys": [SHIROKANE_CANARY_SOURCE_KEY],
        })
        self.assertEqual(snapshot["write_mode"], "snapshot_only_default_off")
        self.assertEqual(item["source_id"], "registered_event_investigation")
        self.assertEqual(item["source_key"], SHIROKANE_CANARY_SOURCE_KEY)
        self.assertEqual(item["kind"], "occurrence_creation")
        self.assertEqual(item["time_scope"], "future")
        self.assertEqual(item["event_year"], 2023)
        self.assertEqual(item["venue"], "白金児童遊園")
        self.assertEqual(item["payload"]["occurrence_id"], "occ_fbba78bb63034a2f")
        for field in ("status", "decision", "decided_by", "decided_at", "decision_route"):
            self.assertNotIn(field, {key: value for key, value in item.items() if key != "payload"})

    def test_task_kinds_cover_date_venue_and_occurrence_review(self):
        payload = {
            "tasks": [
                task(task_id="date", missing_date=True),
                task(task_id="venue", missing_date=False, missing_venue=True),
                task(task_id="name", needs_name_review=True),
            ]
        }
        items = adapt_source_payload(RegisteredEventInvestigationAdapter(), payload)

        self.assertEqual(
            [item["kind"] for item in items],
            ["current_year_confirmation", "venue_review", "occurrence_creation"],
        )
        self.assertEqual({item["time_scope"] for item in items}, {"future"})

    def test_selection_rejects_unknown_source_key(self):
        with self.assertRaisesRegex(ValueError, "missing source keys"):
            adapt_source_payload(
                RegisteredEventInvestigationAdapter(["evtinv_missing"]),
                {"tasks": [task()]},
            )

    def test_canary_snapshot_records_input_adapter_stable_id_and_payload_lineage(self):
        raw = FIXTURE.read_bytes()
        expected_input_sha = hashlib.sha256(raw).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            snapshot_path = Path(tmp) / "shirokane-canary.json"
            snapshot = build_snapshot(FIXTURE, canary=True)
            write_adapted_snapshot(snapshot, snapshot_path)
            loaded = load_adapted_snapshot(snapshot_path)
            source_task = json.loads(FIXTURE.read_text(encoding="utf-8"))["tasks"][0]
            item = {
                "inbox_id": EXPECTED_INBOX_ID,
                "kind": "occurrence_creation",
                "time_scope": "future",
                "event_name": "盆ダンスフェスティバル2023",
                "venue": "白金児童遊園",
                "event_year": 2023,
                "source_id": "registered_event_investigation",
                "source_url": source_task["source_url"],
                "recommended_action": "queue_for_post_cutover_research",
                "payload": source_task,
                "source_payload_hash": EXPECTED_PAYLOAD_HASH,
                "status": "pending",
            }
            report = build_parity_report(
                [loaded],
                {"source": "fixture.current_observation", "items": [item]},
            )
            expected_snapshot_sha = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()

        self.assertEqual(expected_input_sha, EXPECTED_FIXTURE_SHA256)
        self.assertEqual(loaded["input_sha256"], EXPECTED_FIXTURE_SHA256)
        self.assertEqual(loaded["adapter_snapshot_sha256"], expected_snapshot_sha)
        self.assertEqual(item["inbox_id"], EXPECTED_INBOX_ID)
        self.assertEqual(item["source_payload_hash"], EXPECTED_PAYLOAD_HASH)
        self.assertTrue(report["summary"]["parity"])
        self.assertEqual(report["summary"]["missing_count"], 0)
        self.assertEqual(report["summary"]["extra_count"], 0)
        self.assertEqual(report["summary"]["content_mismatch_count"], 0)
        lineage = report["sources"][0]["input"]
        self.assertEqual(lineage["sha256"], expected_input_sha)
        self.assertEqual(lineage["adapter_snapshot_sha256"], loaded["adapter_snapshot_sha256"])


if __name__ == "__main__":
    unittest.main()
