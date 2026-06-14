import unittest

from plan_retrospective_event_review import build_plan


class PlanRetrospectiveEventReviewTest(unittest.TestCase):
    def test_builds_ready_for_apply_only_from_register_decision(self):
        dry_run = {
            "new_event_candidates": [
                {
                    "candidate_key": "event:1",
                    "display_name": "中央公園盆踊り",
                    "venue": "中央公園",
                    "estimated_date": "2026-07-20",
                    "evidence_urls": ["https://x.com/a/status/1"],
                },
                {
                    "candidate_key": "event:2",
                    "display_name": "文章断片盆踊り",
                    "review_flags": ["sentence_fragment"],
                },
            ]
        }
        decisions = {
            "rows": [
                {"key": "event:1", "decision": "登録", "note": "新規登録OK"},
                {"key": "event:2", "decision": "不採用", "note": "ノイズ"},
            ]
        }

        plan = build_plan(dry_run, decisions, generated_at="now")

        self.assertFalse(plan["apply_performed"])
        self.assertEqual(plan["reviewed_count"], 2)
        self.assertEqual(plan["ready_for_apply_count"], 1)
        self.assertEqual(plan["ready_for_apply"][0]["event_name"], "中央公園盆踊り")
        self.assertEqual(plan["ready_for_apply"][0]["source_url"], "https://x.com/a/status/1")
        self.assertEqual(plan["rows"][1]["status"], "rejected")

    def test_missing_decisions_keeps_rows_undecided(self):
        plan = build_plan({"new_event_candidates": [{"candidate_key": "event:1"}]}, {}, generated_at="now")

        self.assertEqual(plan["reviewed_count"], 0)
        self.assertEqual(plan["ready_for_apply_count"], 0)
        self.assertEqual(plan["rows"][0]["status"], "undecided")


if __name__ == "__main__":
    unittest.main()
