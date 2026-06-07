import json
import os
import tempfile
import unittest
from unittest.mock import patch

import collect


class QueueSeenTest(unittest.TestCase):
    def test_loads_legacy_list_as_venues(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "queue_seen.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(["築地本願寺"], f, ensure_ascii=False)

            with patch.object(collect, "QUEUE_SEEN_FILE", path):
                seen = collect._load_queue_seen()

        self.assertEqual(seen["会場"], {"築地本願寺"})
        self.assertEqual(seen["イベント"], set())

    def test_saves_each_candidate_type_separately(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "queue_seen.json")
            seen = {
                "会場": {"築地本願寺"},
                "イベント": {"納涼盆踊り大会"},
            }

            with patch.object(collect, "QUEUE_SEEN_FILE", path):
                collect._save_queue_seen(seen)
            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)

        self.assertEqual(saved["会場"], ["築地本願寺"])
        self.assertEqual(saved["イベント"], ["納涼盆踊り大会"])


if __name__ == "__main__":
    unittest.main()
