import unittest
from pathlib import Path

from operation_safety.manual_apply_guards import LEGACY_NOTION_REPAIR_CONFIRMATION


ROOT = Path(__file__).resolve().parents[1]
LEGACY_NOTION_WRITES = ROOT / "legacy" / "notion_writes"


class LegacyNotionRepairPolicyTest(unittest.TestCase):
    def test_repair_scripts_require_confirmation(self):
        archived_scripts = [
            "fill_missing_venue_addresses.py",
            "fill_venue_access_and_scale.py",
            "fix_aoyama_kumano_event_venue.py",
            "merge_duplicate_venues.py",
            "fix_venue_master_cleanup.py",
            "register_blog_venue_candidates.py",
            "register_fallback_event_candidates.py",
            "fill_public_intros.py",
            "create_glossary_v2_db.py",
            "update_glossary_v2_schema.py",
            "register_glossary_v2_seed_candidates.py",
            "register_reviewed_glossary_v2_terms.py",
            "promote_reviewed_glossary_v2_batch.py",
            "migrate_legacy_glossary_aliases_to_v2.py",
            "create_song_master_db.py",
            "clear_registered_glossary_v2_roles.py",
            "apply_retrospective_song_candidates.py",
            "clean_song_master_titles.py",
            "replace_x_members.py",
            "apply_accepted_venue_song_associations.py",
            "apply_missing_venue_review_decisions.py",
        ]

        for filename in archived_scripts:
            with self.subTest(filename=filename):
                script = (LEGACY_NOTION_WRITES / filename).read_text(encoding="utf-8")
                self.assertIn('parser.add_argument("--confirm"', script)
                self.assertIn("require_confirmation", script)
                self.assertIn("LEGACY_NOTION_REPAIR_CONFIRMATION", script)

        active_dependencies = [
            "register_song_master_initial.py",
            "apply_weekly_harvest_human13_decisions.py",
            "apply_weekly_song_review_decisions.py",
            "apply_weekly_song_final_corrections.py",
            "sync_x_account_scores.py",
        ]
        for filename in active_dependencies:
            with self.subTest(active_dependency=filename):
                script = (ROOT / filename).read_text(encoding="utf-8")
                self.assertIn("LEGACY_NOTION_REPAIR_CONFIRMATION", script)

    def test_read_only_venue_master_sync_is_not_repair_guarded(self):
        script = (ROOT / "sync_venue_master.py").read_text(encoding="utf-8")

        self.assertIn("fetch_venues", script)
        self.assertIn("venue_master.json", script)
        self.assertNotIn("LEGACY_NOTION_REPAIR_CONFIRMATION", script)

    def test_runbook_inventory_and_policy_document_boundary(self):
        runbook = (ROOT / "docs" / "legacy-notion-repair-operations.md").read_text(
            encoding="utf-8"
        )
        inventory = (
            ROOT / "docs" / "manual-auto-operations-inventory.md"
        ).read_text(encoding="utf-8")
        notion_policy = (ROOT / "docs" / "notion-usage-policy.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("Keep them manual", runbook)
        self.assertIn(LEGACY_NOTION_REPAIR_CONFIRMATION, runbook)
        self.assertIn("Do not schedule these scripts", runbook)
        self.assertIn("Legacy Notion repair / registration scripts", inventory)
        self.assertIn(LEGACY_NOTION_REPAIR_CONFIRMATION, inventory)
        self.assertIn("Schedule legacy Notion repair / registration scripts", notion_policy)


if __name__ == "__main__":
    unittest.main()
