import copy
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from legacy.public_projection.apply_public_historical_references import (
    apply_historical_references as legacy_apply_historical_references,
)
from legacy.public_projection.apply_public_season_hints import (
    apply_season_hints as legacy_apply_season_hints,
)
from public_json_postprocessors.apply_public_display_tiers import apply_display_tiers
from public_json_postprocessors.guard_public_events_sync import (
    DATA,
    REVIEWED_APPROVALS,
    apply_reviewed_exact_approvals,
    append_github_summary,
    build,
    canonical_event_sha256,
    classify_rows,
    flow_artifact_warnings,
    guard_decision,
)


class PublicEventsSyncGuardTest(unittest.TestCase):
    def run_build(self, collector_rows, site_rows, approvals, *, today="2026-07-31",
                  approval_schema="public_sync_exact_approvals_v1"):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            collector_events = tmp / "collector.json"
            site_events = tmp / "site.json"
            fixed_date_rules = tmp / "fixed-date-rules.json"
            reviewed_approvals = tmp / "approvals.json"
            collector_events.write_text(
                json.dumps(collector_rows, ensure_ascii=False), encoding="utf-8"
            )
            site_events.write_text(
                json.dumps(site_rows, ensure_ascii=False), encoding="utf-8"
            )
            fixed_date_rules.write_text('{"rules": []}', encoding="utf-8")
            reviewed_approvals.write_text(
                json.dumps(
                    {
                        "schema": approval_schema,
                        "approvals": approvals,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            return build(
                SimpleNamespace(
                    collector_events=collector_events,
                    site_events=site_events,
                    fixed_date_rules=fixed_date_rules,
                    reviewed_approvals=reviewed_approvals,
                    target_year=2026,
                    today=today,
                    allow_individual_review=False,
                    master_db=tmp / "missing-master.sqlite",
                    publication_gap_review=tmp / "missing-gap-review.json",
                    out_json=tmp / "guard.json",
                    out_md=tmp / "guard.md",
                )
            )

    def same_key_approval(self, reviewed_site, reviewed_collector):
        return {
            "id": "review-1",
            "kind": "same_key_update",
            "event_key": f"{reviewed_site['name']}||{reviewed_site['venue']}",
            "site_sha256": canonical_event_sha256(reviewed_site),
            "collector_sha256": canonical_event_sha256(reviewed_collector),
        }

    def key_replacement_approval(self, reviewed_site, reviewed_collector):
        return {
            "id": "replacement-1",
            "kind": "key_replacement",
            "site_event_key": f"{reviewed_site['name']}||{reviewed_site['venue']}",
            "collector_event_key": (
                f"{reviewed_collector['name']}||{reviewed_collector['venue']}"
            ),
            "site_sha256": canonical_event_sha256(reviewed_site),
            "collector_sha256": canonical_event_sha256(reviewed_collector),
        }

    def published_event(self):
        return {
            "name": "承認済み盆踊り",
            "venue": "確認公園",
            "date": "2026-07-28",
            "date_end": "2026-07-29",
            "public_category": "upcoming",
            "display_tier": "confirmed",
            "current_event_state": "confirmed",
            "date_certainty_tier": "confirmed",
        }

    def legacy_postprocessed_rows(self, rows, *, target_year, today):
        """Reproduce the removed guard repair path only to construct fixtures."""
        repaired = copy.deepcopy(rows)
        repaired = legacy_apply_historical_references(
            repaired,
            target_year=target_year,
            today=date.fromisoformat(today),
            fixed_date_rules={},
        )["events"]
        repaired = apply_display_tiers(repaired, target_year=target_year)
        repaired = legacy_apply_season_hints(
            repaired, target_year=target_year
        )["events"]
        return apply_display_tiers(repaired, target_year=target_year)

    def assert_removed_repair_would_have_passed(self, raw_rows, site_rows, *, today):
        repaired_rows = self.legacy_postprocessed_rows(
            raw_rows, target_year=2026, today=today
        )
        self.assertEqual(repaired_rows, site_rows)
        repaired_classification = classify_rows(
            repaired_rows, site_rows, today=date.fromisoformat(today)
        )
        legacy_decision = guard_decision(
            {"summary": {}}, repaired_classification, allow_individual_review=False
        )
        self.assertEqual(legacy_decision["status"], "pass")

    def consumed_same_key_approval(self, published_event):
        reviewed_site = {**published_event, "detail": "承認前の値"}
        return self.same_key_approval(reviewed_site, published_event)

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

    def test_same_key_approval_is_consumed_when_approved_value_is_already_on_site(self):
        published = self.published_event()
        collector = {
            **published,
            "public_category": "ended",
            "display_tier": "ended",
            "current_event_state": "ended",
        }
        payload = {
            "schema": "public_sync_exact_approvals_v1",
            "approvals": [self.consumed_same_key_approval(published)],
        }

        reviewed = apply_reviewed_exact_approvals([collector], [published], payload)

        self.assertEqual(reviewed["summary"]["status"], "pass")
        self.assertEqual(
            reviewed["summary"]["status_counts"], {"consumed_at_site": 1}
        )
        self.assertEqual(reviewed["summary"]["failure_count"], 0)
        self.assertEqual(reviewed["site_rows"], [published])

    def test_same_key_approval_rejects_an_unrecognized_third_site_value(self):
        published = self.published_event()
        collector = {**published, "date_end": "2026-07-30"}
        third_site_value = {**published, "detail": "承認後の別変更"}
        payload = {
            "schema": "public_sync_exact_approvals_v1",
            "approvals": [self.consumed_same_key_approval(published)],
        }

        reviewed = apply_reviewed_exact_approvals(
            [collector], [third_site_value], payload
        )

        self.assertEqual(reviewed["summary"]["status"], "block")
        self.assertEqual(reviewed["summary"]["status_counts"], {"hash_mismatch": 1})
        self.assertEqual(reviewed["site_rows"], [third_site_value])

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

    def test_key_replacement_approval_is_consumed_when_renamed_value_is_already_on_site(self):
        old_site = {"name": "第15回 盆踊り", "venue": "大学", "display_tier": "confirmed"}
        published = {"name": "盆踊り", "venue": "大学", "display_tier": "confirmed"}
        collector = {**published, "display_tier": "ended"}
        payload = {
            "schema": "public_sync_exact_approvals_v1",
            "approvals": [
                {
                    "id": "replacement-1",
                    "kind": "key_replacement",
                    "site_event_key": "第15回 盆踊り||大学",
                    "collector_event_key": "盆踊り||大学",
                    "site_sha256": canonical_event_sha256(old_site),
                    "collector_sha256": canonical_event_sha256(published),
                }
            ],
        }

        reviewed = apply_reviewed_exact_approvals([collector], [published], payload)

        self.assertEqual(reviewed["summary"]["status"], "pass")
        self.assertEqual(reviewed["summary"]["status_counts"], {"consumed_at_site": 1})
        self.assertEqual(reviewed["site_rows"], [published])

    def test_key_replacement_consumed_path_rejects_when_old_key_still_exists(self):
        old_site = {"name": "第15回 盆踊り", "venue": "大学", "display_tier": "confirmed"}
        published = {"name": "盆踊り", "venue": "大学", "display_tier": "confirmed"}
        collector = {**published, "display_tier": "ended"}
        payload = {
            "schema": "public_sync_exact_approvals_v1",
            "approvals": [
                {
                    "id": "replacement-1",
                    "kind": "key_replacement",
                    "site_event_key": "第15回 盆踊り||大学",
                    "collector_event_key": "盆踊り||大学",
                    "site_sha256": canonical_event_sha256(old_site),
                    "collector_sha256": canonical_event_sha256(published),
                }
            ],
        }

        reviewed = apply_reviewed_exact_approvals([collector], [old_site, published], payload)

        self.assertEqual(reviewed["summary"]["status"], "block")
        self.assertEqual(reviewed["summary"]["status_counts"], {"hash_mismatch": 1})

    def test_key_replacement_is_superseded_by_proven_same_key_successor(self):
        old_site = {"name": "第15回 盆踊り", "venue": "大学", "detail": "旧名"}
        renamed = {"name": "盆踊り", "venue": "大学", "detail": "改名時"}
        published = {**renamed, "detail": "後続の承認値"}
        collector = {**published, "display_tier": "ended"}
        replacement = self.key_replacement_approval(old_site, renamed)
        successor = self.same_key_approval(renamed, published)
        successor["id"] = "review-2"
        payload = {
            "schema": "public_sync_exact_approvals_v1",
            "approvals": [replacement, successor],
        }

        reviewed = apply_reviewed_exact_approvals([collector], [published], payload)

        self.assertEqual(reviewed["summary"]["status"], "pass")
        self.assertEqual(
            reviewed["summary"]["status_counts"],
            {"superseded": 1, "consumed_at_site": 1},
        )
        self.assertEqual(
            reviewed["summary"]["results"][0]["superseded_by"], "review-2"
        )

    def test_key_replacement_is_not_superseded_without_exact_successor_hash(self):
        old_site = {"name": "第15回 盆踊り", "venue": "大学", "detail": "旧名"}
        renamed = {"name": "盆踊り", "venue": "大学", "detail": "改名時"}
        unrelated_start = {**renamed, "detail": "別の出発値"}
        published = {**renamed, "detail": "後続の承認値"}
        collector = {**published, "display_tier": "ended"}
        replacement = self.key_replacement_approval(old_site, renamed)
        successor = self.same_key_approval(unrelated_start, published)
        successor["id"] = "review-2"
        payload = {
            "schema": "public_sync_exact_approvals_v1",
            "approvals": [replacement, successor],
        }

        reviewed = apply_reviewed_exact_approvals([collector], [published], payload)

        self.assertEqual(reviewed["summary"]["status"], "block")
        self.assertEqual(
            reviewed["summary"]["status_counts"],
            {"hash_mismatch": 1, "consumed_at_site": 1},
        )
        self.assertNotIn("superseded_by", reviewed["summary"]["results"][0])

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

    def test_low_risk_summary_alone_cannot_waive_approval_failures(self):
        raw = {
            "summary": {
                "collector_event_count": 1,
                "site_event_count": 1,
                "collector_only_count": 0,
                "site_only_count": 0,
                "high_risk_diff_record_count": 0,
                "events_by_action": {},
            }
        }
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

        forged = guard_decision(
            raw, approved, allow_individual_review=False,
            approval_summary={"failure_count": 1, "song_only_warnings": [{}]},
        )
        self.assertEqual(forged["status"], "block")

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

    def test_build_blocks_raw_recurring_historical_fields_that_legacy_repair_would_match(self):
        today = "2026-06-17"
        collector = {
            "name": "過去実績のみの盆踊り",
            "venue": "確認公園",
            "date": "2025-08-08",
            "date_end": "2025-08-09",
            "public_category": "recurring_last_year",
            "public_status": "expected_medium",
            "recurrence_score": 0.67,
            "last_seen_year": 2025,
            "last_seen_dates": ["2025-08-08", "2025-08-09"],
        }
        site = self.legacy_postprocessed_rows([collector], target_year=2026, today=today)[0]
        self.assertNotIn("historical_reference", collector)
        self.assertIn("historical_reference", site)
        inputs = ([collector], [site], [])
        original = copy.deepcopy(inputs)

        self.assert_removed_repair_would_have_passed(*inputs[:2], today=today)
        result = self.run_build(*inputs, today=today)

        self.assertEqual(inputs, original)
        self.assertEqual(result["decision"]["status"], "block")
        self.assertIn(
            "collector_restore_candidates_remain", result["decision"]["failures"]
        )
        self.assertEqual(
            result["raw_classification"], result["postprocessed_classification"]
        )
        self.assertTrue(result["postprocessed_classification_deprecated"])
        self.assertTrue(result["parameters"]["deprecated_fixed_date_rules_ignored"])
        self.assertEqual(result["raw_classification"]["events_by_action"], {
            "restore_collector_from_site_or_reenable_export_postprocess": 1,
        })

    def test_build_blocks_raw_date_unknown_season_fields_that_legacy_repair_would_match(self):
        today = "2026-06-17"
        collector = {
            "name": "月だけ分かる盆踊り",
            "venue": "確認広場",
            "public_category": "date_unknown",
            "months": [7, 8],
            "jun": {"7": "下旬", "8": "上旬"},
            "hints": [[7, 3], [8, 1]],
        }
        site = self.legacy_postprocessed_rows([collector], target_year=2026, today=today)[0]
        self.assertNotIn("season_hint", collector)
        self.assertIn("season_hint", site)
        inputs = ([collector], [site], [])
        original = copy.deepcopy(inputs)

        self.assert_removed_repair_would_have_passed(*inputs[:2], today=today)
        result = self.run_build(*inputs, today=today)

        self.assertEqual(inputs, original)
        self.assertEqual(result["decision"]["status"], "block")
        self.assertIn(
            "collector_restore_candidates_remain", result["decision"]["failures"]
        )
        self.assertEqual(result["raw_classification"]["events_by_action"], {
            "restore_collector_from_site_or_reenable_export_postprocess": 1,
        })

    def test_other_safe_ended_transition_cannot_rescue_raw_missing_projection_fields(self):
        missing_collector = self.published_event()
        missing_site = {
            **missing_collector,
            "historical_reference": {"label": "2025実績・今年未確認"},
            "historical_display_tier": "historical_reference",
            "season_hint": "7月下旬",
        }
        ended_site = {**self.published_event(), "name": "終了済みの別イベント"}
        ended_collector = {
            **ended_site,
            "public_category": "ended",
            "display_tier": "ended",
            "current_event_state": "ended",
        }
        inputs = ([missing_collector, ended_collector], [missing_site, ended_site], [])
        original = copy.deepcopy(inputs)

        result = self.run_build(*inputs)

        self.assertEqual(inputs, original)
        self.assertEqual(result["decision"]["status"], "block")
        self.assertIn(
            "collector_restore_candidates_remain", result["decision"]["failures"]
        )
        self.assertEqual(result["ended_transition_downgrades"], [{
            "event_name": "終了済みの別イベント",
            "venue": "確認公園",
            "ended_on": "2026-07-29",
        }])

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

    def test_ended_transition_allows_only_non_decreasing_recurrence_update(self):
        site = {
            "name": "完了した盆踊り",
            "venue": "テスト公園",
            "date": "2026-07-28",
            "date_end": "2026-07-29",
            "display_tier": "confirmed",
            "public_category": "upcoming",
            "recurrence_score": 0.95,
            "recurrence_reasons": ["2026年日付確認済み"],
        }
        collector = {
            **site,
            "display_tier": "ended",
            "public_category": "ended",
            "recurrence_score": 0.98,
            "recurrence_reasons": ["2026年開催済み"],
        }

        classified = classify_rows([collector], [site], today=date(2026, 7, 31))

        self.assertEqual(classified["event_rows"][0]["recommended_action"], "ended_transition_downgrade")

        downgraded = {**collector, "recurrence_score": 0.90}
        rejected = classify_rows([downgraded], [site], today=date(2026, 7, 31))
        self.assertEqual(rejected["event_rows"][0]["recommended_action"], "individual_review")

    def test_build_allows_consumed_approval_to_flow_into_ended_transition(self):
        published = self.published_event()
        collector = {
            **published,
            "public_category": "ended",
            "display_tier": "ended",
            "current_event_state": "ended",
        }

        result = self.run_build(
            [collector],
            [published],
            [self.consumed_same_key_approval(published)],
        )

        self.assertEqual(result["decision"]["status"], "pass")
        self.assertEqual(
            result["reviewed_exact_approvals"]["status_counts"],
            {"consumed_at_site": 1},
        )
        self.assertEqual(
            result["approved_classification"]["events_by_action"],
            {"ended_transition_downgrade": 1},
        )
        self.assertEqual(result["ended_transition_downgrades"][0]["ended_on"], "2026-07-29")
        self.assertEqual(result["blocking_examples"], [])

    def test_build_allows_superseded_approval_chain_to_flow_into_ended_transition(self):
        published = self.published_event()
        original = {**published, "detail": "最初の公開値"}
        intermediate = {**published, "detail": "次の承認値"}
        collector = {
            **published,
            "public_category": "ended",
            "display_tier": "ended",
            "current_event_state": "ended",
        }
        first = self.same_key_approval(original, intermediate)
        second = self.same_key_approval(intermediate, published)
        second["id"] = "review-2"

        result = self.run_build([collector], [published], [first, second])

        self.assertEqual(result["decision"]["status"], "pass")
        self.assertEqual(
            result["reviewed_exact_approvals"]["status_counts"],
            {"superseded": 1, "consumed_at_site": 1},
        )
        approval_results = result["reviewed_exact_approvals"]["results"]
        self.assertEqual(approval_results[0]["superseded_by"], "review-2")
        self.assertEqual(
            result["approved_classification"]["events_by_action"],
            {"ended_transition_downgrade": 1},
        )

    def test_stale_approval_chain_is_retired_when_only_current_diff_is_ended_transition(
        self,
    ):
        published = self.published_event()
        old_name = {**published, "name": "承認済み盆踊り 旧称", "detail": "改名前"}
        intermediate = {**published, "detail": "改名承認値"}
        parallel_predecessor = {**published, "detail": "別の承認前値"}
        reviewed = {**published, "detail": "最新の承認値"}
        current_site = {
            **reviewed,
            "songs": [{"name": "東京音頭", "probability": 95}],
        }
        collector = {
            **current_site,
            "public_category": "ended",
            "display_tier": "ended",
            "current_event_state": "ended",
        }
        replacement = self.key_replacement_approval(old_name, intermediate)
        duplicate_arrival = self.same_key_approval(parallel_predecessor, intermediate)
        duplicate_arrival["id"] = "review-2"
        latest = self.same_key_approval(intermediate, reviewed)
        latest["id"] = "review-3"

        result = self.run_build(
            [collector],
            [current_site],
            [replacement, duplicate_arrival, latest],
        )

        self.assertEqual(result["decision"]["status"], "pass")
        self.assertNotIn(
            "reviewed_exact_approval_mismatch", result["decision"]["failures"]
        )
        self.assertEqual(
            result["reviewed_exact_approvals"]["status_counts"],
            {"superseded": 2, "retired_after_ended_transition": 1},
        )
        approval_results = result["reviewed_exact_approvals"]["results"]
        self.assertEqual(approval_results[0]["superseded_by"], "review-3")
        self.assertEqual(approval_results[1]["superseded_by"], "review-3")
        self.assertEqual(
            approval_results[2]["retired_by"], "ended_transition_downgrade"
        )
        self.assertEqual(
            result["approved_classification"]["events_by_action"],
            {"ended_transition_downgrade": 1},
        )

    def test_stale_approval_chain_still_blocks_when_ended_transition_has_detail_drift(
        self,
    ):
        published = self.published_event()
        old_name = {**published, "name": "承認済み盆踊り 旧称", "detail": "改名前"}
        intermediate = {**published, "detail": "改名承認値"}
        reviewed = {**published, "detail": "最新の承認値"}
        current_site = {
            **reviewed,
            "songs": [{"name": "東京音頭", "probability": 95}],
        }
        collector = {
            **current_site,
            "detail": "未承認の詳細",
            "public_category": "ended",
            "display_tier": "ended",
            "current_event_state": "ended",
        }
        replacement = self.key_replacement_approval(old_name, intermediate)
        latest = self.same_key_approval(intermediate, reviewed)
        latest["id"] = "review-2"

        result = self.run_build(
            [collector], [current_site], [replacement, latest]
        )

        self.assertEqual(result["decision"]["status"], "block")
        self.assertIn(
            "reviewed_exact_approval_mismatch", result["decision"]["failures"]
        )
        self.assertIn(
            "individual_review_diffs_remain", result["decision"]["failures"]
        )
        self.assertEqual(
            result["reviewed_exact_approvals"]["status_counts"],
            {"hash_mismatch": 2},
        )

    def test_superseded_approval_chain_does_not_hide_current_detail_drift(self):
        published = self.published_event()
        original = {**published, "detail": "最初の公開値"}
        intermediate = {**published, "detail": "次の承認値"}
        collector = {
            **published,
            "detail": "未承認の変更",
            "public_category": "ended",
            "display_tier": "ended",
            "current_event_state": "ended",
        }
        first = self.same_key_approval(original, intermediate)
        second = self.same_key_approval(intermediate, published)
        second["id"] = "review-2"

        result = self.run_build([collector], [published], [first, second])

        self.assertEqual(result["decision"]["status"], "block")
        self.assertNotIn(
            "reviewed_exact_approval_mismatch", result["decision"]["failures"]
        )
        self.assertIn("individual_review_diffs_remain", result["decision"]["failures"])
        self.assertEqual(
            result["approved_classification"]["events_by_action"],
            {"individual_review": 1},
        )

    def test_build_allows_same_recurrence_score_bucket_after_consumed_approval(self):
        published = {**self.published_event(), "recurrence_score": 0.76}
        collector = {**published, "recurrence_score": 0.78}

        result = self.run_build(
            [collector],
            [published],
            [self.consumed_same_key_approval(published)],
        )

        self.assertEqual(result["decision"]["status"], "pass")
        self.assertEqual(
            result["reviewed_exact_approvals"]["status_counts"],
            {"consumed_at_site": 1},
        )
        self.assertEqual(
            result["approved_classification"]["events_by_action"],
            {"low_priority_or_unclassified": 1},
        )

    def test_build_blocks_recurrence_score_bucket_crossing_after_consumed_approval(self):
        published = {**self.published_event(), "recurrence_score": 0.76}
        collector = {**published, "recurrence_score": 0.80}

        result = self.run_build(
            [collector],
            [published],
            [self.consumed_same_key_approval(published)],
        )

        self.assertEqual(result["decision"]["status"], "block")
        self.assertIn("individual_review_diffs_remain", result["decision"]["failures"])
        self.assertEqual(
            result["approved_classification"]["events_by_action"],
            {"individual_review": 1},
        )

    def test_build_blocks_date_or_date_end_drift_after_consumed_approval(self):
        published = self.published_event()
        cases = {
            "date": {**published, "date": "2026-07-29"},
            "date_end": {**published, "date_end": "2026-07-30"},
        }

        for field, collector in cases.items():
            with self.subTest(field=field):
                result = self.run_build(
                    [collector],
                    [published],
                    [self.consumed_same_key_approval(published)],
                )

                self.assertEqual(result["decision"]["status"], "block")
                self.assertIn(
                    "individual_review_diffs_remain", result["decision"]["failures"]
                )
                self.assertEqual(
                    result["approved_classification"]["events_by_action"],
                    {"individual_review": 1},
                )

    def test_build_blocks_detail_and_source_drift_after_consumed_approval(self):
        published = {
            **self.published_event(),
            "detail": "承認済み詳細",
            "source_urls": [{"url": "https://example.com/reviewed"}],
        }
        collector = {
            **published,
            "detail": "未承認の詳細",
            "source_urls": [{"url": "https://example.com/drifted"}],
        }

        result = self.run_build(
            [collector],
            [published],
            [self.consumed_same_key_approval(published)],
        )

        self.assertEqual(result["decision"]["status"], "block")
        self.assertIn("individual_review_diffs_remain", result["decision"]["failures"])
        blocking = result["blocking_examples"][0]
        self.assertEqual(blocking["recommended_action"], "individual_review")
        self.assertEqual(set(blocking["families"]), {"detail", "source"})

    def test_build_blocks_unsafe_ended_transition_variants(self):
        published = self.published_event()
        cases = {
            "ending_today": (
                {**published, "date_end": "2026-07-31"},
                {
                    **published,
                    "date_end": "2026-07-31",
                    "public_category": "ended",
                    "display_tier": "ended",
                    "current_event_state": "ended",
                },
            ),
            "reverse_transition": (
                {
                    **published,
                    "public_category": "ended",
                    "display_tier": "ended",
                    "current_event_state": "ended",
                },
                published,
            ),
            "invalid_public_category": (
                published,
                {
                    **published,
                    "public_category": "date_unknown",
                    "display_tier": "season_hint",
                    "current_event_state": "predicted",
                    "date_certainty_tier": "season_hint",
                },
            ),
        }

        for case, (site, collector) in cases.items():
            with self.subTest(case=case):
                result = self.run_build(
                    [collector],
                    [site],
                    [self.consumed_same_key_approval(site)],
                )

                self.assertEqual(result["decision"]["status"], "block")
                self.assertIn(
                    "individual_review_diffs_remain", result["decision"]["failures"]
                )
                self.assertEqual(
                    result["approved_classification"]["events_by_action"],
                    {"individual_review": 1},
                )

    def test_build_reports_already_synced_after_site_catches_up(self):
        published = self.published_event()
        collector = {
            **published,
            "public_category": "ended",
            "display_tier": "ended",
            "current_event_state": "ended",
        }

        result = self.run_build(
            [collector],
            [collector],
            [self.consumed_same_key_approval(published)],
        )

        self.assertEqual(result["decision"]["status"], "pass")
        self.assertEqual(
            result["reviewed_exact_approvals"]["status_counts"],
            {"already_synced": 1},
        )
        self.assertEqual(result["approved_classification"]["events_by_action"], {})

    def test_build_rejects_drift_before_the_reviewed_value_was_published(self):
        published = self.published_event()
        original_site = {**published, "detail": "承認前の値"}
        collector = {**published, "date_end": "2026-07-30"}
        approval = self.same_key_approval(original_site, published)

        result = self.run_build([collector], [original_site], [approval])

        self.assertEqual(result["decision"]["status"], "block")
        self.assertIn("reviewed_exact_approval_mismatch", result["decision"]["failures"])
        self.assertEqual(
            result["reviewed_exact_approvals"]["status_counts"],
            {"hash_mismatch": 1},
        )

    def test_build_allows_song_only_update_when_old_exact_approval_hash_is_stale(self):
        published = self.published_event()
        site = {
            **published,
            "songs": [{"name": "東京音頭", "probability": 95}],
        }
        collector = {
            **published,
            "songs": [{"name": "東京音頭", "probability": 71}],
        }
        stale_approval = self.same_key_approval(
            {**published, "detail": "承認前の値"},
            {**published, "detail": "以前承認した値"},
        )

        result = self.run_build([collector], [site], [stale_approval])

        self.assertEqual(result["raw_classification"]["high_risk_diff_record_count"], 0)
        self.assertEqual(
            result["reviewed_exact_approvals"]["status_counts"],
            {"hash_mismatch": 1},
        )
        self.assertEqual(result["decision"]["status"], "pass")
        self.assertIn(
            "stale_reviewed_approval_hashes_songs_only",
            result["decision"]["warnings"],
        )

    def stale_song_update(self, *, renamed=False):
        published = self.published_event()
        site = {**published, "songs": [{"name": "東京音頭", "probability": 95}]}
        collector = {**published, "songs": [{"name": "東京音頭", "probability": 71}]}
        old = {**published, "detail": "承認前の値"}
        arrival = {**published, "detail": "以前承認した値"}
        if renamed:
            old["name"] = "改名前の盆踊り"
            approval = self.key_replacement_approval(old, arrival)
        else:
            approval = self.same_key_approval(old, arrival)
        return collector, site, approval

    def test_song_only_stale_approvals_coexist_with_other_ended_transitions(self):
        for renamed in (False, True):
            with self.subTest(renamed=renamed):
                collector, site, approval = self.stale_song_update(renamed=renamed)
                other_site = {**self.published_event(), "name": "別の盆踊り"}
                other_collector = {
                    **other_site, "public_category": "ended",
                    "display_tier": "ended", "current_event_state": "ended",
                }
                inputs = ([collector, other_collector], [site, other_site], [approval])
                original = copy.deepcopy(inputs)
                result = self.run_build(*inputs)
                self.assertEqual(inputs, original)
                self.assertEqual(result["decision"]["status"], "pass")
                self.assertEqual(result["approved_classification"]["events_by_action"],
                                 {"ended_transition_downgrade": 1})
                summary = result["reviewed_exact_approvals"]
                self.assertEqual(summary["status_counts"], {"hash_mismatch": 1})
                self.assertEqual(summary["failure_count"], 1)
                self.assertEqual(result["decision"]["song_only_approval_warnings"][0]["id"], approval["id"])
                self.assertEqual(result["decision"]["song_only_approval_warnings"][0]["changed_fields"], ["songs"])
                self.assertEqual(result["approved_classification"],
                                 result["postprocessed_classification"])

    def test_song_only_exception_rejects_every_additional_raw_field_difference(self):
        differences = {
            "date": "2026-07-27", "date_end": "2026-07-30",
            "detail": "未承認の詳細", "source_urls": ["https://example.org/new"],
            "display_tier": "ended", "unknown_field": "new",
            # Presence and JSON types matter even when Python values compare equal.
            "unknown_null": None, "unknown_number": True,
            "source_urls_normalized": [{"url": "https://example.org/source"}],
        }
        for renamed in (False, True):
            for field, value in differences.items():
                with self.subTest(renamed=renamed, field=field):
                    collector, site, approval = self.stale_song_update(renamed=renamed)
                    if field == "unknown_number":
                        site[field] = 1
                    if field == "source_urls_normalized":
                        field = "source_urls"
                        site[field] = [*value, {"url": "https://example.org/extra"}]
                    collector[field] = value
                    result = self.run_build([collector], [site], [approval])
                    self.assertIn("reviewed_exact_approval_mismatch",
                                  result["decision"]["failures"])

    def test_song_only_exception_requires_unique_current_rows_on_both_sides(self):
        for renamed in (False, True):
            for duplicate_side in ("collector", "site", "both"):
                with self.subTest(renamed=renamed, duplicate_side=duplicate_side):
                    collector, site, approval = self.stale_song_update(renamed=renamed)
                    collector_rows = [collector] * (2 if duplicate_side != "site" else 1)
                    site_rows = [site] * (2 if duplicate_side != "collector" else 1)
                    result = self.run_build(collector_rows, site_rows, [approval])
                    self.assertIn("reviewed_exact_approval_mismatch",
                                  result["decision"]["failures"])

    def test_song_only_rename_exception_rejects_old_key_on_either_side(self):
        for old_key_side in ("collector", "site", "both"):
            with self.subTest(old_key_side=old_key_side):
                collector, site, approval = self.stale_song_update(renamed=True)
                old = {**site, "name": "改名前の盆踊り"}
                collector_rows = [collector] + ([old] if old_key_side != "site" else [])
                site_rows = [site] + ([old] if old_key_side != "collector" else [])
                result = self.run_build(collector_rows, site_rows, [approval])
                self.assertIn("reviewed_exact_approval_mismatch",
                              result["decision"]["failures"])

    def test_song_only_exception_rejects_missing_rows(self):
        for renamed in (False, True):
            for missing_side in ("collector", "site"):
                with self.subTest(renamed=renamed, missing_side=missing_side):
                    collector, site, approval = self.stale_song_update(renamed=renamed)
                    result = self.run_build(
                        [] if missing_side == "collector" else [collector],
                        [] if missing_side == "site" else [site], [approval])
                    self.assertEqual(result["decision"]["status"], "block")

    def test_song_only_exception_never_waives_invalid_approval_records(self):
        collector, site, approval = self.stale_song_update()
        invalid_entries = [None, {}, {**approval, "kind": "unknown"},
                           {**approval, "id": ""},
                           {**approval, "id": 123},
                           {**approval, "site_sha256": ""},
                           {**approval, "collector_sha256": "not-a-hash"}]
        for invalid in invalid_entries:
            with self.subTest(invalid=invalid):
                result = self.run_build([collector], [site], [invalid])
                self.assertIn("reviewed_exact_approval_mismatch",
                              result["decision"]["failures"])
        result = self.run_build([collector], [site], [approval, approval])
        self.assertIn("reviewed_exact_approval_mismatch", result["decision"]["failures"])
        result = self.run_build([collector], [site], [approval], approval_schema="invalid")
        self.assertIn("reviewed_exact_approval_mismatch", result["decision"]["failures"])

    def test_song_only_exception_requires_song_arrays_on_both_sides(self):
        for side in ("collector", "site"):
            for invalid_songs in (None, True, "東京音頭", {}):
                with self.subTest(side=side, invalid_songs=invalid_songs):
                    collector, site, approval = self.stale_song_update()
                    (collector if side == "collector" else site)["songs"] = invalid_songs
                    result = self.run_build([collector], [site], [approval])
                    self.assertIn("reviewed_exact_approval_mismatch", result["decision"]["failures"])
            collector, site, approval = self.stale_song_update()
            (collector if side == "collector" else site).pop("songs")
            result = self.run_build([collector], [site], [approval])
            self.assertIn("reviewed_exact_approval_mismatch", result["decision"]["failures"])

    def test_song_only_exception_does_not_hide_other_unapproved_changes(self):
        collector, site, approval = self.stale_song_update()
        other_site = {**self.published_event(), "name": "別の盆踊り"}
        for field, value in (("date", "2026-07-27"), ("detail", "未承認")):
            with self.subTest(field=field):
                result = self.run_build([collector, {**other_site, field: value}],
                                        [site, other_site], [approval])
                self.assertEqual(result["decision"]["status"], "block")
                self.assertEqual(len(result["decision"]["song_only_approval_warnings"]), 1)
                self.assertNotIn("reviewed_exact_approval_mismatch", result["decision"]["failures"])

    def test_song_only_exception_does_not_waive_unapproved_additions_or_removals(self):
        collector, site, approval = self.stale_song_update()
        other = {**self.published_event(), "name": "別の盆踊り"}
        for kind in ("addition", "removal"):
            with self.subTest(kind=kind):
                invalid_hash = {
                    "id": "other", "kind": kind, "event_key": "別の盆踊り||確認公園",
                    "collector_sha256": "0" * 64, "site_sha256": "0" * 64,
                }
                result = self.run_build(
                    [collector] + ([other] if kind == "addition" else []),
                    [site] + ([other] if kind == "removal" else []),
                    [approval, invalid_hash])
                self.assertIn("reviewed_exact_approval_mismatch", result["decision"]["failures"])

    def test_song_only_exception_is_not_needed_after_sync_or_reused_for_future_drift(self):
        for renamed in (False, True):
            with self.subTest(renamed=renamed):
                collector, _, approval = self.stale_song_update(renamed=renamed)
                synced = self.run_build([collector], [collector], [approval])
                self.assertEqual(synced["decision"]["status"], "pass")
                self.assertEqual(synced["reviewed_exact_approvals"]["status_counts"],
                                 {"already_synced": 1})
                drifted = self.run_build([{**collector, "detail": "未承認"}], [collector], [approval])
                self.assertIn("reviewed_exact_approval_mismatch", drifted["decision"]["failures"])

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
