import unittest
from pathlib import Path

from manual_apply_guards import PUBLIC_JSON_ONE_OFF_CONFIRMATION


ROOT = Path(__file__).resolve().parents[1]


class PublicJsonPostprocessorPolicyTest(unittest.TestCase):
    def test_scheduled_postprocessors_remain_automatic(self):
        scripts = [
            "public_json_postprocessors/apply_public_date_predictions.py",
            "public_json_postprocessors/apply_public_historical_references.py",
            "public_json_postprocessors/apply_public_season_hints.py",
        ]

        for filename in scripts:
            with self.subTest(filename=filename):
                script = (ROOT / filename).read_text(encoding="utf-8")
                self.assertNotIn("PUBLIC_JSON_ONE_OFF_CONFIRMATION", script)

        collect = (ROOT / ".github" / "workflows" / "collect.yml").read_text(
            encoding="utf-8"
        )
        weekly = (ROOT / ".github" / "workflows" / "weekly_harvest.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("python export_public_events.py", collect)
        self.assertNotIn("python apply_public_date_predictions.py", collect)
        self.assertNotIn("python apply_public_historical_references.py", collect)
        self.assertNotIn("python apply_public_season_hints.py", collect)
        self.assertIn("python export_public_events.py", weekly)
        self.assertNotIn("python apply_public_date_predictions.py", weekly)
        self.assertNotIn("python apply_public_historical_references.py", weekly)
        self.assertNotIn("python apply_public_season_hints.py", weekly)

    def test_manual_public_json_one_off_scripts_require_confirmation(self):
        scripts = [
            "apply_public_event_name_cleanup.py",
            "apply_public_official_source_urls.py",
        ]

        for filename in scripts:
            with self.subTest(filename=filename):
                script = (ROOT / filename).read_text(encoding="utf-8")
                self.assertIn('parser.add_argument("--confirm"', script)
                self.assertIn("require_confirmation", script)
                self.assertIn("PUBLIC_JSON_ONE_OFF_CONFIRMATION", script)

    def test_master_rdb_one_off_scripts_keep_specific_confirmations(self):
        expectations = {
            "apply_pre_cutover_p0_historical_references.py": "APPLY PRE CUTOVER P0 HISTORICAL REFERENCES",
            "apply_reviewed_historical_references.py": "APPLY REVIEWED HISTORICAL REFERENCES",
            "legacy/apply/apply_ph2_ebara_fifth_rdb.py": "APPLY PH2 EBARA FIFTH RDB",
        }

        for filename, phrase in expectations.items():
            with self.subTest(filename=filename):
                script = (ROOT / filename).read_text(encoding="utf-8")
                self.assertIn("--apply", script)
                self.assertIn('parser.add_argument("--confirm"', script)
                self.assertIn(phrase, script)

    def test_runbook_and_inventory_document_boundary(self):
        runbook = (
            ROOT / "docs" / "public-json-postprocessor-operations.md"
        ).read_text(encoding="utf-8")
        inventory = (
            ROOT / "docs" / "manual-auto-operations-inventory.md"
        ).read_text(encoding="utf-8")

        self.assertIn("Keep these automatic", runbook)
        self.assertIn(PUBLIC_JSON_ONE_OFF_CONFIRMATION, runbook)
        self.assertIn("Do not add schedules around manual public JSON one-offs", runbook)
        self.assertIn("Public JSON deterministic postprocessors", inventory)
        self.assertIn("Master RDB / public JSON one-off apply scripts", inventory)


if __name__ == "__main__":
    unittest.main()
