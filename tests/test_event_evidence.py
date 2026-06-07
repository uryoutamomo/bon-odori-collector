import unittest
import json
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import patch

import collect
from event_evidence import (
    build_history_query,
    build_initial_window,
    classify_event_evidence,
    evidence_identity,
)


class EventEvidenceTest(unittest.TestCase):
    def test_classifies_patterns_and_explainable_score(self):
        evidence = classify_event_evidence({
            "account": "@odorer",
            "date": "2025-06-10T10:00:00+00:00",
            "tweet_id": "12345",
            "url": "https://x.com/odorer/status/12345",
            "text": "今年も中央区の浜町公園盆踊りへ一緒に行こう。6月20日開催！",
        })

        self.assertEqual(evidence["identity"], "evidence:12345")
        self.assertIn("A", evidence["patterns"])
        self.assertIn("D", evidence["patterns"])
        self.assertGreaterEqual(evidence["score"], 8)
        self.assertEqual(evidence["estimated_venue"], "浜町公園")
        self.assertTrue(evidence["related_key"])

    def test_keeps_weak_fragment_but_scores_weak_context_down(self):
        evidence = classify_event_evidence({
            "account": "@someone",
            "date": "2025-06-10T10:00:00+00:00",
            "url": "https://x.com/someone/status/99",
            "text": "来週一緒に行かない？",
        })

        self.assertIsNotNone(evidence)
        self.assertIn("D", evidence["patterns"])
        self.assertIn("weak_bon_context:-3", evidence["score_reasons"])

    def test_ignores_post_without_a_to_e_pattern(self):
        self.assertIsNone(classify_event_evidence({
            "text": "盆踊りの写真です",
            "url": "https://x.com/example/status/1",
        }))

    def test_identity_falls_back_to_url_hash(self):
        first = evidence_identity({"url": "https://example.com/a", "text": "x"})
        second = evidence_identity({"url": "https://example.com/a", "text": "x"})
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("evidence:sha256:"))

    def test_initial_window_is_previous_year_and_fourteen_days(self):
        start, end = build_initial_window(
            datetime(2026, 6, 7, 12, tzinfo=timezone.utc), days=14
        )
        self.assertEqual(start.isoformat(), "2025-06-07T00:00:00+00:00")
        self.assertEqual((end - start).days, 14)

    def test_history_query_has_unfiltered_accounts_and_half_open_window(self):
        start = datetime(2025, 6, 7, tzinfo=timezone.utc)
        end = datetime(2025, 6, 21, tzinfo=timezone.utc)
        query = build_history_query(["@a", "b"], start, end)
        self.assertIn("(from:a OR from:b)", query)
        self.assertIn("since:2025-06-07_00:00:00_UTC", query)
        self.assertIn("until:2025-06-21_00:00:00_UTC", query)
        self.assertNotIn("盆踊り", query)

    def test_account_threshold_includes_minus_point_six_and_manual_priority(self):
        accounts = [
            {"handle": "@included", "manual_status": ""},
            {"handle": "@excluded", "manual_status": ""},
            {"handle": "@priority", "manual_status": "優先"},
            {"handle": "@paused", "manual_status": "休止"},
        ]
        scores = {
            "accounts": {
                "included": {"score": -0.6},
                "excluded": {"score": -0.7},
                "priority": {"score": -10},
                "paused": {"score": 20},
            }
        }
        with patch.object(collect, "_load_x_account_scores", return_value=scores):
            selected = collect._event_evidence_accounts(
                accounts, {"event_evidence": {
                    "min_account_score": -0.6,
                    "cohort_file": "/missing/cohort.json",
                }}
            )
        self.assertEqual(selected, ["@included", "@priority"])

    def test_frozen_cohort_is_used_exactly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "cohort.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({
                    "expected_count": 2,
                    "handles": ["@b", "@a"],
                }, f)
            selected = collect._event_evidence_accounts([], {
                "event_evidence": {"cohort_file": path}
            })
        self.assertEqual(selected, ["@a", "@b"])

    def test_clears_pending_only_after_queue_delivery(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "state.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({
                    "status": "in_progress",
                    "pending_evidence": [{"identity": "evidence:1"}],
                }, f)
            with patch.object(collect, "X_EVENT_EVIDENCE_STATE_FILE", path):
                collect._clear_pending_event_evidence()
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
        self.assertEqual(state["pending_evidence"], [])
        self.assertIn("pending_cleared_at", state)


if __name__ == "__main__":
    unittest.main()
