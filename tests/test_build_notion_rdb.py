import sqlite3
import tempfile
import unittest
from pathlib import Path

from rdb_builders.build_notion_rdb import build_rows, create_db, prop_plain


def title_prop(value):
    return {"type": "title", "title": [{"plain_text": value}]}


def rich_text_prop(value):
    return {"type": "rich_text", "rich_text": [{"plain_text": value}]}


class BuildNotionRdbTest(unittest.TestCase):
    def test_prop_plain_handles_common_notion_property_types(self):
        self.assertEqual(prop_plain(title_prop("山王音頭")), "山王音頭")
        self.assertEqual(prop_plain({"type": "select", "select": {"name": "確認済み"}}), "確認済み")
        self.assertEqual(prop_plain({"type": "number", "number": 3}), "3")
        self.assertEqual(
            prop_plain({"type": "date", "date": {"start": "2026-06-13", "end": "2026-06-15"}}),
            "2026-06-13..2026-06-15",
        )

    def test_builds_normalized_rows_and_sqlite_tables(self):
        event_page = {
            "id": "event1",
            "url": "https://notion.so/event1",
            "created_time": "2026-06-01T00:00:00Z",
            "last_edited_time": "2026-06-02T00:00:00Z",
            "archived": False,
            "properties": {
                "イベント名": title_prop("山王音頭と民踊大会"),
                "会場": {"type": "relation", "relation": [{"id": "venue1"}]},
                "開催日": {"type": "date", "date": {"start": "2026-06-13", "end": "2026-06-15"}},
                "状態": {"type": "select", "select": {"name": "確認済み"}},
                "開催パターン詳細": rich_text_prop("毎年開催"),
            },
        }
        venue_page = {
            "id": "venue1",
            "url": "https://notion.so/venue1",
            "properties": {
                "会場名": title_prop("山王パークタワー公開空地"),
                "所在区・市": rich_text_prop("千代田区"),
                "住所": rich_text_prop("東京都千代田区"),
            },
        }
        rows = build_rows([
            (
                {
                    "source_key": "events",
                    "source_name": "イベントDB",
                    "api_kind": "data_source",
                    "notion_id": "event_ds",
                    "title_property": "イベント名",
                },
                [event_page],
            ),
            (
                {
                    "source_key": "venues",
                    "source_name": "会場マスタ",
                    "api_kind": "data_source",
                    "notion_id": "venue_ds",
                    "title_property": "会場名",
                },
                [venue_page],
            ),
        ])

        self.assertEqual(len(rows["events"]), 1)
        self.assertEqual(rows["events"][0]["event_name"], "山王音頭と民踊大会")
        self.assertEqual(rows["events"][0]["start_date"], "2026-06-13")
        self.assertEqual(len(rows["relations"]), 1)

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "notion.sqlite"
            create_db(db_path, rows)
            with sqlite3.connect(db_path) as conn:
                page_count = conn.execute("SELECT COUNT(*) FROM notion_pages").fetchone()[0]
                event = conn.execute(
                    "SELECT event_name, start_date, end_date FROM notion_events"
                ).fetchone()
                relation = conn.execute(
                    "SELECT page_id, property_name, related_page_id FROM notion_relations"
                ).fetchone()

            self.assertEqual(page_count, 2)
            self.assertEqual(event, ("山王音頭と民踊大会", "2026-06-13", "2026-06-15"))
            self.assertEqual(relation, ("event1", "会場", "venue1"))


if __name__ == "__main__":
    unittest.main()
