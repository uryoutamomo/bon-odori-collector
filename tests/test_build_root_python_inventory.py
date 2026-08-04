import unittest

from scripts.build_root_python_inventory import build_inventory


class BuildRootPythonInventoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from scripts.build_root_python_inventory import ROOT

        cls.inventory = build_inventory(ROOT, "2026-07-21")
        cls.by_path = {item["path"]: item for item in cls.inventory["items"]}

    def test_workflow_entrypoint_is_detected(self):
        self.assertEqual("workflow_entrypoint", self.by_path["collect.py"]["classification"])

    def test_retained_legacy_dependency_is_explicit(self):
        self.assertEqual(
            "retained_legacy_dependency",
            self.by_path["apply_retrospective_ready_venue_events.py"]["classification"],
        )

    def test_song_catalog_shadow_report_is_test_supported_manual(self):
        # This literal filename reference is what makes the classifier's
        # reference scan (which only reads tracked files -- see
        # tracked_paths()) find build_song_catalog_shadow_report.py, so it
        # is classified test_supported_manual rather than review_candidate.
        # The script itself has no workflow wiring yet (P1 is read-only);
        # it is exercised only via tests/test_build_song_catalog_shadow_report.py.
        self.assertEqual(
            "test_supported_manual",
            self.by_path["build_song_catalog_shadow_report.py"]["classification"],
        )

    def test_all_root_files_have_a_safety_classification(self):
        candidates = [
            item
            for item in self.inventory["items"]
            if item["classification"] == "review_candidate"
        ]
        self.assertEqual([], candidates)


if __name__ == "__main__":
    unittest.main()
