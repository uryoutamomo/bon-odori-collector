import json
import tempfile
import unittest
from pathlib import Path

from review_inbox import payload_hash
from review_inbox_adapters.parity import (
    build_parity_report,
    load_adapted_snapshot,
    markdown_report,
    write_report,
)


def adapted_item(inbox_id="inbox_one", **overrides):
    item = {
        "inbox_id": inbox_id,
        "kind": "official_source",
        "time_scope": "future",
        "event_name": "丸の内de盆踊り",
        "venue": "行幸通り",
        "event_year": 2026,
        "source_id": "official_fixture",
        "source_url": "https://example.com",
        "recommended_action": "review_official_source",
        "payload": {"evidence": "official"},
    }
    item.update(overrides)
    return item


def inbox_item(**overrides):
    item = adapted_item()
    item["source_payload_hash"] = payload_hash(
        json.dumps(item["payload"], ensure_ascii=False, sort_keys=True)
    )
    item.update(
        {
            "status": "accepted",
            "decision": "accepted",
            "decided_by": "おと（Codex）",
        }
    )
    item.update(overrides)
    return item


def snapshot(items=None):
    return {
        "source_id": "official_fixture",
        "input_path": "data/official.json",
        "input_sha256": "a" * 64,
        "input_size_bytes": 123,
        "items": items if items is not None else [adapted_item()],
    }


class ReviewInboxParityTest(unittest.TestCase):
    def test_exact_parity_ignores_decision_lifecycle(self):
        report = build_parity_report(
            [snapshot()],
            {"source": "master_rdb.review_inbox_items", "items": [inbox_item()]},
        )

        self.assertTrue(report["summary"]["parity"])
        self.assertEqual(report["summary"]["expected_count"], 1)
        self.assertEqual(report["sources"][0]["input"]["sha256"], "a" * 64)
        self.assertIn("`true`", markdown_report(report))

    def test_reports_missing_extra_and_content_mismatch(self):
        expected = [adapted_item(), adapted_item("inbox_missing", event_name="不足")]
        actual = [
            inbox_item(source_url="https://different.example.com"),
            inbox_item(inbox_id="inbox_extra", event_name="余分"),
        ]

        report = build_parity_report([snapshot(expected)], {"items": actual})
        source = report["sources"][0]

        self.assertFalse(report["summary"]["parity"])
        self.assertEqual(source["missing_in_inbox"], ["inbox_missing"])
        self.assertEqual(source["extra_in_inbox"], ["inbox_extra"])
        self.assertEqual(source["content_mismatches"][0]["inbox_id"], "inbox_one")
        self.assertIn("source_url", source["content_mismatches"][0]["fields"])

    def test_payload_hash_mismatch_is_reported(self):
        report = build_parity_report(
            [snapshot()],
            {"items": [inbox_item(source_payload_hash="b" * 64)]},
        )

        fields = report["sources"][0]["content_mismatches"][0]["fields"]
        self.assertIn("source_payload_hash", fields)

    def test_missing_input_hash_is_rejected(self):
        invalid = snapshot()
        invalid["input_sha256"] = ""

        with self.assertRaisesRegex(ValueError, "invalid input_sha256"):
            build_parity_report([invalid], {"items": []})

    def test_snapshot_and_report_files_preserve_input_lineage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapted_path = root / "adapted.json"
            adapted_path.write_text(json.dumps(snapshot(), ensure_ascii=False), encoding="utf-8")
            adapted = load_adapted_snapshot(adapted_path)
            report = build_parity_report([adapted], {"items": [inbox_item()]})
            out_json = root / "report.json"
            out_md = root / "report.md"
            write_report(report, out_json, out_md)

            saved = json.loads(out_json.read_text(encoding="utf-8"))

        self.assertEqual(len(adapted["adapter_snapshot_sha256"]), 64)
        self.assertEqual(
            saved["sources"][0]["input"]["adapter_snapshot_sha256"],
            adapted["adapter_snapshot_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
