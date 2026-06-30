import unittest

from guard_site_public_event_additions import classify_addition_diff, guard_decision
from sync_public_event_additions_to_site import build_site_events, selected_collector_events


class PublicEventSiteAdditionToolsTest(unittest.TestCase):
    def test_selected_collector_events_requires_exactly_one_match(self):
        events = [
            {"name": "追加盆踊り", "venue": "公園"},
            {"name": "重複盆踊り", "venue": "A"},
            {"name": "重複盆踊り", "venue": "B"},
        ]

        selected, missing, ambiguous = selected_collector_events(
            events,
            ["追加盆踊り", "未発見盆踊り", "重複盆踊り"],
        )

        self.assertEqual(selected, [{"name": "追加盆踊り", "venue": "公園"}])
        self.assertEqual(missing, ["未発見盆踊り"])
        self.assertEqual(ambiguous, ["重複盆踊り"])

    def test_build_site_events_preserves_existing_and_appends_selected(self):
        base = [
            {"name": "既存盆踊り", "venue": "広場", "date": "2026-07-01"},
            {"name": "更新対象", "venue": "旧会場", "date": "2026-07-02"},
        ]
        additions = [
            {"name": "更新対象", "venue": "新会場", "date": "2026-07-03"},
            {"name": "追加盆踊り", "venue": "公園", "date": "2026-08-01"},
        ]

        result = build_site_events(base, additions)

        self.assertEqual(
            result,
            [
                {"name": "既存盆踊り", "venue": "広場", "date": "2026-07-01"},
                {"name": "更新対象", "venue": "新会場", "date": "2026-07-03"},
                {"name": "追加盆踊り", "venue": "公園", "date": "2026-08-01"},
            ],
        )

    def test_addition_only_diff_passes_with_expected_names(self):
        base = [{"name": "既存盆踊り", "venue": "広場", "date": "2026-07-01"}]
        current = [
            {"name": "既存盆踊り", "venue": "広場", "date": "2026-07-01"},
            {"name": "追加盆踊り", "venue": "公園", "date": "2026-08-01"},
        ]

        diff = classify_addition_diff(base, current)
        decision = guard_decision(diff, ["追加盆踊り"])

        self.assertEqual(decision["status"], "pass")
        self.assertEqual([event["name"] for event in diff["added"]], ["追加盆踊り"])

    def test_existing_event_field_modification_blocks(self):
        base = [{"name": "既存盆踊り", "venue": "広場", "date": "2026-07-01", "description": "before"}]
        current = [{"name": "既存盆踊り", "venue": "広場", "date": "2026-07-01", "description": "after"}]

        diff = classify_addition_diff(base, current)
        decision = guard_decision(diff, [])

        self.assertEqual(decision["status"], "block")
        self.assertIn("modified_existing_public_events", decision["failures"])

    def test_existing_event_date_change_blocks_as_removal(self):
        base = [{"name": "既存盆踊り", "venue": "広場", "date": "2026-07-01"}]
        current = [{"name": "既存盆踊り", "venue": "広場", "date": "2026-07-02"}]

        diff = classify_addition_diff(base, current)
        decision = guard_decision(diff, [])

        self.assertEqual(decision["status"], "block")
        self.assertIn("removed_existing_public_events", decision["failures"])

    def test_expected_name_mismatch_blocks(self):
        base = [{"name": "既存盆踊り", "venue": "広場"}]
        current = [
            {"name": "既存盆踊り", "venue": "広場"},
            {"name": "別の盆踊り", "venue": "公園"},
        ]

        diff = classify_addition_diff(base, current)
        decision = guard_decision(diff, ["追加盆踊り"])

        self.assertEqual(decision["status"], "block")
        self.assertIn("added_events_do_not_match_expected_names", decision["failures"])


if __name__ == "__main__":
    unittest.main()
