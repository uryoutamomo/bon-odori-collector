import unittest

from legacy.notion_writes.apply_youtube_review_video_evidence import (
    build_updates,
    classify_row,
    grouped_ready,
)


class FakeApi:
    def __init__(self, pages=None):
        self.pages = pages or {
            "自由が丘納涼盆踊り大会": {
                "id": "jiyugaoka-page-id",
                "url": "https://app.notion.com/p/jiyugaoka",
                "properties": {
                    "開催パターン詳細": {
                        "type": "rich_text",
                        "rich_text": [{"plain_text": "existing"}],
                    }
                },
            },
            "丸の内de盆踊り": {
                "id": "marunouchi-page-id",
                "url": "https://app.notion.com/p/marunouchi",
                "properties": {
                    "開催パターン詳細": {
                        "type": "rich_text",
                        "rich_text": [{"plain_text": "existing"}],
                    }
                },
            },
        }

    def query_data_source(self, data_source_id, payload):
        name = payload["filter"]["title"]["equals"]
        page = self.pages.get(name)
        return [page] if page else []


def row(title, url):
    return {
        "action": "review_video_evidence",
        "video_url": url,
        "title": title,
        "channel_title": "yt",
        "published_at": "2025-07-27T00:00:00+00:00",
        "detected_event_date": "",
    }


class ApplyYoutubeReviewVideoEvidenceTest(unittest.TestCase):
    def test_classifies_jiyugaoka_as_append_existing_event(self):
        result = classify_row(row("自由が丘小唄 #盆踊り", "https://www.youtube.com/shorts/aaa"))

        self.assertEqual(result["decision"], "append_existing_event")
        self.assertEqual(result["target_event_name"], "自由が丘納涼盆踊り大会")

    def test_classifies_marunouchi_as_append_existing_event(self):
        result = classify_row(row("丸の内盆踊り Shorts", "https://www.youtube.com/shorts/bbb"))

        self.assertEqual(result["decision"], "append_existing_event")
        self.assertEqual(result["target_event_name"], "丸の内de盆踊り")

    def test_classifies_shibuya_as_hold(self):
        result = classify_row(row("Shibuya Bon Odori Dance festival 2025", "https://www.youtube.com/shorts/ccc"))

        self.assertEqual(result["decision"], "hold")
        self.assertEqual(result["target_event_name"], "渋谷盆踊り2025")
        self.assertIn("公式確認", result["reason"])

    def test_groups_ready_and_held_rows(self):
        grouped, held = grouped_ready([
            row("自由が丘小唄 #盆踊り", "https://www.youtube.com/shorts/aaa"),
            row("丸の内盆踊り Shorts", "https://www.youtube.com/shorts/bbb"),
            row("Shibuya Bon Odori Dance festival 2025", "https://www.youtube.com/shorts/ccc"),
        ])

        self.assertEqual(len(grouped["自由が丘納涼盆踊り大会"]), 1)
        self.assertEqual(len(grouped["丸の内de盆踊り"]), 1)
        self.assertEqual(len(held), 1)

    def test_builds_updates_for_existing_events(self):
        review = {
            "rows": [
                row("自由が丘小唄 #盆踊り", "https://www.youtube.com/shorts/aaa"),
                row("丸の内盆踊り Shorts", "https://www.youtube.com/shorts/bbb"),
                row("丸の内盆踊り Part2", "https://www.youtube.com/shorts/ccc"),
                row("Shibuya Bon Odori Dance festival 2025", "https://www.youtube.com/shorts/ddd"),
            ]
        }

        updates, held = build_updates(FakeApi(), review)

        by_event = {row["target_event_name"]: row for row in updates}
        self.assertEqual(by_event["自由が丘納涼盆踊り大会"]["video_count"], 1)
        self.assertEqual(by_event["丸の内de盆踊り"]["video_count"], 2)
        self.assertTrue(by_event["自由が丘納涼盆踊り大会"]["changed"])
        self.assertTrue(by_event["丸の内de盆踊り"]["changed"])
        self.assertEqual(len(held), 1)

    def test_duplicate_urls_do_not_change_detail(self):
        review = {
            "rows": [
                row("丸の内盆踊り Shorts", "https://www.youtube.com/shorts/bbb"),
            ]
        }
        page = {
            "丸の内de盆踊り": {
                "id": "marunouchi-page-id",
                "url": "https://app.notion.com/p/marunouchi",
                "properties": {
                    "開催パターン詳細": {
                        "type": "rich_text",
                        "rich_text": [{"plain_text": "existing https://www.youtube.com/shorts/bbb"}],
                    }
                },
            }
        }

        updates, held = build_updates(FakeApi(page), review)

        self.assertFalse(updates[0]["changed"])
        self.assertEqual(updates[0]["duplicate_url_count"], 1)
        self.assertEqual(held, [])


if __name__ == "__main__":
    unittest.main()
