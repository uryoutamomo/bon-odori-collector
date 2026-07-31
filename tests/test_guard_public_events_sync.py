import tempfile
import unittest
import os
from datetime import date
from pathlib import Path

from public_json_postprocessors.guard_public_events_sync import (
    DATA,
    REVIEWED_APPROVALS,
    apply_reviewed_exact_approvals,
    append_github_summary,
    canonical_event_sha256,
    classify_rows,
    flow_artifact_warnings,
    guard_decision,
)


class PublicEventsSyncGuardTest(unittest.TestCase):
    def test_default_data_paths_are_relative_to_the_guard_script(self):
        expected_data = Path(__file__).resolve().parents[1] / "data"

        self.assertEqual(DATA, expected_data)
        self.assertEqual(REVIEWED_APPROVALS, expected_data / "public_sync_exact_approvals.json")

    def test_exact_same_key_approval_only_applies_to_pinned_values(self):
        site = {"name": "テスト盆踊り", "venue": "公園", "display_tier": "confirmed"}
        collector = {"name": "テスト盆踊り", "venue": "公園", "display_tier": "ended"}
        payload = {
            "schema": "public_sync_exact_approvals_v1",
            "approvals": [
                {
                    "id": "review-1",
                    "kind": "same_key_update",
                    "event_key": "テスト盆踊り||公園",
                    "site_sha256": canonical_event_sha256(site),
                    "collector_sha256": canonical_event_sha256(collector),
                }
            ],
        }

        reviewed = apply_reviewed_exact_approvals([collector], [site], payload)

        self.assertEqual(reviewed["summary"]["status"], "pass")
        self.assertEqual(reviewed["summary"]["status_counts"], {"applied": 1})
        self.assertEqual(reviewed["site_rows"], [collector])

        drifted_site = {**site, "status": "unexpected drift"}
        rejected = apply_reviewed_exact_approvals([collector], [drifted_site], payload)
        self.assertEqual(rejected["summary"]["status"], "block")
        self.assertEqual(rejected["summary"]["status_counts"], {"hash_mismatch": 1})
        self.assertEqual(rejected["site_rows"], [drifted_site])

    def test_exact_key_replacement_preserves_event_count_and_resolves_keys(self):
        site = {"name": "第15回 盆踊り", "venue": "大学", "display_tier": "rule_predicted"}
        collector = {"name": "第16回 盆踊り", "venue": "大学", "display_tier": "ended"}
        payload = {
            "schema": "public_sync_exact_approvals_v1",
            "approvals": [
                {
                    "id": "replacement-1",
                    "kind": "key_replacement",
                    "site_event_key": "第15回 盆踊り||大学",
                    "collector_event_key": "第16回 盆踊り||大学",
                    "site_sha256": canonical_event_sha256(site),
                    "collector_sha256": canonical_event_sha256(collector),
                }
            ],
        }

        reviewed = apply_reviewed_exact_approvals([collector], [site], payload)
        classified = classify_rows([collector], reviewed["site_rows"])

        self.assertEqual(reviewed["summary"]["status_counts"], {"applied": 1})
        self.assertEqual(classified["summary"]["collector_event_count"], 1)
        self.assertEqual(classified["summary"]["site_event_count"], 1)
        self.assertEqual(classified["summary"]["collector_only_count"], 0)
        self.assertEqual(classified["summary"]["site_only_count"], 0)

    def test_exact_addition_approval_adds_collector_only_event_at_pinned_hash(self):
        collector_event = {"name": "新規盆踊り", "venue": "商店街", "display_tier": "confirmed"}
        existing = {"name": "既存イベント", "venue": "別会場"}
        payload = {
            "schema": "public_sync_exact_approvals_v1",
            "approvals": [
                {
                    "id": "addition-1",
                    "kind": "addition",
                    "event_key": "新規盆踊り||商店街",
                    "collector_sha256": canonical_event_sha256(collector_event),
                }
            ],
        }

        reviewed = apply_reviewed_exact_approvals(
            [existing, collector_event], [existing], payload
        )
        classified = classify_rows([existing, collector_event], reviewed["site_rows"])

        self.assertEqual(reviewed["summary"]["status_counts"], {"applied": 1})
        self.assertEqual(classified["summary"]["collector_event_count"], 2)
        self.assertEqual(classified["summary"]["site_event_count"], 2)
        self.assertEqual(classified["summary"]["collector_only_count"], 0)
        self.assertEqual(classified["summary"]["site_only_count"], 0)

    def test_exact_addition_approval_rejects_drifted_collector_value(self):
        reviewed_event = {"name": "新規盆踊り", "venue": "商店街", "display_tier": "confirmed"}
        drifted = {**reviewed_event, "date": "2026-08-28"}
        payload = {
            "schema": "public_sync_exact_approvals_v1",
            "approvals": [
                {
                    "id": "addition-1",
                    "kind": "addition",
                    "event_key": "新規盆踊り||商店街",
                    "collector_sha256": canonical_event_sha256(reviewed_event),
                }
            ],
        }

        rejected = apply_reviewed_exact_approvals([drifted], [], payload)

        self.assertEqual(rejected["summary"]["status"], "block")
        self.assertEqual(rejected["summary"]["status_counts"], {"hash_mismatch": 1})
        self.assertEqual(rejected["site_rows"], [])

    def test_exact_addition_approval_is_inactive_once_collector_drops_it(self):
        payload = {
            "schema": "public_sync_exact_approvals_v1",
            "approvals": [
                {
                    "id": "addition-1",
                    "kind": "addition",
                    "event_key": "消えた盆踊り||広場",
                    "collector_sha256": "0" * 64,
                }
            ],
        }

        reviewed = apply_reviewed_exact_approvals([], [], payload)

        self.assertEqual(reviewed["summary"]["status_counts"], {"inactive": 1})
        self.assertEqual(reviewed["summary"]["failure_count"], 0)

    def test_exact_addition_approval_is_already_synced_after_the_site_catches_up(self):
        collector_event = {"name": "新規盆踊り", "venue": "商店街", "display_tier": "confirmed"}
        payload = {
            "schema": "public_sync_exact_approvals_v1",
            "approvals": [
                {
                    "id": "addition-1",
                    "kind": "addition",
                    "event_key": "新規盆踊り||商店街",
                    "collector_sha256": canonical_event_sha256(collector_event),
                }
            ],
        }

        reviewed = apply_reviewed_exact_approvals(
            [collector_event], [dict(collector_event)], payload
        )

        self.assertEqual(reviewed["summary"]["status_counts"], {"already_synced": 1})
        self.assertEqual(reviewed["summary"]["failure_count"], 0)

    def test_exact_addition_approval_is_already_applied_when_site_value_changes(self):
        collector_event = {"name": "新規盆踊り", "venue": "商店街", "public_status": "ended_2026"}
        site_event = {**collector_event, "public_status": "upcoming_confirmed"}
        payload = {"schema": "public_sync_exact_approvals_v1", "approvals": [{"id": "addition-1", "kind": "addition", "event_key": "新規盆踊り||商店街", "collector_sha256": canonical_event_sha256(site_event)}]}
        reviewed = apply_reviewed_exact_approvals([collector_event], [site_event], payload)
        self.assertEqual(reviewed["summary"]["status_counts"], {"already_applied": 1})
        self.assertEqual(reviewed["summary"]["failure_count"], 0)
        self.assertEqual(reviewed["site_rows"], [site_event])

    def test_exact_removal_approval_drops_site_only_event_at_pinned_hash(self):
        site_event = {"name": "旧イベント", "venue": "公園", "public_status": "expected_medium"}
        other_site_event = {"name": "残るイベント", "venue": "別会場"}
        payload = {
            "schema": "public_sync_exact_approvals_v1",
            "approvals": [
                {
                    "id": "removal-1",
                    "kind": "removal",
                    "event_key": "旧イベント||公園",
                    "site_sha256": canonical_event_sha256(site_event),
                }
            ],
        }

        reviewed = apply_reviewed_exact_approvals([], [site_event, other_site_event], payload)
        classified = classify_rows([], reviewed["site_rows"])

        self.assertEqual(reviewed["summary"]["status_counts"], {"applied": 1})
        self.assertEqual(reviewed["site_rows"], [other_site_event])
        self.assertEqual(classified["summary"]["site_only_count"], 1)

    def test_exact_removal_approval_rejects_drifted_site_value(self):
        site_event = {"name": "旧イベント", "venue": "公園", "public_status": "expected_medium"}
        drifted_site_event = {**site_event, "public_status": "unexpected drift"}
        payload = {
            "schema": "public_sync_exact_approvals_v1",
            "approvals": [
                {
                    "id": "removal-1",
                    "kind": "removal",
                    "event_key": "旧イベント||公園",
                    "site_sha256": canonical_event_sha256(site_event),
                }
            ],
        }

        reviewed = apply_reviewed_exact_approvals([], [drifted_site_event], payload)

        self.assertEqual(reviewed["summary"]["status"], "block")
        self.assertEqual(reviewed["summary"]["status_counts"], {"hash_mismatch": 1})
        self.assertEqual(reviewed["site_rows"], [drifted_site_event])

    def test_exact_removal_approval_rejects_if_collector_resurrected_key(self):
        site_event = {"name": "旧イベント", "venue": "公園", "public_status": "expected_medium"}
        resurrected_collector_event = {"name": "旧イベント", "venue": "公園", "public_status": "upcoming_confirmed"}
        payload = {
            "schema": "public_sync_exact_approvals_v1",
            "approvals": [
                {
                    "id": "removal-1",
                    "kind": "removal",
                    "event_key": "旧イベント||公園",
                    "site_sha256": canonical_event_sha256(site_event),
                }
            ],
        }

        reviewed = apply_reviewed_exact_approvals([resurrected_collector_event], [site_event], payload)

        self.assertEqual(reviewed["summary"]["status"], "block")
        self.assertEqual(reviewed["summary"]["status_counts"], {"hash_mismatch": 1})
        self.assertEqual(reviewed["site_rows"], [site_event])

    def test_exact_removal_approval_is_inactive_if_already_gone(self):
        payload = {
            "schema": "public_sync_exact_approvals_v1",
            "approvals": [
                {
                    "id": "removal-1",
                    "kind": "removal",
                    "event_key": "既に消えたイベント||公園",
                    "site_sha256": "whatever",
                }
            ],
        }

        reviewed = apply_reviewed_exact_approvals([], [], payload)

        self.assertEqual(reviewed["summary"]["status"], "pass")
        self.assertEqual(reviewed["summary"]["status_counts"], {"inactive": 1})

    def test_exact_approval_is_already_synced_after_site_catches_up(self):
        event = {"name": "テスト盆踊り", "venue": "公園", "display_tier": "ended"}
        payload = {
            "schema": "public_sync_exact_approvals_v1",
            "approvals": [
                {
                    "id": "review-1",
                    "kind": "same_key_update",
                    "event_key": "テスト盆踊り||公園",
                    "site_sha256": "old-value",
                    "collector_sha256": canonical_event_sha256(event),
                }
            ],
        }

        reviewed = apply_reviewed_exact_approvals([event], [event], payload)

        self.assertEqual(reviewed["summary"]["status"], "pass")
        self.assertEqual(reviewed["summary"]["status_counts"], {"already_synced": 1})

    def test_approval_hash_mismatch_blocks_decision(self):
        raw = {"summary": {"events_by_action": {}}}
        approved = {
            "summary": {
                "collector_event_count": 1,
                "site_event_count": 1,
                "collector_only_count": 0,
                "site_only_count": 0,
                "events_by_action": {},
            }
        }

        decision = guard_decision(
            raw,
            approved,
            allow_individual_review=False,
            approval_summary={"failure_count": 1},
        )

        self.assertEqual(decision["status"], "block")
        self.assertIn("reviewed_exact_approval_mismatch", decision["failures"])

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

    def test_flow_artifact_warnings_when_master_is_newer_than_review_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            master = tmp / "bon_odori_master.sqlite"
            gap = tmp / "publication_gap_review.json"
            public_events = tmp / "events_public.json"
            master.write_text("db", encoding="utf-8")
            gap.write_text("{}", encoding="utf-8")
            public_events.write_text("[]", encoding="utf-8")
            os.utime(gap, (100, 100))
            os.utime(public_events, (100, 100))
            os.utime(master, (200, 200))

            warnings = flow_artifact_warnings(master, gap, public_events)

            self.assertIn("master_rdb_newer_than_publication_gap_review", warnings)
            self.assertIn("master_rdb_newer_than_public_export", warnings)

    def test_flow_artifact_warnings_clear_when_review_outputs_are_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            master = tmp / "bon_odori_master.sqlite"
            gap = tmp / "publication_gap_review.json"
            public_events = tmp / "events_public.json"
            master.write_text("db", encoding="utf-8")
            gap.write_text("{}", encoding="utf-8")
            public_events.write_text("[]", encoding="utf-8")
            os.utime(master, (100, 100))
            os.utime(gap, (200, 200))
            os.utime(public_events, (200, 200))

            warnings = flow_artifact_warnings(master, gap, public_events)

            self.assertEqual(warnings, [])

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

    def test_past_ended_transition_is_automatically_allowed(self):
        site = {
            "name": "完了した盆踊り",
            "venue": "テスト公園",
            "date": "2026-07-28",
            "date_end": "2026-07-29",
            "display_tier": "confirmed",
        }
        collector = {
            **site,
            "display_tier": "ended",
            "public_category": "ended",
            "current_event_state": "ended",
            "time_text": "公式開催概要で17時30分から",
        }

        classified = classify_rows([collector], [site], today=date(2026, 7, 31))

        self.assertEqual(
            classified["summary"]["events_by_action"], {"ended_transition_downgrade": 1}
        )
        self.assertEqual(classified["event_rows"][0]["ended_transition_end_date"], "2026-07-29")

    def test_ended_transition_on_today_still_requires_review(self):
        site = {
            "name": "本日最終日の盆踊り",
            "venue": "テスト公園",
            "date": "2026-07-30",
            "date_end": "2026-07-31",
            "display_tier": "upcoming",
            "historical_display_tier": "upcoming",
        }
        collector = {**site, "display_tier": "ended", "historical_display_tier": "ended"}

        classified = classify_rows([collector], [site], today=date(2026, 7, 31))

        self.assertEqual(classified["event_rows"][0]["recommended_action"], "individual_review")

    def test_reverse_ended_transition_still_requires_review(self):
        collector = {
            "name": "再開した盆踊り",
            "venue": "テスト公園",
            "date": "2026-07-29",
            "date_end": "2026-07-29",
            "display_tier": "upcoming",
            "historical_display_tier": "upcoming",
        }
        site = {**collector, "display_tier": "ended", "historical_display_tier": "ended"}

        classified = classify_rows([collector], [site], today=date(2026, 7, 31))

        self.assertEqual(classified["event_rows"][0]["recommended_action"], "individual_review")

    def test_ended_transition_with_detail_change_still_requires_review(self):
        site = {
            "name": "詳細も変わった盆踊り",
            "venue": "テスト公園",
            "date": "2026-07-29",
            "date_end": "2026-07-29",
            "detail": "旧詳細",
            "display_tier": "upcoming",
            "historical_display_tier": "upcoming",
        }
        collector = {
            **site,
            "detail": "新詳細",
            "display_tier": "ended",
            "historical_display_tier": "ended",
        }

        classified = classify_rows([collector], [site], today=date(2026, 7, 31))

        self.assertEqual(classified["event_rows"][0]["recommended_action"], "individual_review")

    def test_ended_transition_with_date_change_still_requires_review(self):
        site = {
            "name": "日付も変わった盆踊り",
            "venue": "テスト公園",
            "date": "2026-07-28",
            "date_end": "2026-07-28",
            "display_tier": "upcoming",
            "historical_display_tier": "upcoming",
        }
        collector = {
            **site,
            "date": "2026-07-29",
            "date_end": "2026-07-29",
            "display_tier": "ended",
            "historical_display_tier": "ended",
        }

        classified = classify_rows([collector], [site], today=date(2026, 7, 31))

        self.assertEqual(classified["event_rows"][0]["recommended_action"], "individual_review")

    def test_ended_transition_requires_ended_public_category_when_present(self):
        site = {
            "name": "公開区分が不整合な盆踊り",
            "venue": "テスト公園",
            "date": "2026-07-29",
            "date_end": "2026-07-29",
            "display_tier": "confirmed",
            "public_category": "upcoming",
        }
        collector = {**site, "display_tier": "ended"}

        classified = classify_rows([collector], [site], today=date(2026, 7, 31))

        self.assertEqual(classified["event_rows"][0]["recommended_action"], "individual_review")


if __name__ == "__main__":
    unittest.main()
