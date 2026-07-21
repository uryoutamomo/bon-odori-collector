import copy
import unittest
from pathlib import Path

from review_inbox_adapters.parity import build_parity_report, item_payload_hash
from review_inbox_adapters.source_adapter import LIFECYCLE_FIELDS, adapt_source_payload, input_sha256
from review_inbox_adapters.youtube_user_confirmation_adapter import YouTubeUserConfirmationAdapter, build_snapshot


FIXTURE = Path(__file__).parent / "fixtures" / "youtube_user_confirmation_examples.json"


class ReviewInboxYouTubeUserConfirmationAdapterTest(unittest.TestCase):
    def test_fixture_emits_only_undecided_video_items(self):
        snapshot = build_snapshot(FIXTURE)
        self.assertEqual(snapshot["source_id"], "youtube_evidence")
        self.assertEqual(snapshot["item_count"], 2)
        self.assertEqual(snapshot["input_sha256"], input_sha256(FIXTURE.read_bytes()))
        self.assertEqual(snapshot["selection"]["mode"], "all")
        self.assertEqual(snapshot["selection"]["source_keys"], ["video:pending-user|year:2025", "video:pending-scope|year:2026"])
        self.assertEqual([item["recommended_action"] for item in snapshot["items"]], ["add_song_evidence", "needs_research"])
        for item in snapshot["items"]:
            self.assertEqual(item["time_scope"], "historical")
            self.assertFalse(LIFECYCLE_FIELDS.intersection(item))
        report = build_parity_report([snapshot], {"items": copy.deepcopy(snapshot["items"])})
        self.assertTrue(report["summary"]["parity"])

    def test_url_and_mutable_text_changes_keep_shared_identity(self):
        payload = {"items":[{"id":"candidate_2025","label":"Before","video_url":"https://youtu.be/same-user","detected_event_date":"2025-07-01","recommended_decision":"hold_until_official_confirmation","options":["hold_until_official_confirmation","exclude"]}]}
        before = adapt_source_payload(YouTubeUserConfirmationAdapter(), payload)[0]
        changed = copy.deepcopy(payload)
        changed["items"][0].update({"label":"After","video_url":"https://www.youtube.com/watch?v=same-user&feature=share","detected_event_date":"2025-07-02"})
        after = adapt_source_payload(YouTubeUserConfirmationAdapter(), changed)[0]
        self.assertEqual(before["inbox_id"], after["inbox_id"])
        self.assertNotEqual(item_payload_hash(before), item_payload_hash(after))

    def test_partial_decisions_invalid_options_and_missing_identity_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "partial YouTube confirmation decision"):
            adapt_source_payload(YouTubeUserConfirmationAdapter(), {"items":[{"current_decision":"exclude"}]})
        base = {"id":"pending_2025","label":"Pending","video_url":"https://youtu.be/pending","detected_event_date":"2025-01-01","recommended_decision":"exclude","options":["exclude"]}
        with self.assertRaisesRegex(ValueError, "unsupported YouTube confirmation recommendation"):
            adapt_source_payload(YouTubeUserConfirmationAdapter(), {"items":[{**base,"recommended_decision":"publish_now"}]})
        with self.assertRaisesRegex(ValueError, "unsupported YouTube confirmation options"):
            adapt_source_payload(YouTubeUserConfirmationAdapter(), {"items":[{**base,"options":["publish_now"]}]})
        with self.assertRaisesRegex(ValueError, "requires a YouTube video URL"):
            adapt_source_payload(YouTubeUserConfirmationAdapter(), {"items":[{**base,"video_url":""}]})
        with self.assertRaisesRegex(ValueError, "video_id does not match video_url"):
            adapt_source_payload(YouTubeUserConfirmationAdapter(), {"items":[{**base,"video_id":"different"}]})
        with self.assertRaisesRegex(ValueError, "requires a target year"):
            adapt_source_payload(YouTubeUserConfirmationAdapter(), {"items":[{**base,"id":"pending","detected_event_date":""}]})

    def test_matching_supplied_video_id_cannot_override_canonical_payload(self):
        payload = {"items":[{"id":"pending_2025","label":"Pending","video_url":"https://youtu.be/pending","video_id":"pending","detected_event_date":"2025-01-01","recommended_decision":"exclude","options":["exclude"]}]}
        item = adapt_source_payload(YouTubeUserConfirmationAdapter(), payload)[0]
        self.assertEqual(item["payload"]["video_id"], "pending")
        self.assertEqual(item["payload"]["origin_queue"], "youtube_user_confirmation")

    def test_current_real_queue_is_fully_decided(self):
        current = Path(__file__).resolve().parents[1] / "data/youtube_user_confirmation_queue.json"
        self.assertEqual(build_snapshot(current)["item_count"], 0)


if __name__ == "__main__":
    unittest.main()
