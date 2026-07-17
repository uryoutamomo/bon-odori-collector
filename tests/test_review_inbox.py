import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from review_inbox import export_inbox_json, inbox_rows, upsert_inbox_items


def inbox_item(**overrides):
    item = {
        "kind": "current_year_confirmation",
        "domain": "開催日",
        "priority_label": "P0",
        "priority_score": 100,
        "title": "丸の内de盆踊り 2026候補",
        "event_name": "丸の内de盆踊り",
        "venue": "行幸通り",
        "event_year": 2026,
        "source_id": "date_predictions",
        "source_key": "marunouchi|2026",
        "source_url": "https://example.com",
        "recommended_action": "confirm_current_date",
        "payload": {"summary": "7月最終金曜候補"},
    }
    item.update(overrides)
    return item


class ReviewInboxTest(unittest.TestCase):
    def test_upsert_and_export_pending_inbox_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            conn = sqlite3.connect(db)
            try:
                normalized = upsert_inbox_items(conn, [inbox_item()])
                conn.commit()
                rows = inbox_rows(conn, status="pending")
            finally:
                conn.close()

            self.assertEqual(len(normalized), 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["event_name"], "丸の内de盆踊り")
            self.assertEqual(rows[0]["payload"]["summary"], "7月最終金曜候補")

            out_json = Path(tmp) / "review_inbox.json"
            payload = export_inbox_json(db, out_json, status="pending")

            self.assertEqual(payload["source"], "master_rdb.review_inbox_items")
            self.assertEqual(payload["items"][0]["recommended_action"], "confirm_current_date")
            saved = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(saved["items"][0]["source_key"], "marunouchi|2026")

    def test_upsert_keeps_processed_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            conn = sqlite3.connect(db)
            try:
                upsert_inbox_items(conn, [inbox_item(status="pending")])
                conn.execute(
                    "UPDATE review_inbox_items SET status = 'accepted' WHERE source_key = ?",
                    ("marunouchi|2026",),
                )
                upsert_inbox_items(conn, [inbox_item(status="pending", title="再収穫された候補")])
                conn.commit()
                rows = inbox_rows(conn, status=None)
            finally:
                conn.close()

            self.assertEqual(rows[0]["status"], "accepted")
            self.assertEqual(rows[0]["title"], "再収穫された候補")


if __name__ == "__main__":
    unittest.main()
