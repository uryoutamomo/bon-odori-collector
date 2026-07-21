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

    def test_review_candidates_have_no_safety_reference(self):
        candidates = [
            item
            for item in self.inventory["items"]
            if item["classification"] == "review_candidate"
        ]
        self.assertTrue(candidates)
        for item in candidates:
            with self.subTest(path=item["path"]):
                refs = item["references"]
                self.assertFalse(refs["workflow"])
                self.assertFalse(refs["source"])
                self.assertFalse(refs["test"])
                self.assertFalse(refs["docs"])


if __name__ == "__main__":
    unittest.main()
