import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import collect
from collection_support.proactive_search import OfficialScanOutcome


class CollectOutcomeMainTest(unittest.TestCase):
    @staticmethod
    def _write_due_target(data):
        (data / "evergreen_events.json").write_text(
            json.dumps({"lead_months": 0, "events": [{
                "venue": "fixture venue", "event_name": "fixture event",
                "months": [datetime.now().month],
                "official_sources": ["https://official.fixture/"],
            }]}),
            encoding="utf-8",
        )

    @staticmethod
    def _completed_empty_x_lane(lane):
        def collect_empty(*_args, health=None, **_kwargs):
            collect.set_planned_units(health, lane, 1)
            collect.mark_unit_complete(health, lane, "fixture")
            return [], []
        return collect_empty

    def test_main_x_partial_failure_closes_every_voice_derived_gate(self):
        with tempfile.TemporaryDirectory() as raw:
            root, data = Path(raw), Path(raw) / "data"
            data.mkdir()
            (data / "voices.json").write_text("[]", encoding="utf-8")
            (data / "voices_seen.json").write_text("[]", encoding="utf-8")
            venue = data / "venue_master.json"
            venue.write_text(json.dumps({"venues": []}), encoding="utf-8")
            self._write_due_target(data)
            def failed_keyword(_seen, health=None):
                collect.record_failure(health, "keyword", "test", error="down")
                return [], []
            original = os.getcwd()
            try:
                os.chdir(root)
                with (
                    patch.object(collect, "VENUE_MASTER_FILE", str(venue)),
                    patch.object(collect, "TWITTERAPI_IO_KEY", "test"),
                    patch.object(collect, "fetch_news", return_value=None),
                    patch.object(collect, "fetch_blog_feeds", return_value=[]),
                    patch.object(collect, "collect_voices_outcome", return_value=collect.VoiceCollectionResult("empty", seen_urls=[])),
                    patch.object(collect, "collect_x_voices", side_effect=failed_keyword),
                    patch.object(collect, "collect_proactive_x", side_effect=self._completed_empty_x_lane("proactive")),
                    patch.object(collect, "collect_x_whitelist", side_effect=self._completed_empty_x_lane("whitelist")),
                    patch.object(collect, "require_writable_local_voices"),
                    patch.object(collect, "collect_event_evidence_history", return_value=[]),
                    patch.object(collect, "push_event_candidate_queue", return_value={"failed": 0}),
                    patch.object(collect, "detect_venues_for_queue") as detect,
                    patch.object(collect, "_save_x_account_scores") as scores,
                    patch.object(collect, "_refresh_official_source_registry") as registry,
                    patch.object(collect, "scan_official_sources_outcome") as official,
                    patch.object(collect, "push_to_notion") as notion,
                    patch.object(collect, "write_health_report"),
                ):
                    collect.main()
            finally:
                os.chdir(original)
            for mocked in (detect, scores, registry, official, notion):
                mocked.assert_not_called()

    def test_main_broken_x_config_is_failed_and_closes_voice_derived_gates(self):
        with tempfile.TemporaryDirectory() as raw:
            root, data = Path(raw), Path(raw) / "data"
            data.mkdir()
            (data / "voices.json").write_text("[]", encoding="utf-8")
            (data / "voices_seen.json").write_text("[]", encoding="utf-8")
            query_config = data / "x_queries.json"
            query_config.write_text("{broken", encoding="utf-8")
            venue = data / "venue_master.json"
            venue.write_text(json.dumps({"venues": []}), encoding="utf-8")
            self._write_due_target(data)
            original = os.getcwd()
            try:
                os.chdir(root)
                with (
                    patch.object(collect, "VENUE_MASTER_FILE", str(venue)),
                    patch.object(collect, "X_QUERIES_FILE", str(query_config)),
                    patch.object(collect, "TWITTERAPI_IO_KEY", "test"),
                    patch.object(collect, "fetch_news", return_value=None),
                    patch.object(collect, "fetch_blog_feeds", return_value=[]),
                    patch.object(collect, "collect_voices_outcome", return_value=collect.VoiceCollectionResult("empty", seen_urls=[])),
                    patch.object(collect, "load_whitelist_accounts", return_value=[{"handle": "@fixture"}]) as accounts,
                    patch.object(collect, "_x_search") as search,
                    patch.object(collect, "require_writable_local_voices"),
                    patch.object(collect, "collect_event_evidence_history", return_value=[]),
                    patch.object(collect, "push_event_candidate_queue", return_value={"failed": 0}),
                    patch.object(collect, "detect_venues_for_queue") as detect,
                    patch.object(collect, "_save_x_account_scores") as scores,
                    patch.object(collect, "_refresh_official_source_registry") as registry,
                    patch.object(collect, "scan_official_sources_outcome") as official,
                    patch.object(collect, "push_to_notion") as notion,
                    patch.object(collect, "_write_collection_outcome") as outcome,
                    patch.object(collect, "write_health_report") as health_report,
                ):
                    collect.main()
            finally:
                os.chdir(original)
            accounts.assert_not_called()
            search.assert_not_called()
            for mocked in (detect, scores, registry, official, notion):
                mocked.assert_not_called()
            saved = outcome.call_args.args[0]
            self.assertEqual(saved["snapshot"], "failed")
            health = health_report.call_args.args[0]
            self.assertEqual(health["status"], "unhealthy")
            self.assertIn("x_request_failures:3", health["failure_reasons"])
            self.assertEqual(
                {saved["lanes"][name] for name in ("x_keyword", "x_proactive", "x_whitelist")},
                {"failed"},
            )

    def test_main_score_write_failure_closes_later_voice_gates(self):
        with tempfile.TemporaryDirectory() as raw:
            root, data = Path(raw), Path(raw) / "data"
            data.mkdir()
            (data / "voices.json").write_text("[]", encoding="utf-8")
            (data / "voices_seen.json").write_text("[]", encoding="utf-8")
            venue = data / "venue_master.json"
            venue.write_text(json.dumps({"venues": []}), encoding="utf-8")
            self._write_due_target(data)
            empty_keyword = self._completed_empty_x_lane("keyword")
            empty_proactive = self._completed_empty_x_lane("proactive")
            empty_whitelist = self._completed_empty_x_lane("whitelist")
            original = os.getcwd()
            try:
                os.chdir(root)
                with (
                    patch.object(collect, "VENUE_MASTER_FILE", str(venue)),
                    patch.object(collect, "TWITTERAPI_IO_KEY", "test"),
                    patch.object(collect, "fetch_news", return_value=None),
                    patch.object(collect, "fetch_blog_feeds", return_value=[]),
                    patch.object(collect, "collect_voices_outcome", return_value=collect.VoiceCollectionResult("empty", seen_urls=[])),
                    patch.object(collect, "collect_x_voices", side_effect=empty_keyword),
                    patch.object(collect, "collect_proactive_x", side_effect=empty_proactive),
                    patch.object(collect, "collect_x_whitelist", side_effect=empty_whitelist),
                    patch.object(collect, "require_writable_local_voices"),
                    patch.object(collect, "collect_event_evidence_history", return_value=[]),
                    patch.object(collect, "push_event_candidate_queue", return_value={"failed": 0}),
                    patch.object(collect, "_save_x_account_scores", side_effect=OSError("disk full")) as scores,
                    patch.object(collect, "_refresh_official_source_registry") as registry,
                    patch.object(collect, "detect_venues_for_queue") as detect,
                    patch.object(collect, "scan_official_sources_outcome") as official,
                    patch.object(collect, "push_to_notion") as notion,
                    patch.object(collect, "write_health_report"),
                ):
                    collect.main()
            finally:
                os.chdir(original)
            scores.assert_called_once()
            for mocked in (registry, detect, official, notion):
                mocked.assert_not_called()

    def test_main_empty_completed_lanes_reach_voice_derived_downstream(self):
        with tempfile.TemporaryDirectory() as raw:
            root, data = Path(raw), Path(raw) / "data"
            data.mkdir()
            (data / "voices.json").write_text("[]", encoding="utf-8")
            (data / "voices_seen.json").write_text("[]", encoding="utf-8")
            venue = data / "venue_master.json"
            venue.write_text(json.dumps({"venues": []}), encoding="utf-8")
            self._write_due_target(data)
            original = os.getcwd()
            try:
                os.chdir(root)
                with (
                    patch.object(collect, "VENUE_MASTER_FILE", str(venue)),
                    patch.object(collect, "TWITTERAPI_IO_KEY", "test"),
                    patch.object(collect, "fetch_news", return_value=None),
                    patch.object(collect, "fetch_blog_feeds", return_value=[]),
                    patch.object(collect, "collect_voices_outcome", return_value=collect.VoiceCollectionResult("empty", seen_urls=[])),
                    patch.object(collect, "collect_x_voices", side_effect=self._completed_empty_x_lane("keyword")),
                    patch.object(collect, "collect_proactive_x", side_effect=self._completed_empty_x_lane("proactive")),
                    patch.object(collect, "collect_x_whitelist", side_effect=self._completed_empty_x_lane("whitelist")),
                    patch.object(collect, "require_writable_local_voices"),
                    patch.object(collect, "collect_event_evidence_history", return_value=[]),
                    patch.object(collect, "push_event_candidate_queue", return_value={"failed": 0}),
                    patch.object(collect, "detect_venues_for_queue", return_value=[]),
                    patch.object(collect, "push_torimochi_queue"),
                    patch.object(collect, "_save_x_account_scores") as scores,
                    patch.object(collect, "_refresh_official_source_registry") as registry,
                    patch.object(collect, "scan_official_sources_outcome", return_value=OfficialScanOutcome("empty")) as official,
                    patch.object(collect, "push_to_notion") as notion,
                    patch.object(collect, "write_health_report"),
                ):
                    collect.main()
            finally:
                os.chdir(original)
            scores.assert_called_once()
            registry.assert_called_once()
            official.assert_called_once()
            notion.assert_called_once()

    def test_save_x_account_scores_propagates_write_failure(self):
        with patch.object(collect, "_build_x_account_scores", return_value={"accounts": {}}), patch("builtins.open", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                collect._save_x_account_scores([])

    def test_x_health_failure_is_not_reported_as_empty(self):
        health = {"lanes": {"keyword": {"planned_units": 1, "completed_units": 0, "failed_requests": 1}}}
        self.assertEqual(collect._x_lane_state(health, "keyword", []), "failed")

    def test_x_health_skip_is_not_reported_as_empty(self):
        health = {"lanes": {"keyword": {"skipped_reason": "api_key_missing"}}}
        self.assertEqual(collect._x_lane_state(health, "keyword", []), "skipped")

    def test_voice_snapshot_rollback_removes_new_first_file_when_second_replace_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            voices, seen = root / "voices.json", root / "seen.json"
            original_replace = Path.replace
            calls = []
            def fail_second(source, target):
                calls.append((source, target))
                if len(calls) == 2:
                    raise OSError("second replace")
                return original_replace(source, target)
            with patch.object(Path, "replace", fail_second):
                with self.assertRaises(OSError):
                    collect._commit_voice_snapshot(voices, [{"url": "new"}], seen, ["new"])
            self.assertFalse(voices.exists())
            self.assertFalse(seen.exists())

    def test_voice_snapshot_rollback_restores_existing_bytes(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            voices, seen = root / "voices.json", root / "seen.json"
            voices.write_bytes(b"old-voices")
            seen.write_bytes(b"old-seen")
            original_replace = Path.replace
            calls = []
            def fail_second(source, target):
                calls.append((source, target))
                if len(calls) == 2:
                    raise OSError("second replace")
                return original_replace(source, target)
            with patch.object(Path, "replace", fail_second):
                with self.assertRaises(OSError):
                    collect._commit_voice_snapshot(voices, [{"url": "new"}], seen, ["new"])
            self.assertEqual(voices.read_bytes(), b"old-voices")
            self.assertEqual(seen.read_bytes(), b"old-seen")

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
