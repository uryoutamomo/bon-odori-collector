import copy
import unittest
from pathlib import Path

from review_inbox_parity import build_parity_report, item_payload_hash
from review_inbox_source_adapter import LIFECYCLE_FIELDS, adapt_source_payload, input_sha256
from review_inbox_youtube_year_backfill_adapter import YouTubeYearBackfillAdapter, build_snapshot


FIXTURE = Path(__file__).parent / "fixtures" / "youtube_year_backfill_review_examples.json"


class ReviewInboxYouTubeYearBackfillAdapterTest(unittest.TestCase):
    def test_fixture_emits_only_undecided_videos_with_shared_youtube_identity(self):
        snapshot = build_snapshot(FIXTURE)
        self.assertEqual(snapshot["source_id"], "youtube_evidence")
        self.assertEqual(snapshot["item_count"], 3)
        self.assertEqual(snapshot["input_sha256"], input_sha256(FIXTURE.read_bytes()))
        self.assertEqual(snapshot["selection"]["mode"], "all")
        self.assertEqual({item["time_scope"] for item in snapshot["items"]}, {"historical"})
        self.assertEqual(snapshot["selection"]["source_keys"], ["video:year-one|year:2024", "video:year-two|year:2024", "video:year-mismatch|year:2024"])
        self.assertEqual([item["recommended_action"] for item in snapshot["items"]], ["add_song_evidence", "add_song_evidence", "needs_research"])
        for item in snapshot["items"]:
            self.assertFalse(LIFECYCLE_FIELDS.intersection(item))
        report = build_parity_report([snapshot], {"items": copy.deepcopy(snapshot["items"])})
        self.assertTrue(report["summary"]["parity"])

    def test_url_shape_and_mutable_group_text_do_not_change_identity(self):
        payload = {"groups": [{"event_name":"Before","venue":"Before venue","target_year":2024,"candidate_action":"merge_to_existing_candidate","existing_decision":None,"videos":[{"title":"Before","url":"https://youtu.be/same-year-video","score":70}]}]}
        before = adapt_source_payload(YouTubeYearBackfillAdapter(), payload)[0]
        changed = copy.deepcopy(payload)
        changed["groups"][0].update({"event_name":"After","venue":"After venue"})
        changed["groups"][0]["videos"][0].update({"title":"After","url":"https://www.youtube.com/watch?v=same-year-video&feature=share"})
        after = adapt_source_payload(YouTubeYearBackfillAdapter(), changed)[0]
        self.assertEqual(before["inbox_id"], after["inbox_id"])
        self.assertNotEqual(item_payload_hash(before), item_payload_hash(after))

    def test_same_video_and_year_matches_active_adapter_identity(self):
        payload = {"groups": [{"event_name":"Event","target_year":2025,"candidate_action":"single_video_hold","existing_decision":None,"videos":[{"title":"Video","url":"https://youtu.be/shared-video"}]}]}
        item = adapt_source_payload(YouTubeYearBackfillAdapter(), payload)[0]
        self.assertEqual(item["source_key"], "video:shared-video|year:2025")

    def test_decision_invariants_unknown_actions_and_duplicates_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "requires existing_decision"):
            adapt_source_payload(YouTubeYearBackfillAdapter(), {"groups":[{"candidate_action":"already_decided","existing_decision":None}]})
        with self.assertRaisesRegex(ValueError, "unsupported YouTube year backfill action"):
            adapt_source_payload(YouTubeYearBackfillAdapter(), {"groups":[{"candidate_action":"publish_now","existing_decision":None}]})
        group = {"event_name":"Duplicate","target_year":2024,"candidate_action":"hold_or_reject","existing_decision":None,"videos":[{"title":"One","url":"https://youtu.be/duplicate-year"},{"title":"Two","url":"https://www.youtube.com/watch?v=duplicate-year"}]}
        with self.assertRaisesRegex(ValueError, "duplicate stable ids"):
            adapt_source_payload(YouTubeYearBackfillAdapter(), {"groups":[group]})

    def test_current_real_queue_has_no_undecided_groups(self):
        current = Path(__file__).resolve().parents[1] / "data/youtube_year_backfill_review_queue.json"
        self.assertEqual(build_snapshot(current)["item_count"], 0)


if __name__ == "__main__":
    unittest.main()
