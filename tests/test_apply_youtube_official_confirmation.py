import unittest

from legacy.notion_writes.apply_youtube_official_confirmation import (
    build_updates,
    classify_row,
    grouped_ready,
)


class FakeApi:
    def __init__(self, page=None):
        self.page = page or {
            "id": "page-id",
            "url": "https://app.notion.com/p/page",
            "properties": {
                "開催パターン詳細": {
                    "type": "rich_text",
                    "rich_text": [{"plain_text": "existing"}],
                }
            },
        }

    def query_data_source(self, data_source_id, payload):
        name = payload["filter"]["title"]["equals"]
        if name == "丸の内de盆踊り":
            return [self.page]
        return []


def row(title, url, official_urls=None):
    return {
        "action": "needs_official_confirmation",
        "video_url": url,
        "title": title,
        "channel_title": "Exploring Japan with Zen",
        "published_at": "2025-07-27T00:00:00+00:00",
        "detected_event_date": "2025-07-26",
        "official_urls": official_urls or [],
    }


class ApplyYoutubeOfficialConfirmationTest(unittest.TestCase):
    def test_classifies_marunouchi_as_append_existing_event(self):
        result = classify_row(row(
            "Marunouchi Bon Odori Dance festival",
            "https://www.youtube.com/watch?v=aaa",
            ["https://www.marunouchi.com/pickup/event/6763/"],
        ))

        self.assertEqual(result["decision"], "append_existing_event")
        self.assertEqual(result["target_event_name"], "丸の内de盆踊り")

    def test_classifies_shibuya_as_hold_when_official_body_unreadable(self):
        result = classify_row(row(
            "Shibuya Bon Odori Dance festival 2025",
            "https://www.youtube.com/watch?v=bbb",
            ["https://shibuyadogenzaka.com/?p=6827"],
        ))

        self.assertEqual(result["decision"], "hold")
        self.assertIn("本文取得不可", result["reason"])

    def test_groups_ready_and_held_rows(self):
        grouped, held = grouped_ready([
            row("Marunouchi Bon Odori Dance festival", "https://www.youtube.com/watch?v=aaa", ["https://www.marunouchi.com/pickup/event/6763/"]),
            row("Shibuya Bon Odori Dance festival 2025", "https://www.youtube.com/watch?v=bbb", ["https://shibuyadogenzaka.com/?p=6827"]),
        ])

        self.assertEqual(len(grouped["丸の内de盆踊り"]), 1)
        self.assertEqual(len(held), 1)

    def test_builds_update_for_existing_marunouchi_event(self):
        review = {
            "rows": [
                row("Marunouchi Bon Odori Dance festival", "https://www.youtube.com/watch?v=aaa", ["https://www.marunouchi.com/pickup/event/6763/"]),
                row("Marunouchi Bon Odori Dance festival PART 2", "https://www.youtube.com/watch?v=bbb", ["https://www.marunouchi.com/pickup/event/6763/"]),
            ]
        }

        updates, held = build_updates(FakeApi(), review)

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["apply_status"], "ready")
        self.assertEqual(updates[0]["video_count"], 2)
        self.assertTrue(updates[0]["changed"])
        self.assertEqual(held, [])


if __name__ == "__main__":
    unittest.main()
