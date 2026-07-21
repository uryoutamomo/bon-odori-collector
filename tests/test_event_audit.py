import unittest

from collection_support.event_audit import (
    blocking_duplicate_count,
    duplicate_groups,
    normalize_event_name,
    normalize_source_url,
)


def event(page_id, name, url=""):
    return {
        "id": page_id,
        "properties": {
            "イベント名": {
                "type": "title",
                "title": [{"plain_text": name}],
            },
            "情報源URL": {"type": "url", "url": url or None},
        },
    }


class EventAuditTest(unittest.TestCase):
    def test_normalizes_name_width_spacing_and_punctuation(self):
        self.assertEqual(
            normalize_event_name("盆踊り（中央区）"),
            normalize_event_name("盆踊り ( 中央区 )"),
        )

    def test_normalizes_url_query_fragment_and_trailing_slash(self):
        self.assertEqual(
            normalize_source_url("HTTPS://EXAMPLE.COM/event/?ref=x#top"),
            "https://example.com/event",
        )

    def test_detects_duplicates_by_name_and_url(self):
        rows = [
            event("1", "中央区 盆踊り", "https://example.com/event"),
            event("2", "中央区盆踊り", "https://example.com/event?ref=x"),
            event("3", "別イベント", "https://example.com/other"),
        ]
        groups = duplicate_groups(rows)
        self.assertEqual(len(groups["name"]), 1)
        self.assertEqual(len(groups["url_name_match"]), 1)
        self.assertEqual(
            {page["id"] for page in groups["name"][0]["pages"]},
            {"1", "2"},
        )

    def test_shared_url_for_different_events_is_warning_only(self):
        rows = [
            event("1", "佃島の盆踊り", "https://example.com/list"),
            event("2", "銀座納涼盆踊り", "https://example.com/list"),
        ]
        groups = duplicate_groups(rows)
        self.assertEqual(groups["url_name_match"], [])
        self.assertEqual(len(groups["shared_url"]), 1)
        self.assertEqual(blocking_duplicate_count(groups), 0)


if __name__ == "__main__":
    unittest.main()
