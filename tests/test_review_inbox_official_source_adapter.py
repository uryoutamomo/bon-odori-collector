import json
import tempfile
import unittest
from pathlib import Path

from review_inbox_official_source_adapter import OfficialSourceAdapter, row_event_year
from review_inbox_source_adapter import load_adapted_source, write_adapted_snapshot


def row(**overrides):
    value = {
        "id": "official-1",
        "decision": "hold",
        "suggested_source_type": "official",
        "suggested_score": 85,
        "reason": "自治体・公的ドメイン",
        "source_url": "https://www.city.example.jp/notice.pdf",
        "source_domain": "www.city.example.jp",
        "venue": "行幸通り",
        "event_name": "丸の内de盆踊り",
        "region": "千代田区",
        "event_date_text": "2026 7/24",
    }
    value.update(overrides)
    return value


class OfficialSourceAdapterTest(unittest.TestCase):
    def test_future_candidate_keeps_legacy_decision_only_in_payload(self):
        item = list(OfficialSourceAdapter().adapt({"rows": [row()]}))[0]

        self.assertEqual(item["time_scope"], "future")
        self.assertEqual(item["event_year"], 2026)
        self.assertEqual(item["source_key"], "official-1")
        self.assertEqual(item["payload"]["decision"], "hold")
        self.assertNotIn("decision", {key: value for key, value in item.items() if key != "payload"})

    def test_past_candidate_is_historical_not_future(self):
        item = list(
            OfficialSourceAdapter().adapt(
                {"rows": [row(event_date_text="2025 [L16] 7/26", event_name="親子盆踊り")]}
            )
        )[0]

        self.assertEqual(item["time_scope"], "historical")
        self.assertEqual(item["priority_label"], "P2")
        self.assertEqual(item["event_year"], 2025)

    def test_year_prefers_explicit_then_parses_date_text(self):
        self.assertEqual(row_event_year(row(event_year="2024", event_date_text="2025 7/1")), 2024)
        self.assertEqual(row_event_year(row(event_year="", event_date_text="2024実績 / 2025実績")), 2025)

    def test_missing_id_uses_stable_legacy_composite(self):
        item = list(OfficialSourceAdapter().adapt({"rows": [row(id="")]}))[0]

        self.assertEqual(
            item["source_key"],
            "https://www.city.example.jp/notice.pdf|行幸通り|丸の内de盆踊り",
        )

    def test_real_loader_and_atomic_snapshot_keep_input_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "official.json"
            output = root / "adapted.json"
            source.write_text(
                json.dumps({"rows": [row()]}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            snapshot = load_adapted_source(OfficialSourceAdapter(), source)
            write_adapted_snapshot(snapshot, output)
            saved = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(saved["item_count"], 1)
        self.assertEqual(saved["input_sha256"], snapshot["input_sha256"])
        self.assertEqual(saved["items"][0]["source_id"], "official_source")


if __name__ == "__main__":
    unittest.main()
