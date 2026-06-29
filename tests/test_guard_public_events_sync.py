import unittest
import tempfile
from pathlib import Path

from guard_public_events_sync import append_github_summary, classify_rows, guard_decision


class PublicEventsSyncGuardTest(unittest.TestCase):
    def test_pass_still_requires_separate_public_deploy_approval(self):
        raw = {"summary": {"events_by_action": {}}}
        postprocessed = {
            "summary": {
                "collector_event_count": 1,
                "site_event_count": 1,
                "collector_only_count": 0,
                "site_only_count": 0,
                "events_by_action": {},
            }
        }

        decision = guard_decision(raw, postprocessed, allow_individual_review=False)

        self.assertEqual(decision["status"], "pass")
        self.assertTrue(decision["safe_to_wholesale_sync"])
        self.assertNotIn("safe_to_deploy_without_review", decision)
        self.assertTrue(decision["public_deploy_requires_separate_approval"])

    def test_event_count_mismatch_blocks_wholesale_sync(self):
        raw = {"summary": {"events_by_action": {}}}
        postprocessed = {
            "summary": {
                "collector_event_count": 2,
                "site_event_count": 1,
                "collector_only_count": 1,
                "site_only_count": 0,
                "events_by_action": {},
            }
        }

        decision = guard_decision(raw, postprocessed, allow_individual_review=False)

        self.assertEqual(decision["status"], "block")
        self.assertFalse(decision["safe_to_wholesale_sync"])
        self.assertIn("event_count_mismatch", decision["failures"])
        self.assertIn("event_key_mismatch", decision["failures"])

    def test_append_github_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            markdown = tmp / "guard.md"
            summary = tmp / "summary.md"
            markdown.write_text("# Guard\n\n- status: pass\n", encoding="utf-8")

            result = append_github_summary(markdown, summary)

            self.assertEqual(result, str(summary))
            self.assertIn("status: pass", summary.read_text(encoding="utf-8"))

    def test_expired_historical_slide_downgrade_is_safe_action(self):
        collector_rows = [
            {
                "name": "テスト盆踊り",
                "venue": "テスト公園",
                "historical_display_tier": "historical_reference",
                "historical_reference": {
                    "display_tier": "historical_reference",
                    "label": "2025実績・今年未確認",
                    "confidence": "medium",
                    "score": 0.67,
                },
            }
        ]
        site_rows = [
            {
                "name": "テスト盆踊り",
                "venue": "テスト公園",
                "historical_display_tier": "historical_slide",
                "historical_reference": {
                    "display_tier": "historical_slide",
                    "label": "2025実績・今年未確認",
                    "confidence": "medium",
                    "score": 0.67,
                    "slide": {"date": "2026-06-20"},
                },
            }
        ]

        classified = classify_rows(collector_rows, site_rows)

        self.assertEqual(
            classified["summary"]["events_by_action"],
            {"expired_historical_slide_downgrade": 1},
        )


if __name__ == "__main__":
    unittest.main()
