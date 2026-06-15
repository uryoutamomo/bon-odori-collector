import unittest

from apply_youtube_blocked_new_events import build_results, event_status, text_prop


class FakeApi:
    def __init__(self, title_rows=None):
        self.title_rows = title_rows or {}
        self.created = []

    def query_data_source(self, data_source_id, payload):
        name = payload["filter"]["title"]["equals"]
        return self.title_rows.get(name, [])

    def request(self, method, path, payload=None):
        page = {"id": f"created-{len(self.created) + 1}", "payload": payload}
        self.created.append(page)
        return page


class ApplyYoutubeBlockedNewEventsTest(unittest.TestCase):
    def test_event_status_marks_past_event_done(self):
        self.assertEqual(event_status("2026-06-07"), "終了")

    def test_text_prop_splits_long_text(self):
        prop = text_prop("a" * 2001)

        self.assertEqual(len(prop["rich_text"]), 2)
        self.assertEqual(len(prop["rich_text"][0]["text"]["content"]), 1900)

    def test_dry_run_reports_missing_venue_and_event(self):
        rows = build_results(FakeApi(), apply=False)

        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["venue_exists"])
        self.assertFalse(rows[0]["event_exists"])
        self.assertFalse(rows[0]["venue_created"])
        self.assertFalse(rows[0]["event_created"])

    def test_apply_creates_venue_then_event_when_missing(self):
        api = FakeApi()

        rows = build_results(api, apply=True)

        self.assertTrue(rows[0]["venue_created"])
        self.assertTrue(rows[0]["event_created"])
        self.assertEqual(len(api.created), 2)

    def test_does_not_create_existing_event(self):
        api = FakeApi({
            "国立旭通り 弥生ビル東側": [{"id": "venue-id"}],
            "ジューンフェスタ2026 盆踊り（国立市旭通り商店会）": [{"id": "event-id"}],
        })

        rows = build_results(api, apply=True)

        self.assertTrue(rows[0]["venue_exists"])
        self.assertTrue(rows[0]["event_exists"])
        self.assertFalse(rows[0]["venue_created"])
        self.assertFalse(rows[0]["event_created"])
        self.assertEqual(len(api.created), 0)


if __name__ == "__main__":
    unittest.main()
