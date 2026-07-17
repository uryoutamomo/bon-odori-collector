import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "promote_change_requests_for_review.py"
SPEC = importlib.util.spec_from_file_location("promote_change_requests_for_review", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PromoteChangeRequestsForReviewTest(unittest.TestCase):
    def sample_payload(self):
        return {
            "request_type": "rdb_change_requests",
            "generated_by": "builder.py",
            "scope": "sample",
            "requests": [
                {
                    "request_id": "r1",
                    "change_type": "add_historical_reference",
                    "occurrence_id": "occ1",
                    "dry_run_only": True,
                    "source": {"url": "https://example.com/1"},
                },
                {
                    "request_id": "r2",
                    "change_type": "add_historical_reference",
                    "occurrence_id": "occ2",
                    "dry_run_only": True,
                    "source": {"url": "https://example.com/2"},
                },
            ],
        }

    def test_promotes_all_by_default_and_preserves_request_ids(self):
        payload, report = MODULE.promote_payload(
            self.sample_payload(),
            reviewed_by="こと（Claude Code）",
            reviewed_at="2026-07-17T00:00:00+09:00",
        )

        self.assertEqual(report["approved_request_count"], 2)
        self.assertEqual([request["request_id"] for request in payload["requests"]], ["r1", "r2"])
        self.assertNotIn("dry_run_only", payload["requests"][0])
        self.assertEqual(payload["requests"][0]["reviewed_by"], "こと（Claude Code）")
        self.assertEqual(payload["requests"][0]["reviewed_at"], "2026-07-17T00:00:00+09:00")
        self.assertEqual(payload["source_generated_by"], "builder.py")

    def test_promotes_only_approved_ids(self):
        payload, report = MODULE.promote_payload(self.sample_payload(), approved_ids=["r2"])

        self.assertEqual(report["approved_request_count"], 1)
        self.assertEqual(payload["requests"][0]["request_id"], "r2")

    def test_refuses_unknown_approved_id(self):
        with self.assertRaisesRegex(ValueError, "not found"):
            MODULE.promote_payload(self.sample_payload(), approved_ids=["missing"])

    def test_refuses_selected_request_without_dry_run_only(self):
        payload = self.sample_payload()
        payload["requests"][0].pop("dry_run_only")

        with self.assertRaisesRegex(ValueError, "not dry_run_only"):
            MODULE.promote_payload(payload, approved_ids=["r1"])

    def test_load_approved_ids_ignores_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ids.txt"
            path.write_text("# note\nr1\n\nr2\n", encoding="utf-8")

            self.assertEqual(MODULE.load_approved_ids(path, ["r3"]), ["r1", "r2", "r3"])


if __name__ == "__main__":
    unittest.main()
