import unittest
from pathlib import Path

from operation_safety.manual_apply_guards import (
    LOCAL_EVIDENCE_ONE_OFF_CONFIRMATION,
    MASTER_RDB_ONE_OFF_CONFIRMATION,
    PUBLIC_JSON_ONE_OFF_CONFIRMATION,
)


ROOT = Path(__file__).resolve().parents[1]


class MasterRdbPublicJsonOneOffPolicyTest(unittest.TestCase):
    def assert_confirmation_reference(self, script, phrase):
        constant_names = {
            MASTER_RDB_ONE_OFF_CONFIRMATION: "MASTER_RDB_ONE_OFF_CONFIRMATION",
            PUBLIC_JSON_ONE_OFF_CONFIRMATION: "PUBLIC_JSON_ONE_OFF_CONFIRMATION",
            LOCAL_EVIDENCE_ONE_OFF_CONFIRMATION: "LOCAL_EVIDENCE_ONE_OFF_CONFIRMATION",
        }
        self.assertTrue(
            phrase in script or constant_names[phrase] in script,
            f"missing confirmation reference for {phrase}",
        )

    def test_new_one_off_apply_scripts_require_shared_confirmation(self):
        expectations = {
            "apply_ph2_shinagawa_second_venue_review.py": MASTER_RDB_ONE_OFF_CONFIRMATION,
            "promotion_candidates/build_historical_promotion_candidates.py": MASTER_RDB_ONE_OFF_CONFIRMATION,
            "promotion_candidates/build_registered_event_investigation_queue.py": MASTER_RDB_ONE_OFF_CONFIRMATION,
            "apply_public_event_name_cleanup.py": PUBLIC_JSON_ONE_OFF_CONFIRMATION,
            "apply_public_official_source_urls.py": PUBLIC_JSON_ONE_OFF_CONFIRMATION,
            "apply_youtube_year_backfill_review_decisions.py": LOCAL_EVIDENCE_ONE_OFF_CONFIRMATION,
        }

        for filename, phrase in expectations.items():
            with self.subTest(filename=filename):
                script = (ROOT / filename).read_text(encoding="utf-8")
                self.assertIn('parser.add_argument("--confirm"', script)
                self.assertIn("require_confirmation", script)
                self.assert_confirmation_reference(script, phrase)

    def test_existing_master_rdb_one_off_scripts_keep_specific_confirmation(self):
        expectations = {
            "legacy/apply/apply_ph2_ebara_fifth_rdb.py": "APPLY PH2 EBARA FIFTH RDB",
            "legacy/apply/apply_gujo_series_merge.py": "APPLY GUJO SERIES MERGE",
            "apply_notion_drift_public_intro.py": "APPLY NOTION DRIFT PUBLIC INTRO",
            "apply_notion_drift_source_url_resolutions.py": "APPLY NOTION DRIFT SOURCE URL RESOLUTIONS",
            "apply_pre_cutover_p0_historical_references.py": "APPLY PRE CUTOVER P0 HISTORICAL REFERENCES",
            "apply_predicted_occurrence_source_rechecks.py": "APPLY PREDICTED SOURCE RECHECKS",
            "apply_reviewed_historical_references.py": "APPLY REVIEWED HISTORICAL REFERENCES",
            "apply_reviewed_missing_occurrence_venues.py": "APPLY REVIEWED MISSING OCCURRENCE VENUES",
            "apply_reviewed_missing_source_urls.py": "APPLY REVIEWED MISSING SOURCE URLS",
            "apply_reviewed_shinagawa_date_fills.py": "APPLY REVIEWED SHINAGAWA DATE FILLS",
            "apply_reviewed_venue_field_fixes.py": "APPLY REVIEWED VENUE FIELD FIXES",
        }

        for filename, phrase in expectations.items():
            with self.subTest(filename=filename):
                script = (ROOT / filename).read_text(encoding="utf-8")
                self.assertIn("--apply", script)
                self.assertIn("--confirm", script)
                self.assertIn(phrase, script)

    def test_automated_public_postprocessors_are_documented_separately(self):
        runbook = (
            ROOT / "docs" / "master-rdb-public-json-one-off-operations.md"
        ).read_text(encoding="utf-8")

        self.assertIn("Automated Public Postprocessors", runbook)
        self.assertIn("apply_public_date_predictions.py", runbook)
        self.assertIn("apply_public_historical_references.py", runbook)
        self.assertIn("apply_public_season_hints.py", runbook)

    def test_runbook_inventory_and_policy_document_boundary(self):
        runbook = (
            ROOT / "docs" / "master-rdb-public-json-one-off-operations.md"
        ).read_text(encoding="utf-8")
        inventory = (
            ROOT / "docs" / "manual-auto-operations-inventory.md"
        ).read_text(encoding="utf-8")
        notion_policy = (ROOT / "docs" / "notion-usage-policy.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("Keep one-off data mutation scripts manual", runbook)
        self.assertIn(MASTER_RDB_ONE_OFF_CONFIRMATION, runbook)
        self.assertIn(PUBLIC_JSON_ONE_OFF_CONFIRMATION, runbook)
        self.assertIn(LOCAL_EVIDENCE_ONE_OFF_CONFIRMATION, runbook)
        self.assertIn("Master RDB / public JSON one-off apply scripts", inventory)
        self.assertIn(PUBLIC_JSON_ONE_OFF_CONFIRMATION, inventory)
        self.assertIn("Schedule Master RDB / public JSON one-off apply scripts", notion_policy)


if __name__ == "__main__":
    unittest.main()
