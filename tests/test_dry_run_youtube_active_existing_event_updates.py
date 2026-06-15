import unittest

from dry_run_youtube_active_existing_event_updates import build_groups, proposed_note, row_status


class DryRunYoutubeActiveExistingEventUpdatesTest(unittest.TestCase):
    def test_groups_multiple_videos_by_event_and_occurrence(self):
        groups = build_groups({
            "rows": [
                {
                    "action": "append_existing_event",
                    "video_url": "https://www.youtube.com/watch?v=aaa",
                    "title": "東京音頭",
                    "channel_title": "和太鼓",
                    "published_at": "2026-06-13",
                    "detected_event_date": "2026-06-13",
                    "matched_public_event": {"name": "山王音頭と民踊大会"},
                    "setlist_occurrences": [{"occurrence_key": "occ1", "event_name": "山王音頭と民踊大会"}],
                },
                {
                    "action": "append_existing_event",
                    "video_url": "https://www.youtube.com/watch?v=bbb",
                    "title": "炭坑節",
                    "channel_title": "和太鼓",
                    "published_at": "2026-06-13",
                    "detected_event_date": "2026-06-13",
                    "matched_public_event": {"name": "山王音頭と民踊大会"},
                    "setlist_occurrences": [{"occurrence_key": "occ1", "event_name": "山王音頭と民踊大会"}],
                },
            ]
        })

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["target_event_name"], "山王音頭と民踊大会")
        self.assertEqual(len(groups[0]["videos"]), 2)

    def test_proposed_note_uses_occurrence_songs(self):
        note = proposed_note(
            {
                "target_event_name": "山王音頭と民踊大会",
                "event_date": "2026-06-13",
                "videos": [{"url": "https://www.youtube.com/watch?v=aaa", "channel": "和太鼓", "title": "東京音頭"}],
                "official_urls": [],
                "occurrence_key": "occ1",
            },
            {
                "occ1": {
                    "setlist": [
                        {"title": "東京音頭"},
                        {"title": "炭坑節"},
                    ]
                }
            },
        )

        self.assertIn("[youtube_evidence]", note)
        self.assertIn("東京音頭, 炭坑節", note)

    def test_row_status_detects_duplicate_urls(self):
        status, warnings, would_change = row_status(
            {"id": "page"},
            "existing https://www.youtube.com/watch?v=aaa",
            "new note",
            [{"url": "https://www.youtube.com/watch?v=aaa"}],
        )

        self.assertEqual(status, "done")
        self.assertFalse(would_change)
        self.assertIn("同じYouTube URL", warnings[0])


if __name__ == "__main__":
    unittest.main()
