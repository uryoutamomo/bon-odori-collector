import unittest

from legacy.notion_writes.apply_youtube_active_existing_event_updates import (
    build_updates,
    event_summary_note,
    has_existing_youtube_summary,
    rich_text_prop,
    skipped_rows,
)


class FakeApi:
    def __init__(self, pages):
        self.pages = pages

    def retrieve_page(self, page_id):
        return self.pages[page_id]


def page(detail=""):
    return {
        "id": "page-id",
        "properties": {
            "開催パターン詳細": {
                "type": "rich_text",
                "rich_text": [{"plain_text": detail}],
            }
        },
    }


class ApplyYoutubeActiveExistingEventUpdatesTest(unittest.TestCase):
    def test_summarizes_multiple_ready_rows_into_one_event_note(self):
        note, videos, songs = event_summary_note(
            "山王音頭と民踊大会",
            [
                {
                    "event_date": "2026-06-13",
                    "videos": [
                        {"url": "https://www.youtube.com/watch?v=aaa", "channel": "和太鼓", "title": "東京音頭"}
                    ],
                    "songs": ["東京音頭", "炭坑節"],
                },
                {
                    "event_date": "2026-06-14",
                    "videos": [
                        {"url": "https://www.youtube.com/watch?v=bbb", "channel": "祭のきせき", "title": "後半"}
                    ],
                    "songs": ["東京音頭"],
                },
            ],
        )

        self.assertIn("2026-06-13, 2026-06-14", note)
        self.assertIn("動画数: 2", note)
        self.assertIn("東京音頭, 炭坑節", note)
        self.assertEqual(len(videos), 2)
        self.assertEqual(songs, ["東京音頭", "炭坑節"])

    def test_builds_one_update_per_event(self):
        plan = {
            "rows": [
                {
                    "status": "ready",
                    "target_event_name": "山王音頭と民踊大会",
                    "target_page_id": "page-id",
                    "target_page_url": "https://app.notion.com/p/page",
                    "event_date": "2026-06-13",
                    "videos": [{"url": "https://www.youtube.com/watch?v=aaa", "channel": "和太鼓", "title": "東京音頭"}],
                    "songs": ["東京音頭"],
                },
                {
                    "status": "ready",
                    "target_event_name": "山王音頭と民踊大会",
                    "target_page_id": "page-id",
                    "target_page_url": "https://app.notion.com/p/page",
                    "event_date": "2026-06-14",
                    "videos": [{"url": "https://www.youtube.com/watch?v=bbb", "channel": "祭のきせき", "title": "後半"}],
                    "songs": [],
                },
            ]
        }

        updates = build_updates(FakeApi({"page-id": page("既存詳細")}), plan)

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["input_rows"], 2)
        self.assertEqual(updates[0]["video_count"], 2)
        self.assertTrue(updates[0]["changed"])
        content = updates[0]["properties"]["開催パターン詳細"]["rich_text"][0]["text"]["content"]
        self.assertIn("既存詳細", content)
        self.assertIn("[youtube_evidence]", content)

    def test_does_not_change_when_all_urls_already_exist(self):
        plan = {
            "rows": [
                {
                    "status": "ready",
                    "target_event_name": "山王音頭と民踊大会",
                    "target_page_id": "page-id",
                    "videos": [{"url": "https://www.youtube.com/watch?v=aaa", "channel": "和太鼓", "title": "東京音頭"}],
                    "songs": ["東京音頭"],
                }
            ]
        }

        updates = build_updates(
            FakeApi({"page-id": page("既存 https://www.youtube.com/watch?v=aaa")}),
            plan,
        )

        self.assertFalse(updates[0]["changed"])
        self.assertTrue(updates[0]["all_urls_duplicate"])

    def test_reports_skipped_blocked_rows(self):
        plan = {
            "rows": [
                {
                    "status": "blocked",
                    "target_event_name": "国立旭通りジューンフェスタ盆踊り",
                    "warnings": ["Notionイベントページが見つかりません"],
                    "video_count": 1,
                    "song_count": 12,
                }
            ]
        }

        rows = skipped_rows(plan)

        self.assertEqual(rows[0]["status"], "blocked")
        self.assertIn("Notionイベントページ", rows[0]["reason"])

    def test_splits_long_rich_text(self):
        prop = rich_text_prop("a" * 2001)

        self.assertEqual(len(prop["rich_text"]), 2)
        self.assertEqual(len(prop["rich_text"][0]["text"]["content"]), 1900)

    def test_detects_existing_youtube_summary_for_same_event(self):
        detail = "\n".join(
            [
                "[youtube_evidence] YouTube実績証拠",
                "- 対象イベント: シタマチ.ふるさと盆踊り大会",
                "- 動画数: 79",
            ]
        )

        self.assertTrue(has_existing_youtube_summary(detail, "シタマチ.ふるさと盆踊り大会"))

    def test_does_not_match_other_event_summary(self):
        detail = "\n".join(
            [
                "[youtube_evidence] YouTube実績証拠",
                "- 対象イベント: 別イベント",
                "- 動画数: 79",
            ]
        )

        self.assertFalse(has_existing_youtube_summary(detail, "シタマチ.ふるさと盆踊り大会"))

    def test_does_not_change_when_summary_for_same_event_already_exists(self):
        plan = {
            "rows": [
                {
                    "status": "ready",
                    "target_event_name": "シタマチ.ふるさと盆踊り大会",
                    "target_page_id": "page-id",
                    "videos": [{"url": "https://www.youtube.com/watch?v=new", "channel": "和太鼓", "title": "東京音頭"}],
                    "songs": ["東京音頭"],
                }
            ]
        }
        existing = "\n".join(
            [
                "[youtube_evidence] YouTube実績証拠",
                "- 対象イベント: シタマチ.ふるさと盆踊り大会",
                "- 動画数: 79",
            ]
        )

        updates = build_updates(FakeApi({"page-id": page(existing)}), plan)

        self.assertFalse(updates[0]["changed"])
        self.assertTrue(updates[0]["summary_present"])


if __name__ == "__main__":
    unittest.main()
