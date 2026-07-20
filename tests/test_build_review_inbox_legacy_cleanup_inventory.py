import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("cleanup_inventory", ROOT / "scripts/build_review_inbox_legacy_cleanup_inventory.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LegacyCleanupInventoryTest(unittest.TestCase):
    def test_inventory_marks_known_adapter_inputs_and_rollback_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".github/workflows").mkdir(parents=True)
            (root / "data").mkdir()
            (root / "review_console").mkdir(parents=True)
            (root / "data/rare_signal_backcheck_queue.json").write_text("{}", encoding="utf-8")
            (root / ".github/workflows/collect.yml").write_text("rare_signal_backcheck_queue.json", encoding="utf-8")
            report = MODULE.build_inventory(root)
        rows = {row["source_id"]: row for row in report["rows"]}
        self.assertEqual(rows["rare_signal_backcheck"]["category"], "parity_input")
        self.assertTrue(rows["rare_signal_backcheck"]["exists"])
        self.assertEqual(rows["rare_signal_backcheck"]["workflow_or_adapter_references"], [".github/workflows/collect.yml"])
        self.assertEqual(rows["legacy_official_source"]["category"], "rollback_snapshot")
        self.assertEqual(rows["daily_song"]["alternate_live_writers"][0]["workflow"], ".github/workflows/weekly_harvest.yml")

    def test_markdown_keeps_no_delete_boundary(self):
        markdown = MODULE.render_markdown({"rows": [], "category_counts": {}})
        self.assertIn("削除・移動・workflow変更を行わない", markdown)
        self.assertIn("parity_input", markdown)
        self.assertIn("alternate_live_writer", markdown)


if __name__ == "__main__":
    unittest.main()
