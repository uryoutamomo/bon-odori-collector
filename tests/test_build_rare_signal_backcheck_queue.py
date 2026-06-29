import unittest

from build_rare_signal_backcheck_queue import build


class BuildRareSignalBackcheckQueueTest(unittest.TestCase):
    def payload(self):
        return {
            "generated_at": "2026-06-27T00:00:00+00:00",
            "candidates": [
                {
                    "candidate_id": "xoto_event",
                    "source_urls": ["https://x.com/example/status/1"],
                    "promotion_target": "event",
                    "novelty_assessment": "new",
                    "possible_event_name": "佐竹ゲバゲバ盆踊り",
                    "possible_venue": "佐竹商店街",
                    "possible_area": "台東区",
                    "possible_date_text": "7月",
                    "possible_song_names": [],
                    "oto_interpreted_summary": "佐竹商店街で佐竹ゲバゲバ盆踊りの開催情報があり、新規候補として裏どりする。",
                    "novelty_reason": "既存DBに一致するイベントがない。",
                    "matched_existing_events": [],
                    "matched_existing_venues": [{"name": "佐竹商店街"}],
                    "web_backcheck_queries": ["佐竹ゲバゲバ盆踊り 台東区 盆踊り"],
                    "backcheck_status": "needs_backcheck",
                    "review_status": "needs_backcheck",
                },
                {
                    "candidate_id": "xoto_existing",
                    "source_urls": ["https://x.com/example/status/2"],
                    "promotion_target": "existing_evidence",
                    "novelty_assessment": "update",
                    "possible_event_name": "中野駅前大盆踊り大会",
                    "oto_interpreted_summary": "既存イベントへの日程証拠。",
                    "backcheck_status": "needs_backcheck",
                    "review_status": "needs_backcheck",
                },
            ],
        }

    def test_queues_all_registration_targets_by_default(self):
        result = build(self.payload())
        self.assertEqual(result["summary"]["queue_count"], 2)
        self.assertEqual(result["summary"]["skipped_count"], 0)
        row = result["queue"][0]
        self.assertEqual(row["candidate_id"], "xoto_event")
        self.assertEqual(row["backcheck_status"], "pending")
        self.assertEqual(row["source_policy"], "x_discovery_only_non_x_confirmation_required")
        self.assertEqual(row["next_action"], "find_non_x_confirmation")
        self.assertIn("official_or_organizer", row["suggested_source_types"])
        self.assertIn("佐竹ゲバゲバ盆踊り 台東区 盆踊り", row["search_queries"])
        self.assertIn("佐竹ゲバゲバ盆踊り 佐竹商店街 7月", row["search_queries"])

    def test_can_narrow_targets_when_requested(self):
        result = build(self.payload(), include_targets={"event"})
        self.assertEqual(result["summary"]["queue_count"], 1)
        self.assertEqual(result["summary"]["skipped_count"], 1)
        self.assertEqual(result["queue"][0]["promotion_target"], "event")

    def test_includes_song_candidates_by_default(self):
        payload = self.payload()
        payload["candidates"].append(
            {
                "candidate_id": "xoto_song",
                "source_urls": ["https://x.com/example/status/3"],
                "promotion_target": "song",
                "novelty_assessment": "new",
                "possible_song_names": ["白浜音頭"],
                "oto_interpreted_summary": "白浜音頭が曲候補として言及されている。",
                "backcheck_status": "needs_backcheck",
                "review_status": "needs_backcheck",
            }
        )
        result = build(payload)
        targets = {row["promotion_target"] for row in result["queue"]}
        self.assertIn("song", targets)

    def test_can_include_existing_evidence_when_requested(self):
        result = build(self.payload(), include_targets={"event", "existing_evidence"})
        self.assertEqual(result["summary"]["queue_count"], 2)
        targets = {row["promotion_target"] for row in result["queue"]}
        self.assertEqual(targets, {"event", "existing_evidence"})

    def test_skips_rows_that_are_not_waiting_for_backcheck(self):
        payload = self.payload()
        payload["candidates"][0]["backcheck_status"] = "confirmed"
        result = build(payload)
        self.assertEqual(result["summary"]["queue_count"], 1)
        self.assertEqual(result["skipped"][0]["reason"], "already_backchecked_or_not_pending")

    def test_includes_manual_x_missed_signal_payload(self):
        manual_payload = {
            "updated_at": "2026-06-27T01:00:00+00:00",
            "candidates": [
                {
                    "candidate_id": "manual_x_1",
                    "source_urls": ["https://x.com/kagurazaka_6/status/2067528339074830638"],
                    "source_authors": ["@kagurazaka_6"],
                    "promotion_target": "event",
                    "novelty_assessment": "unclear",
                    "possible_event_name": "神楽坂エリアの重要イベント情報",
                    "possible_area": "神楽坂",
                    "oto_interpreted_summary": "手動追加された重要なX見逃し投稿。非X根拠で裏どりする。",
                    "web_backcheck_queries": ["神楽坂 イベント 盆踊り 公式"],
                    "backcheck_status": "needs_backcheck",
                    "review_status": "needs_backcheck",
                }
            ],
        }
        result = build({"generated_at": "2026-06-27T00:00:00+00:00", "candidates": []}, manual_payload=manual_payload)
        self.assertEqual(result["summary"]["queue_count"], 1)
        row = result["queue"][0]
        self.assertEqual(row["candidate_id"], "manual_x_1")
        self.assertEqual(row["source_policy"], "x_discovery_only_non_x_confirmation_required")
        self.assertIn("神楽坂 イベント 盆踊り 公式", row["search_queries"])

    def test_registered_official_social_source_changes_policy(self):
        payload = {
            "generated_at": "2026-06-27T00:00:00+00:00",
            "candidates": [
                {
                    "candidate_id": "xoto_teppozu",
                    "source_urls": ["https://x.com/iri2choukai/status/2069959259895496872"],
                    "source_authors": ["@iri2choukai"],
                    "promotion_target": "event",
                    "novelty_assessment": "new",
                    "possible_event_name": "鉄砲洲納涼盆踊り",
                    "possible_venue": "鉄砲洲公園",
                    "possible_date_text": "2026年8月3日〜8月5日 18:45〜21:00",
                    "oto_interpreted_summary": "町会公式Xによる鉄砲洲納涼盆踊り告知。",
                    "backcheck_status": "needs_backcheck",
                    "review_status": "needs_backcheck",
                }
            ],
        }

        result = build(payload)
        row = result["queue"][0]

        self.assertEqual(row["source_policy"], "registered_official_social_review_required")
        self.assertEqual(row["confirmed_source_type"], "official_or_organizer_social")
        self.assertEqual(row["next_action"], "review_official_social_post")
        self.assertEqual(row["official_social_sources"][0]["handle"], "@iri2choukai")


if __name__ == "__main__":
    unittest.main()
