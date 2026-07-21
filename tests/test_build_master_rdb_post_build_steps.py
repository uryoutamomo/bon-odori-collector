import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BuildMasterRdbPostBuildStepsTest(unittest.TestCase):
    def test_post_build_steps_reference_promotion_candidates_package(self):
        source = (ROOT / "rdb_builders" / "build_master_rdb.py").read_text(encoding="utf-8")
        self.assertIn('"promotion_candidates/build_observed_promotion_candidates.py"', source)
        self.assertIn('"promotion_candidates/build_registered_event_investigation_queue.py"', source)
        self.assertIn('"promotion_candidates/build_historical_promotion_candidates.py"', source)
        self.assertNotIn('"build_observed_promotion_candidates.py"', source)
        self.assertNotIn('"build_registered_event_investigation_queue.py"', source)
        self.assertNotIn('"build_historical_promotion_candidates.py"', source)


if __name__ == "__main__":
    unittest.main()
