import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import collect


class CollectOutcomeMainTest(unittest.TestCase):
    def test_invalid_existing_snapshot_never_reaches_voice_derived_downstream(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            data = root / "data"
            data.mkdir()
            voices = data / "voices.json"
            voices.write_bytes(b"{not-json")
            seen = data / "voices_seen.json"
            seen.write_text("[]", encoding="utf-8")
            venue = data / "venue_master.json"
            venue.write_text(json.dumps({"venues": []}), encoding="utf-8")
            original = os.getcwd()
            try:
                os.chdir(root)
                with (
                    patch.object(collect, "VENUE_MASTER_FILE", str(venue)),
                    patch.object(collect, "fetch_news", return_value=None),
                    patch.object(collect, "fetch_blog_feeds", return_value=[]),
                    patch.object(collect, "collect_event_evidence_history", return_value=[]),
                    patch.object(collect, "push_event_candidate_queue", return_value={"failed": 0}),
                    patch.object(collect, "detect_venues_for_queue") as detect,
                    patch.object(collect, "push_torimochi_queue") as push_queue,
                    patch.object(collect, "push_to_notion") as notion,
                    patch.object(collect, "write_health_report"),
                ):
                    collect.main()
            finally:
                os.chdir(original)
            self.assertEqual(voices.read_bytes(), b"{not-json")
            self.assertEqual(seen.read_text(encoding="utf-8"), "[]")
            detect.assert_not_called()
            push_queue.assert_not_called()
            notion.assert_not_called()


if __name__ == "__main__":
    unittest.main()
