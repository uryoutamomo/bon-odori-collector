import copy
import unittest
from pathlib import Path

from review_inbox_adapters.parity import build_parity_report, item_payload_hash
from review_inbox_adapters.source_adapter import LIFECYCLE_FIELDS, adapt_source_payload, input_sha256
from review_inbox_adapters.youtube_adapter import (
    YouTubeActiveVideoAdapter,
    build_snapshot,
    has_structured_song_evidence,
    normalize_song_text,
)


FIXTURE = Path(__file__).parent / "fixtures" / "youtube_active_video_review_examples.json"
KNOWN_SONGS = {normalize_song_text("東京音頭"): "東京音頭"}


class ReviewInboxYouTubeAdapterTest(unittest.TestCase):
    def test_fixture_matches_legacy_pending_boundary_and_zero_diff_parity(self):
        snapshot = build_snapshot(FIXTURE, known_song_terms=KNOWN_SONGS)

        self.assertEqual(snapshot["source_id"], "youtube_evidence")
        self.assertEqual(snapshot["item_count"], 3)
        self.assertEqual(snapshot["input_sha256"], input_sha256(FIXTURE.read_bytes()))
        self.assertEqual(snapshot["write_mode"], "snapshot_only_default_off")
        self.assertEqual(snapshot["selection"]["mode"], "all")
        self.assertEqual({item["kind"] for item in snapshot["items"]}, {"youtube_evidence"})
        self.assertEqual({item["time_scope"] for item in snapshot["items"]}, {"historical"})
        self.assertEqual(
            [item["recommended_action"] for item in snapshot["items"]],
            ["needs_research", "add_song_evidence", "add_song_evidence"],
        )
        self.assertEqual(
            snapshot["selection"]["source_keys"],
            [
                "video:pending-official|year:2025",
                "video:pending-evidence|year:2025",
                "video:pending-component|year:2025",
            ],
        )
        for item in snapshot["items"]:
            self.assertFalse(LIFECYCLE_FIELDS.intersection(item))

        report = build_parity_report([snapshot], {"items": copy.deepcopy(snapshot["items"])})
        self.assertTrue(report["summary"]["parity"])
        self.assertEqual(report["summary"]["expected_count"], 3)

    def test_mutable_display_text_and_url_shape_do_not_change_identity(self):
        payload = {
            "rows": [{
                "video_id": "same-video",
                "video_url": "https://youtu.be/same-video?t=30",
                "title": "Before",
                "channel_title": "Before channel",
                "published_at": "2025-07-01T00:00:00Z",
                "detected_event_date": "2025-07-20",
                "action": "review_video_evidence",
            }]
        }
        before = adapt_source_payload(YouTubeActiveVideoAdapter(), payload)[0]
        changed = copy.deepcopy(payload)
        changed["rows"][0].update({
            "video_url": "https://www.youtube.com/watch?v=same-video&feature=share",
            "title": "After",
            "channel_title": "After channel",
            "detected_event_date": "2025-07-21",
        })
        after = adapt_source_payload(YouTubeActiveVideoAdapter(), changed)[0]

        self.assertEqual(before["source_key"], after["source_key"])
        self.assertEqual(before["inbox_id"], after["inbox_id"])
        self.assertNotEqual(item_payload_hash(before), item_payload_hash(after))

    def test_occurrence_or_year_changes_semantic_identity(self):
        row = {
            "video_id": "multi-target",
            "video_url": "https://www.youtube.com/watch?v=multi-target",
            "title": "Evidence",
            "detected_event_date": "2025-07-20",
            "action": "review_video_evidence",
        }
        by_year = adapt_source_payload(YouTubeActiveVideoAdapter(), {"rows": [row]})[0]
        by_occurrence = adapt_source_payload(
            YouTubeActiveVideoAdapter(),
            {"rows": [{**row, "matched_public_event": {"id": "occ-2025", "name": "Event"}}]},
        )[0]
        next_year = adapt_source_payload(
            YouTubeActiveVideoAdapter(),
            {"rows": [{**row, "detected_event_date": "2026-07-20"}]},
        )[0]

        self.assertNotEqual(by_year["inbox_id"], by_occurrence["inbox_id"])
        self.assertNotEqual(by_year["inbox_id"], next_year["inbox_id"])

    def test_structured_song_or_setlist_matches_legacy_auto_close_boundary(self):
        self.assertTrue(has_structured_song_evidence({"songs": ["未登録曲"]}))
        self.assertTrue(
            has_structured_song_evidence(
                {"setlist_occurrences": [{"setlist": [{"song_name": "未登録曲"}]}]}
            )
        )
        self.assertFalse(
            has_structured_song_evidence(
                {"setlist_occurrences": [{"song_count": 1, "setlist": []}]}
            )
        )

    def test_closed_action_is_skipped_but_unknown_action_and_invalid_rows_fail_closed(self):
        closed = {
            "rows": [{"video_id": "ignored", "title": "Ignored", "action": "ignore"}]
        }
        self.assertEqual(adapt_source_payload(YouTubeActiveVideoAdapter(), closed), [])

        with self.assertRaisesRegex(ValueError, "unsupported YouTube active video action"):
            adapt_source_payload(
                YouTubeActiveVideoAdapter(),
                {"rows": [{"video_id": "unknown", "title": "Unknown", "action": "publish_now"}]},
            )

        mismatch = {
            "rows": [{
                "video_id": "one",
                "video_url": "https://www.youtube.com/watch?v=two",
                "title": "Mismatch",
                "action": "review_video_evidence",
            }]
        }
        with self.assertRaisesRegex(ValueError, "does not match"):
            adapt_source_payload(YouTubeActiveVideoAdapter(), mismatch)

    def test_duplicate_video_and_target_fail_closed_across_url_variants(self):
        first = {
            "video_id": "duplicate",
            "video_url": "https://youtu.be/duplicate",
            "title": "One",
            "detected_event_date": "2025-07-20",
            "action": "review_video_evidence",
        }
        duplicate = {**first, "video_url": "https://www.youtube.com/watch?v=duplicate", "title": "Two"}
        with self.assertRaisesRegex(ValueError, "duplicate stable ids"):
            adapt_source_payload(YouTubeActiveVideoAdapter(), {"rows": [first, duplicate]})


if __name__ == "__main__":
    unittest.main()
