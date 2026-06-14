import unittest
import json
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import patch

import collect
from event_evidence import (
    aggregate_event_candidates,
    build_event_candidate_key,
    build_event_candidate_match_key,
    build_history_query,
    build_initial_window,
    classify_event_evidence,
    evidence_identity,
    normalize_event_name,
)


class EventEvidenceTest(unittest.TestCase):
    def test_classifies_patterns_and_explainable_score(self):
        evidence = classify_event_evidence({
            "account": "@odorer",
            "date": "2025-06-10T10:00:00+00:00",
            "tweet_id": "12345",
            "url": "https://x.com/odorer/status/12345",
            "text": "今年も中央区の浜町公園盆踊りへ一緒に行こう。6月20日開催！",
        })

        self.assertEqual(evidence["identity"], "evidence:12345")
        self.assertIn("A", evidence["patterns"])
        self.assertIn("D", evidence["patterns"])
        self.assertGreaterEqual(evidence["score"], 8)
        self.assertEqual(evidence["estimated_venue"], "浜町公園")
        self.assertTrue(evidence["related_key"])

    def test_keeps_weak_fragment_but_scores_weak_context_down(self):
        evidence = classify_event_evidence({
            "account": "@someone",
            "date": "2025-06-10T10:00:00+00:00",
            "url": "https://x.com/someone/status/99",
            "text": "来週一緒に行かない？",
        })

        self.assertIsNotNone(evidence)
        self.assertIn("D", evidence["patterns"])
        self.assertIn("weak_bon_context:-3", evidence["score_reasons"])

    def test_ignores_post_without_a_to_e_pattern(self):
        self.assertIsNone(classify_event_evidence({
            "text": "盆踊りの写真です",
            "url": "https://x.com/example/status/1",
        }))

    def test_identity_falls_back_to_url_hash(self):
        first = evidence_identity({"url": "https://example.com/a", "text": "x"})
        second = evidence_identity({"url": "https://example.com/a", "text": "x"})
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("evidence:sha256:"))

    def test_event_candidate_key_uses_event_venue_and_month(self):
        evidence = classify_event_evidence({
            "account": "@odorer",
            "date": "2025-06-10T10:00:00+00:00",
            "tweet_id": "12345",
            "url": "https://x.com/odorer/status/12345",
            "text": "浜町公園盆踊りに6月20日行きます #浜町公園盆踊り",
        })
        match_key = build_event_candidate_match_key(evidence)
        self.assertIn("event:浜町公園", match_key)
        self.assertIn("venue:浜町公園", match_key)
        self.assertIn("month:06", match_key)
        self.assertTrue(build_event_candidate_key(match_key).startswith("event:"))

    def test_generic_event_name_is_suppressed_and_uses_venue_month(self):
        evidence = classify_event_evidence({
            "account": "@odorer",
            "date": "2025-06-10T10:00:00+00:00",
            "tweet_id": "12345",
            "url": "https://x.com/odorer/status/12345",
            "text": "中央公園の祭りと盆踊りに6月20日行きます",
        })
        match_key = build_event_candidate_match_key(evidence)
        self.assertEqual(evidence["estimated_event"], "")
        self.assertEqual(evidence["suppressed_event_hints"], ["中央公園の祭りと盆踊り"])
        self.assertIn("venue:中央公園", match_key)
        self.assertIn("month:06", match_key)
        self.assertNotIn("event:", match_key)

    def test_blocked_cultural_event_name_is_suppressed(self):
        evidence = classify_event_evidence({
            "account": "@fan",
            "date": "2026-06-13T10:00:00+00:00",
            "tweet_id": "999",
            "url": "https://x.com/fan/status/999",
            "text": "見取り図盆踊り、8/21行きます",
        })
        match_key = build_event_candidate_match_key(evidence)
        self.assertEqual(evidence["estimated_event"], "")
        self.assertEqual(evidence["suppressed_event_hints"], ["見取り図盆踊り"])
        self.assertNotIn("event:", match_key)
        self.assertNotIn("month:08", match_key)

    def test_event_sentence_fragment_is_suppressed(self):
        evidence = classify_event_evidence({
            "account": "@fan",
            "date": "2026-06-13T10:00:00+00:00",
            "tweet_id": "998",
            "url": "https://x.com/fan/status/998",
            "text": "今日は盆踊り仲間となんとなく覚えた盆踊りに行きます",
        })
        candidates = aggregate_event_candidates([evidence], {})
        self.assertEqual(evidence["estimated_event"], "")
        self.assertEqual(evidence["suppressed_event_hints"], ["今日は盆踊り仲間となんとなく覚えた盆踊り"])
        self.assertEqual(candidates, [])

    def test_specific_event_anchor_is_not_suppressed_as_fragment(self):
        evidence = classify_event_evidence({
            "account": "@fan",
            "date": "2026-06-13T10:00:00+00:00",
            "tweet_id": "997",
            "url": "https://x.com/fan/status/997",
            "text": "神田明神アニソン盆踊りに行きます",
        })
        self.assertEqual(evidence["estimated_event"], "神田明神アニソン盆踊り")
        self.assertEqual(evidence["normalized_event"], "神田明神アニソン")

    def test_classifies_non_bon_named_dance_event_with_song_context(self):
        evidence = classify_event_evidence({
            "account": "@fan",
            "date": "2026-06-13T10:00:00+00:00",
            "tweet_id": "996",
            "url": "https://x.com/fan/status/996",
            "text": "中央公園納涼祭に参加します。曲目は東京音頭、炭坑節。7月20日開催",
        })

        self.assertEqual(evidence["estimated_event"], "中央公園納涼祭")
        self.assertEqual(evidence["normalized_event"], "中央公園")
        self.assertIn("納涼祭", evidence["bon_context_hits"])
        self.assertNotIn("weak_bon_context:-3", evidence["score_reasons"])

    def test_classifies_yusuzumi_event_when_dance_context_is_present(self):
        evidence = classify_event_evidence({
            "account": "@fan",
            "date": "2026-06-13T10:00:00+00:00",
            "tweet_id": "995",
            "url": "https://x.com/fan/status/995",
            "text": "町会の夕涼み会に行きます。東京音頭を踊ります。7月20日 中央公園",
        })

        self.assertEqual(evidence["estimated_event"], "町会の夕涼み会")
        self.assertIn("夕涼み会", evidence["bon_context_hits"])
        self.assertNotIn("weak_bon_context:-3", evidence["score_reasons"])

    def test_soft_event_without_dance_context_stays_weak(self):
        evidence = classify_event_evidence({
            "account": "@fan",
            "date": "2026-06-13T10:00:00+00:00",
            "tweet_id": "993",
            "url": "https://x.com/fan/status/993",
            "text": "中央公園納涼祭に行きます。屋台が楽しみです。7月20日開催",
        })

        self.assertEqual(evidence["estimated_event"], "中央公園納涼祭")
        self.assertEqual(evidence["bon_context_hits"], [])
        self.assertIn("weak_bon_context:-3", evidence["score_reasons"])

    def test_event_normalization_strips_noise_prefixes(self):
        self.assertEqual(normalize_event_name("演目・大の坂踊り"), "大の坂踊り")
        self.assertEqual(normalize_event_name("回かすがい郡上おどり"), "かすがい郡上踊り")

    def test_venue_hint_strips_leading_date_text(self):
        evidence = classify_event_evidence({
            "account": "@fan",
            "date": "2026-06-13T10:00:00+00:00",
            "tweet_id": "994",
            "url": "https://x.com/fan/status/994",
            "text": "7月4日は辻堂駅北口神台公園の盆踊りに行きます",
        })

        self.assertEqual(evidence["estimated_venue"], "辻堂駅北口神台公園")

    def test_aggregates_evidence_and_scores_v2(self):
        first = classify_event_evidence({
            "account": "@a",
            "date": "2025-06-10T10:00:00+00:00",
            "tweet_id": "1",
            "url": "https://x.com/a/status/1",
            "text": "今年も浜町公園盆踊りに6月20日行きます",
        })
        second = classify_event_evidence({
            "account": "@b",
            "date": "2025-06-11T10:00:00+00:00",
            "tweet_id": "2",
            "url": "https://x.com/b/status/2",
            "text": "浜町公園盆踊り、6月20日開催情報です",
        })
        candidates = aggregate_event_candidates(
            [first, second],
            {"浜町公園": True},
        )
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["evidence_count"], 2)
        self.assertEqual(candidate["speaker_count"], 2)
        self.assertGreaterEqual(candidate["confidence_score"], 50)
        self.assertEqual(candidate["title"], "浜町公園盆踊り")
        self.assertEqual(candidate["evidence"][0]["dancer_key"], "@a")
        self.assertEqual(candidate["evidence"][0]["observed_at"], "2025-06-10T10:00:00+00:00")

    def test_aggregates_generic_event_by_same_venue_and_month(self):
        first = classify_event_evidence({
            "account": "@a",
            "date": "2025-06-10T10:00:00+00:00",
            "tweet_id": "1",
            "url": "https://x.com/a/status/1",
            "text": "中央公園の祭りと盆踊りに6月20日行きます",
        })
        second = classify_event_evidence({
            "account": "@b",
            "date": "2025-06-11T10:00:00+00:00",
            "tweet_id": "2",
            "url": "https://x.com/b/status/2",
            "text": "中央公園の盆踊り、6月21日開催情報です",
        })
        candidates = aggregate_event_candidates([first, second], {})
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["estimated_event"], "")
        self.assertEqual(candidates[0]["estimated_venue"], "中央公園")
        self.assertEqual(candidates[0]["estimated_month"], "06")
        self.assertEqual(candidates[0]["evidence_count"], 2)

    def test_initial_window_is_previous_year_and_fourteen_days(self):
        start, end = build_initial_window(
            datetime(2026, 6, 7, 12, tzinfo=timezone.utc), days=14
        )
        self.assertEqual(start.isoformat(), "2025-06-07T00:00:00+00:00")
        self.assertEqual((end - start).days, 14)

    def test_history_query_has_unfiltered_accounts_and_half_open_window(self):
        start = datetime(2025, 6, 7, tzinfo=timezone.utc)
        end = datetime(2025, 6, 21, tzinfo=timezone.utc)
        query = build_history_query(["@a", "b"], start, end)
        self.assertIn("(from:a OR from:b)", query)
        self.assertIn("since:2025-06-07_00:00:00_UTC", query)
        self.assertIn("until:2025-06-21_00:00:00_UTC", query)
        self.assertNotIn("盆踊り", query)

    def test_account_threshold_includes_minus_point_six_and_manual_priority(self):
        accounts = [
            {"handle": "@included", "manual_status": ""},
            {"handle": "@excluded", "manual_status": ""},
            {"handle": "@priority", "manual_status": "優先"},
            {"handle": "@paused", "manual_status": "休止"},
        ]
        scores = {
            "accounts": {
                "included": {"score": -0.6},
                "excluded": {"score": -0.7},
                "priority": {"score": -10},
                "paused": {"score": 20},
            }
        }
        with patch.object(collect, "_load_x_account_scores", return_value=scores):
            selected = collect._event_evidence_accounts(
                accounts, {"event_evidence": {
                    "min_account_score": -0.6,
                    "cohort_file": "/missing/cohort.json",
                }}
            )
        self.assertEqual(selected, ["@included", "@priority"])

    def test_frozen_cohort_is_used_exactly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "cohort.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({
                    "expected_count": 2,
                    "handles": ["@b", "@a"],
                }, f)
            selected = collect._event_evidence_accounts([], {
                "event_evidence": {"cohort_file": path}
            })
        self.assertEqual(selected, ["@a", "@b"])

    def test_clears_pending_only_after_queue_delivery(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "state.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({
                    "status": "in_progress",
                    "pending_evidence": [{"identity": "evidence:1"}],
                }, f)
            with patch.object(collect, "X_EVENT_EVIDENCE_STATE_FILE", path):
                collect._clear_pending_event_evidence()
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
        self.assertEqual(state["pending_evidence"], [])
        self.assertIn("pending_cleared_at", state)


if __name__ == "__main__":
    unittest.main()
