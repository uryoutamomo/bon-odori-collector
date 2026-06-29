import os
import unittest
from unittest.mock import patch

import collect


def _empty_queue_seen():
    return {candidate_type: set() for candidate_type in collect.QUEUE_TYPES}


class FakeDynamoQueueStore:
    def __init__(self):
        self.added = []
        self.synced = []

    def add_candidate(self, candidate):
        self.added.append(candidate)
        return True

    def is_notion_synced(self, key, candidate_type=None):
        return False

    def mark_notion_synced(self, key, candidate_type=None):
        self.synced.append((key, candidate_type))


class CollectNotionWritePolicyTest(unittest.TestCase):
    def test_collect_notion_writes_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(collect.collect_notion_writes_enabled())

    def test_collect_notion_writes_requires_truthy_env(self):
        for value in ("true", "1", "yes", "on"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"COLLECT_ALLOW_NOTION_WRITES": value}, clear=True):
                    self.assertTrue(collect.collect_notion_writes_enabled())

    def test_x_log_row_does_not_write_to_notion_without_opt_in(self):
        voice = {
            "text": "築地本願寺の盆踊り",
            "account": "@test",
            "url": "https://x.com/test/status/1",
            "date": "2026-06-26T00:00:00+00:00",
        }
        with (
            patch.dict(os.environ, {"COLLECT_ALLOW_NOTION_WRITES": "false"}, clear=True),
            patch.object(collect, "NOTION_TOKEN", "token"),
            patch.object(collect, "X_LOG_DB_ID", "x-log"),
            patch.object(collect, "_notion_request") as notion_request,
        ):
            collect._append_x_log_row(voice, "q-test", "🟢一次レポ", 0.00015)

        notion_request.assert_not_called()

    def test_x_member_scores_do_not_sync_to_notion_without_opt_in(self):
        with (
            patch.dict(os.environ, {"COLLECT_ALLOW_NOTION_WRITES": "false"}, clear=True),
            patch.object(collect, "NOTION_TOKEN", "token"),
            patch.object(collect, "_ensure_x_member_score_props") as ensure_props,
            patch.object(collect, "_cleanup_x_member_obsolete_score_props") as cleanup_props,
            patch.object(collect, "_update_page_props_best_effort") as update_props,
        ):
            collect._sync_x_account_scores_to_notion(
                [{"handle": "@test", "page_id": "page-1"}],
                {},
            )

        ensure_props.assert_not_called()
        cleanup_props.assert_not_called()
        update_props.assert_not_called()

    def test_push_to_notion_skips_summary_without_opt_in(self):
        with (
            patch.dict(os.environ, {"COLLECT_ALLOW_NOTION_WRITES": "false"}, clear=True),
            patch.object(collect, "NOTION_TOKEN", "token"),
            patch.object(collect, "NOTION_PAGE_ID", "page-1"),
            patch.object(collect, "_notion_request") as notion_request,
        ):
            collect.push_to_notion([], "2026-06-26 00:00 JST")

        notion_request.assert_not_called()

    def test_dual_queue_still_uses_dynamodb_without_notion_opt_in(self):
        store = FakeDynamoQueueStore()
        detected = [{
            "venue": "築地本願寺",
            "url": "https://example.com",
            "text": "築地本願寺で盆踊り開催",
            "source": "news",
            "priority": "ホーム",
        }]
        with (
            patch.dict(
                os.environ,
                {
                    "COLLECT_ALLOW_NOTION_WRITES": "false",
                    "DYNAMODB_QUEUE_TABLE": "queue-table",
                },
                clear=True,
            ),
            patch.object(collect, "NOTION_TOKEN", "token"),
            patch.object(collect, "QUEUE_STORAGE_MODE", "dual"),
            patch.object(collect, "DynamoQueueStore", return_value=store),
            patch.object(collect, "_load_queue_seen", return_value=_empty_queue_seen()),
            patch.object(collect, "_save_queue_seen"),
            patch.object(collect, "_notion_request") as notion_request,
        ):
            result = collect.push_torimochi_queue(detected)

        self.assertEqual(result["added"], 1)
        self.assertEqual(len(store.added), 1)
        notion_request.assert_not_called()

    def test_notion_only_event_queue_fails_closed_without_opt_in(self):
        candidate = {
            "candidate_key": "event:1",
            "match_key": "event:test",
            "title": "築地本願寺の盆踊り",
            "text": "築地本願寺で盆踊り開催",
        }
        with (
            patch.dict(os.environ, {"COLLECT_ALLOW_NOTION_WRITES": "false"}, clear=True),
            patch.object(collect, "NOTION_TOKEN", "token"),
            patch.object(collect, "EVENT_QUEUE_STORAGE_MODE", "notion"),
            patch.object(collect, "_load_known_venues", return_value={}),
            patch.object(collect, "aggregate_event_candidates", return_value=[candidate]),
            patch.object(collect, "_notion_request") as notion_request,
        ):
            result = collect.push_event_candidate_queue([{"identity": "evidence:1"}])

        self.assertEqual(result["added"], 0)
        self.assertEqual(result["failed"], 1)
        notion_request.assert_not_called()

    def test_glossary_alias_registration_skips_without_opt_in(self):
        with (
            patch.dict(os.environ, {"COLLECT_ALLOW_NOTION_WRITES": "false"}, clear=True),
            patch.object(collect, "NOTION_TOKEN", "token"),
            patch.object(collect, "GLOSSARY_DB_ID", "glossary"),
            patch.object(collect, "_notion_query_database") as query_database,
            patch.object(collect, "_notion_request") as notion_request,
        ):
            collect.register_glossary_alias("晴盆", "晴海ふ頭公園")

        query_database.assert_not_called()
        notion_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
