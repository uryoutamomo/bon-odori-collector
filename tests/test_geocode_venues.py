import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/manual/geocode_venues.py"


def load_script_in_repository(root):
    script = root / "scripts/manual/geocode_venues.py"
    script.parent.mkdir(parents=True)
    shutil.copyfile(SCRIPT, script)
    spec = importlib.util.spec_from_file_location("isolated_geocode_venues", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GeocodeVenuesTests(unittest.TestCase):
    def test_main_uses_repository_data_from_an_unrelated_working_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "collector"
            public = root / "data/public"
            public.mkdir(parents=True)
            venues = [
                {"name": "確認用会場", "area": "確認用区", "address": "〒100-0000 確認用住所（補足）"},
                {"name": "住所未確認", "area": "確認用区", "address": ""},
            ]
            source = public / "venues_public.json"
            original = json.dumps(venues, ensure_ascii=False)
            source.write_text(original, encoding="utf-8")
            unrelated = Path(tmp) / "unrelated"
            unrelated.mkdir()
            # A caller's data directory must not override the repository input.
            decoy = unrelated / "data/public"
            decoy.mkdir(parents=True)
            (decoy / "venues_public.json").write_text("[]", encoding="utf-8")

            previous = Path.cwd()
            try:
                os.chdir(unrelated)
                module = load_script_in_repository(root)
                with patch.object(module, "geocode", return_value={
                    "lat": 35.0, "lon": 139.0, "matched_title": "確認用住所",
                }) as geocode, patch.object(module.time, "sleep"), patch("builtins.print"):
                    module.main()
            finally:
                os.chdir(previous)

            geocode.assert_called_once_with("確認用住所")
            output = json.loads((public / "venues_geo.json").read_text(encoding="utf-8"))
            self.assertEqual([row["name"] for row in output], [row["name"] for row in venues])
            self.assertEqual(output[0]["lat"], 35.0)
            self.assertEqual(output[0]["lon"], 139.0)
            self.assertEqual(output[0]["address"], venues[0]["address"])
            self.assertEqual(output[1]["lat"], None)
            self.assertEqual(output[1]["lon"], None)
            self.assertEqual(source.read_text(encoding="utf-8"), original)
            self.assertFalse((decoy / "venues_geo.json").exists())
            self.assertFalse((root / "scripts/manual/data").exists())

    def test_missing_repository_input_does_not_call_api_or_replace_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module = load_script_in_repository(root)
            public = root / "data/public"
            public.mkdir(parents=True)
            output = public / "venues_geo.json"
            output.write_text("existing output", encoding="utf-8")
            with patch.object(module, "geocode") as geocode:
                with self.assertRaises(FileNotFoundError):
                    module.main()
            geocode.assert_not_called()
            self.assertEqual(output.read_text(encoding="utf-8"), "existing output")

    def test_serialization_failure_keeps_existing_output_and_cleans_temporary_file(self):
        def fail_after_partial_write(payload, handle, **kwargs):
            handle.write("partial")
            raise OSError("simulated write failure")

        self._assert_output_preserved(patch_target="json.dump", side_effect=fail_after_partial_write)

    def test_replace_failure_keeps_existing_output_and_cleans_temporary_file(self):
        self._assert_output_preserved(patch_target="os.replace", side_effect=OSError("simulated replace failure"))

    def _assert_output_preserved(self, *, patch_target, side_effect):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module = load_script_in_repository(root)
            public = root / "data/public"
            public.mkdir(parents=True)
            source = public / "venues_public.json"
            source.write_text('[{"name": "test", "address": ""}]')
            output = public / "venues_geo.json"
            output.write_text("existing output")
            owner_name, attribute = patch_target.split(".")
            with patch.object(getattr(module, owner_name), attribute, side_effect=side_effect), \
                    patch.object(module.time, "sleep"):
                with self.assertRaises(OSError):
                    module.main()
            self.assertEqual(output.read_text(), "existing output")
            self.assertEqual({path.name for path in public.iterdir()}, {source.name, output.name})


if __name__ == "__main__":
    unittest.main()
