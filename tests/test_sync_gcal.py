import unittest

from sync_gcal import build_gcal_event, sync


def text_prop(prop_type, value):
    return {
        "type": prop_type,
        prop_type: [{"plain_text": value}] if value else [],
    }


def event_page(page_id="event-1", state="確認済み", date="2026-08-21"):
    return {
        "id": page_id,
        "properties": {
            "イベント名": text_prop("title", "中央区盆踊り"),
            "状態": {"type": "select", "select": {"name": state}},
            "開催日": {
                "type": "date",
                "date": {"start": date, "end": None} if date else None,
            },
            "情報源URL": {
                "type": "url",
                "url": "https://example.com/event",
            },
            "会場": {"type": "relation", "relation": []},
        },
    }


def plan_page(event_id="event-1", status="参加予定", gcal_id=""):
    return {
        "id": "plan-1",
        "properties": {
            "参加計画名": text_prop("title", "中央区盆踊り"),
            "参加ステータス": {
                "type": "select",
                "select": {"name": status},
            },
            "イベント": {
                "type": "relation",
                "relation": [{"id": event_id}],
            },
            "移動手段": {
                "type": "select",
                "select": {"name": "自転車"},
            },
            "個人メモ": text_prop("rich_text", "再訪"),
            "日付": {"type": "date", "date": None},
            "GCal同期ID": text_prop("rich_text", gcal_id),
        },
    }


class FakeExecute:
    def __init__(self, result=None):
        self.result = result or {}

    def execute(self):
        return self.result


class FakeEvents:
    def __init__(self):
        self.calls = []

    def insert(self, **kwargs):
        self.calls.append(("insert", kwargs))
        return FakeExecute({"id": "gcal-new"})

    def update(self, **kwargs):
        self.calls.append(("update", kwargs))
        return FakeExecute()

    def delete(self, **kwargs):
        self.calls.append(("delete", kwargs))
        return FakeExecute()


class FakeGcal:
    def __init__(self):
        self.event_api = FakeEvents()

    def events(self):
        return self.event_api


class FakeApi:
    def __init__(self, events, plans):
        self.events = events
        self.plans = plans
        self.updates = []

    def retrieve_data_source(self, data_source_id):
        from event_audit import EVENT_SCHEMA
        from notion_config import (
            EVENT_DATA_SOURCE_ID,
            PLAN_DATA_SOURCE_ID,
            VENUE_DATA_SOURCE_ID,
        )
        from sync_gcal import PLAN_SCHEMA, VENUE_SCHEMA

        schemas = {
            EVENT_DATA_SOURCE_ID: EVENT_SCHEMA,
            PLAN_DATA_SOURCE_ID: PLAN_SCHEMA,
            VENUE_DATA_SOURCE_ID: VENUE_SCHEMA,
        }
        properties = {}
        for name, expected in schemas[data_source_id].items():
            prop = {"type": expected["type"]}
            if expected["type"] == "relation":
                prop["relation"] = {
                    "data_source_id": expected["data_source_id"]
                }
            properties[name] = prop
        return {"properties": properties}

    def query_data_source(self, data_source_id):
        from notion_config import EVENT_DATA_SOURCE_ID

        return self.events if data_source_id == EVENT_DATA_SOURCE_ID else self.plans

    def retrieve_page(self, page_id):
        raise AssertionError("venue lookup was not expected")

    def update_page(self, page_id, properties):
        self.updates.append((page_id, properties))


class SyncGcalTest(unittest.TestCase):
    def test_builds_event_from_current_schema(self):
        body = build_gcal_event(plan_page(), event_page())
        self.assertEqual(body["summary"], "中央区盆踊り")
        self.assertEqual(body["start"], {"date": "2026-08-21"})
        self.assertEqual(body["end"], {"date": "2026-08-22"})
        self.assertIn("移動手段: 自転車", body["description"])

    def test_sync_creates_only_confirmed_dated_event(self):
        api = FakeApi([event_page()], [plan_page()])
        gcal = FakeGcal()
        stats = sync(api, gcal)
        self.assertEqual(stats["created"], 1)
        self.assertEqual(gcal.event_api.calls[0][0], "insert")
        self.assertEqual(api.updates[0][0], "plan-1")

    def test_sync_skips_unconfirmed_event(self):
        api = FakeApi(
            [event_page(state="未確認")],
            [plan_page()],
        )
        stats = sync(api, FakeGcal())
        self.assertEqual(stats["skipped"], 1)

    def test_sync_deletes_existing_calendar_event_when_unconfirmed(self):
        api = FakeApi(
            [event_page(state="未確認")],
            [plan_page(gcal_id="gcal-old")],
        )
        gcal = FakeGcal()
        stats = sync(api, gcal)
        self.assertEqual(stats["deleted"], 1)
        self.assertEqual(gcal.event_api.calls[0][0], "delete")
        self.assertEqual(api.updates[0][1]["日付"], {"date": None})

    def test_sync_rejects_noncanonical_relation(self):
        api = FakeApi([event_page()], [plan_page(event_id="old-event")])
        with self.assertRaisesRegex(ValueError, "non-canonical"):
            sync(api, FakeGcal())


if __name__ == "__main__":
    unittest.main()
