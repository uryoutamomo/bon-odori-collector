import unittest
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "legacy" / "build-reports" / "build_retrospective_occurrences.py"
SPEC = importlib.util.spec_from_file_location("build_retrospective_occurrences", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

build_dry_run = MODULE.build_dry_run
event_date = MODULE.event_date


class RetrospectiveOccurrencesTest(unittest.TestCase):
    def test_event_date_does_not_parse_inside_four_digit_year(self):
        self.assertEqual(
            event_date({"estimated_date": "2026/06/21", "year": 2026, "month": "06"}, 2026),
            "2026-06-21",
        )
        self.assertEqual(
            event_date({"estimated_date": "2026/06", "year": 2026, "month": "06"}, 2026),
            "2026-06-01",
        )
        self.assertEqual(
            event_date({"estimated_date": "6/21", "year": 2026}, 2026),
            "2026-06-21",
        )

    def test_matches_existing_event_and_builds_observations(self):
        candidates = {
            "candidate_count": 2,
            "candidates": [
                {
                    "kind": "event",
                    "candidate_key": "event:1",
                    "display_name": "中央公園盆踊り",
                    "normalized_event": "中央公園",
                    "venue": "中央公園",
                    "month": "07",
                    "estimated_date": "7月20日",
                    "year": 2026,
                    "tier": "promote",
                    "score": 55,
                    "evidence": [
                        {
                            "identity": "evidence:1",
                            "url": "https://x.com/a/status/1",
                            "text": "中央公園盆踊りは7月20日開催です",
                            "account": "@a",
                            "dancer_key": "@a",
                            "observed_at": "2026-06-01T00:00:00+00:00",
                        }
                    ],
                },
                {
                    "kind": "song",
                    "candidate_key": "song:1",
                    "display_name": "東京音頭",
                    "venue": "中央公園",
                    "month": "07",
                    "year": 2026,
                    "tier": "review",
                    "score": 25,
                    "evidence": [
                        {
                            "identity": "evidence:2",
                            "url": "https://x.com/a/status/2",
                            "text": "中央公園で東京音頭を踊った",
                            "account": "@a",
                            "dancer_key": "@a",
                            "observed_at": "2026-07-21T00:00:00+00:00",
                        }
                    ],
                },
            ],
        }
        events = [{"name": "中央公園盆踊り", "venue": "中央公園", "months": [7], "status": "確認済み"}]
        venues = [{"venue": "中央公園", "notion_url": "https://example.test/venue"}]
        accounts = {"accounts": {"a": {"handle": "@a", "status": "trusted"}}}

        output = build_dry_run(candidates, events, venues, accounts, target_year=2026, generated_at="now")

        self.assertFalse(output["apply_performed"])
        self.assertEqual(output["summary"]["matched_existing_candidate_count"], 2)
        self.assertEqual(output["summary"]["new_event_candidate_count"], 0)
        occurrence = output["occurrences"][0]
        self.assertEqual(occurrence["event_name"], "中央公園盆踊り")
        self.assertEqual(occurrence["event_match"]["match_type"], "event_venue")
        self.assertEqual(occurrence["event_songs"][0]["song_name"], "東京音頭")
        self.assertTrue(occurrence["observations"][0]["registered_dancer"])

    def test_unmatched_promote_event_is_review_required_new_event(self):
        candidates = {
            "candidate_count": 1,
            "candidates": [
                {
                    "kind": "event",
                    "candidate_key": "event:new",
                    "display_name": "新発見盆踊り",
                    "venue": "新発見公園",
                    "month": "08",
                    "year": 2026,
                    "tier": "promote",
                    "score": 60,
                    "evidence": [{"url": "https://x.com/b/status/1", "account": "@b", "dancer_key": "@b"}],
                }
            ],
        }

        output = build_dry_run(candidates, [], [], {"accounts": {}}, target_year=2026, generated_at="now")

        self.assertEqual(output["summary"]["matched_existing_candidate_count"], 0)
        self.assertEqual(output["summary"]["new_event_candidate_count"], 1)
        self.assertEqual(output["new_event_candidates"][0]["apply_status"], "dry_run_review_required")
        self.assertEqual(output["new_event_candidates"][0]["source"], "retrospective_harvest")
        self.assertEqual(output["new_event_candidates"][0]["evidence"][0]["url"], "https://x.com/b/status/1")


if __name__ == "__main__":
    unittest.main()
