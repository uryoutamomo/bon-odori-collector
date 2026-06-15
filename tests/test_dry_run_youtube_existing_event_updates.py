import unittest

from dry_run_youtube_existing_event_updates import build_dry_run


class FakeApi:
    def __init__(self, pages):
        self.pages = pages

    def query_data_source(self, data_source_id, payload=None):
        title_filter = ((payload or {}).get("filter") or {}).get("title") or {}
        name = title_filter.get("equals") or ""
        page = self.pages.get(name)
        return [page] if page else []


def page(detail=""):
    return {
        "id": "page-id",
        "url": "https://notion.test/page-id",
        "properties": {
            "開催パターン詳細": {
                "type": "rich_text",
                "rich_text": [{"plain_text": detail}],
            }
        },
    }


class DryRunYoutubeExistingEventUpdatesTest(unittest.TestCase):
    def test_builds_ready_dry_run_for_existing_event(self):
        plan = {
            "rows": [
                {
                    "candidate_key": "yt1",
                    "action": "append_evidence_to_existing_event",
                    "youtube_event_date": "2025-07-21",
                    "source_video_url": "https://www.youtube.com/watch?v=abc",
                    "source_video_title": "自由が丘",
                    "source_channel_title": "channel",
                    "thumbnail_url": "https://img.example/thumb.jpg",
                    "matched_public_event": {
                        "name": "自由が丘納涼盆踊り大会",
                        "date": "2025-07-19",
                        "date_end": "2025-07-21",
                        "score": 75,
                    },
                    "songs": [
                        {"title": "東京音頭"},
                        {"title": "炭坑節"},
                    ],
                }
            ]
        }
        rows = build_dry_run(FakeApi({"自由が丘納涼盆踊り大会": page()}), plan)
        self.assertEqual(rows[0]["status"], "ready")
        self.assertTrue(rows[0]["would_change_detail"])
        self.assertIn("[youtube_evidence]", rows[0]["proposed_note"])

    def test_flags_missing_date_end_when_detail_covers_source_date(self):
        plan = {
            "rows": [
                {
                    "candidate_key": "yt1",
                    "action": "append_evidence_to_existing_event",
                    "youtube_event_date": "2025-07-21",
                    "source_video_url": "https://www.youtube.com/watch?v=abc",
                    "source_channel_title": "channel",
                    "matched_public_event": {
                        "name": "自由が丘納涼盆踊り大会",
                        "date": "2025-07-19",
                        "date_end": "",
                        "score": 75,
                    },
                    "songs": [{"title": "東京音頭"}, {"title": "炭坑節"}],
                }
            ]
        }
        rows = build_dry_run(
            FakeApi({"自由が丘納涼盆踊り大会": page()}),
            plan,
            [{"name": "自由が丘納涼盆踊り大会", "detail": "2025-07-19（土）〜21（月祝）18:00-21:00。"}],
        )
        self.assertEqual(rows[0]["status"], "review")
        self.assertIn("date_endが空", "; ".join(rows[0]["warnings"]))

    def test_marks_duplicate_url_as_done(self):
        plan = {
            "rows": [
                {
                    "candidate_key": "yt1",
                    "action": "append_evidence_to_existing_event",
                    "youtube_event_date": "2025-09-16",
                    "source_video_url": "https://www.youtube.com/watch?v=abc",
                    "source_channel_title": "channel",
                    "matched_public_event": {
                        "name": "歌舞伎町BON ODORI",
                        "date": "",
                        "date_end": "",
                        "score": 75,
                    },
                    "songs": [{"title": "ダンシング・ヒーロー"}],
                }
            ]
        }
        rows = build_dry_run(
            FakeApi({"歌舞伎町BON ODORI": page("https://www.youtube.com/watch?v=abc")}),
            plan,
        )
        self.assertEqual(rows[0]["status"], "done")
        self.assertFalse(rows[0]["would_change_detail"])
        self.assertIn("同じYouTube URL", "; ".join(rows[0]["warnings"]))

    def test_marks_low_song_count_as_done_when_song_already_covered(self):
        plan = {
            "rows": [
                {
                    "candidate_key": "yt1",
                    "action": "append_evidence_to_existing_event",
                    "youtube_event_date": "2025-08-16",
                    "source_video_url": "https://www.youtube.com/watch?v=abc",
                    "source_channel_title": "channel",
                    "matched_public_event": {
                        "name": "歌舞伎町BON ODORI",
                        "date": "2025-08-16",
                        "date_end": "",
                        "score": 75,
                    },
                    "songs": [{"title": "ultra soul ②"}],
                }
            ]
        }
        rows = build_dry_run(
            FakeApi({"歌舞伎町BON ODORI": page("[youtube_evidence]\n- 曲目候補: ultra soul, Get Wild")}),
            plan,
        )
        self.assertEqual(rows[0]["status"], "done")
        self.assertFalse(rows[0]["would_change_detail"])
        self.assertIn("既存のYouTube証拠", "; ".join(rows[0]["warnings"]))

    def test_flags_small_song_count_for_review_when_not_covered(self):
        plan = {
            "rows": [
                {
                    "candidate_key": "yt1",
                    "action": "append_evidence_to_existing_event",
                    "youtube_event_date": "2025-09-16",
                    "source_video_url": "https://www.youtube.com/watch?v=abc",
                    "source_channel_title": "channel",
                    "matched_public_event": {
                        "name": "歌舞伎町BON ODORI",
                        "date": "",
                        "date_end": "",
                        "score": 75,
                    },
                    "songs": [{"title": "ダンシング・ヒーロー"}],
                }
            ]
        }
        rows = build_dry_run(
            FakeApi({"歌舞伎町BON ODORI": page()}),
            plan,
        )
        self.assertEqual(rows[0]["status"], "review")
        self.assertTrue(rows[0]["would_change_detail"])
        self.assertIn("曲目候補が1件以下", "; ".join(rows[0]["warnings"]))


if __name__ == "__main__":
    unittest.main()
