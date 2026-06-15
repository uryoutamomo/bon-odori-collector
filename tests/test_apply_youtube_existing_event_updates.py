import unittest

from apply_youtube_existing_event_updates import build_updates


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


class ApplyYoutubeExistingEventUpdatesTest(unittest.TestCase):
    def test_builds_ready_update_from_dry_run_row(self):
        plan = {
            "rows": [
                {
                    "candidate_key": "yt1",
                    "status": "ready",
                    "target_event_name": "自由が丘納涼盆踊り大会",
                    "target_page_id": "page-id",
                    "source_video_url": "https://www.youtube.com/watch?v=abc",
                    "proposed_note": "[youtube_evidence] 2025実績証拠",
                }
            ]
        }

        rows = build_updates(FakeApi({"page-id": page("既存詳細")}), plan)

        self.assertEqual(rows[0]["apply_status"], "ready")
        self.assertTrue(rows[0]["changed"])
        content = rows[0]["properties"]["開催パターン詳細"]["rich_text"][0]["text"]["content"]
        self.assertIn("既存詳細", content)
        self.assertIn("[youtube_evidence]", content)

    def test_skips_non_ready_rows_and_event_name_mismatch(self):
        plan = {
            "rows": [
                {
                    "candidate_key": "yt1",
                    "status": "review",
                    "target_event_name": "歌舞伎町BON ODORI",
                    "target_page_id": "page-id",
                },
                {
                    "candidate_key": "yt2",
                    "status": "ready",
                    "target_event_name": "自由が丘納涼盆踊り大会",
                    "target_page_id": "page-id",
                    "proposed_note": "note",
                },
            ]
        }

        rows = build_updates(
            FakeApi({"page-id": page()}),
            plan,
            event_name="自由が丘納涼盆踊り大会",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["target_event_name"], "自由が丘納涼盆踊り大会")
        self.assertEqual(rows[0]["apply_status"], "ready")

    def test_does_not_duplicate_existing_video_url(self):
        plan = {
            "rows": [
                {
                    "candidate_key": "yt1",
                    "status": "ready",
                    "target_event_name": "自由が丘納涼盆踊り大会",
                    "target_page_id": "page-id",
                    "source_video_url": "https://www.youtube.com/watch?v=abc",
                    "proposed_note": "[youtube_evidence] https://www.youtube.com/watch?v=abc",
                }
            ]
        }

        rows = build_updates(
            FakeApi({"page-id": page("既存 https://www.youtube.com/watch?v=abc")}),
            plan,
        )

        self.assertEqual(rows[0]["apply_status"], "ready")
        self.assertFalse(rows[0]["changed"])
        self.assertTrue(rows[0]["duplicate_url"])


if __name__ == "__main__":
    unittest.main()
