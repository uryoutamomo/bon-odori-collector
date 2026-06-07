import unittest

from queue_store import (
    DynamoQueueStore,
    normalize_candidate_key,
    normalize_venue_key,
)


class ConditionalFailure(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeTable:
    def __init__(self):
        self.items = {}

    def put_item(self, Item, ConditionExpression):
        key = Item["venue_key"]
        if key in self.items:
            raise ConditionalFailure()
        self.items[key] = Item

    def get_item(self, **kwargs):
        return {"Item": self.items.get(kwargs["Key"]["venue_key"], {})}

    def update_item(self, **kwargs):
        key = kwargs["Key"]["venue_key"]
        if key not in self.items:
            raise ConditionalFailure()
        values = kwargs["ExpressionAttributeValues"]
        if ":status" in values:
            self.items[key]["status"] = values[":status"]
        if ":synced" in values:
            self.items[key]["notion_synced"] = values[":synced"]
        self.items[key]["updated_at"] = values[":updated_at"]


class DynamoQueueStoreTest(unittest.TestCase):
    def setUp(self):
        self.table = FakeTable()
        self.store = DynamoQueueStore(table=self.table)
        self.candidate = {
            "venue": "築地本願寺",
            "source": "news",
            "priority": "ホーム",
            "url": "https://example.com",
            "text": "盆踊り開催",
        }

    def test_normalized_key_ignores_spaces(self):
        self.assertEqual(
            normalize_venue_key("築地 本願寺"),
            normalize_venue_key(" 築地本願寺 "),
        )

    def test_event_key_is_separate_from_venue_key(self):
        self.assertNotEqual(
            normalize_candidate_key("中央公園", "イベント"),
            normalize_candidate_key("中央公園", "会場"),
        )

    def test_add_candidate_is_idempotent(self):
        self.assertTrue(self.store.add_candidate(self.candidate))
        self.assertFalse(self.store.add_candidate(self.candidate))
        self.assertEqual(len(self.table.items), 1)
        item = self.table.items[normalize_venue_key("築地本願寺")]
        self.assertEqual(item["candidate_type"], "会場")

    def test_same_name_can_be_added_for_each_type(self):
        self.assertTrue(self.store.add_candidate(self.candidate))
        event = dict(self.candidate, type="イベント")
        self.assertTrue(self.store.add_candidate(event))
        self.assertEqual(len(self.table.items), 2)

    def test_event_evidence_uses_tweet_identity(self):
        event = dict(
            self.candidate,
            type="イベント",
            identity="evidence:123",
            tweet_id="123",
            patterns=["A", "D"],
            score=9,
        )
        self.assertTrue(self.store.add_candidate(event))
        key = normalize_candidate_key("evidence:123", "イベント")
        self.assertEqual(self.table.items[key]["tweet_id"], "123")
        self.assertEqual(self.table.items[key]["patterns"], ["A", "D"])
        self.assertEqual(self.table.items[key]["status"], "要裏取り")

    def test_update_status(self):
        self.store.add_candidate(self.candidate)
        self.store.update_status("築地本願寺", "該当なし")
        item = self.table.items[normalize_venue_key("築地本願寺")]
        self.assertEqual(item["status"], "該当なし")

    def test_notion_sync_state(self):
        self.store.add_candidate(self.candidate)
        self.assertFalse(self.store.is_notion_synced("築地本願寺"))
        self.store.mark_notion_synced("築地本願寺")
        self.assertTrue(self.store.is_notion_synced("築地本願寺"))


if __name__ == "__main__":
    unittest.main()
