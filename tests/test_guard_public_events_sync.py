import unittest

from guard_public_events_sync import guard_decision


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


if __name__ == "__main__":
    unittest.main()
