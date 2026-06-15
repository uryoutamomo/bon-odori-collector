import unittest

from dry_run_youtube_active_existing_event_updates import build_groups, find_event, proposed_note, row_status


class FakeApi:
    def __init__(self, rows_by_name):
        self.rows_by_name = rows_by_name
        self.queries = []

    def query_data_source(self, data_source_id, payload):
        name = payload["filter"]["title"]["equals"]
        self.queries.append(name)
        return self.rows_by_name.get(name, [])


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

    def test_row_status_detects_event_level_youtube_evidence(self):
        status, warnings, would_change = row_status(
            {"id": "page"},
            "[youtube_evidence] YouTube実績証拠\n- 対象イベント: 山王音頭と民踊大会\n- 検出日付: 2026-06-13, 2026-06-14",
            "new note",
            [{"url": "https://www.youtube.com/watch?v=aaa"}],
            event_name="山王音頭と民踊大会",
            event_date="2026-06-14",
        )

        self.assertEqual(status, "done")
        self.assertFalse(would_change)
        self.assertIn("同じイベント日付", warnings[0])

    def test_find_event_uses_aliases_for_kunitachi_june_festa(self):
        api = FakeApi({
            "ジューンフェスタ2026 盆踊り（国立市旭通り商店会）": [{"id": "page-id"}],
        })

        page = find_event(api, "国立旭通りジューンフェスタ盆踊り")

        self.assertEqual(page["id"], "page-id")
        self.assertIn("国立旭通りジューンフェスタ盆踊り", api.queries)
        self.assertIn("ジューンフェスタ2026 盆踊り（国立市旭通り商店会）", api.queries)


if __name__ == "__main__":
    unittest.main()
