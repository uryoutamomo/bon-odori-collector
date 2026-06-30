import json
import os
import tempfile
import unittest
from pathlib import Path

import run_post_batch_maintenance as maintenance
from master_db import init_db


NOW = "2026-01-01T00:00:00+00:00"


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def create_master_db(path):
    conn = init_db(path)
    conn.execute(
        """
        INSERT INTO venues(
          venue_id, canonical_name, normalized_name, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        ("venue_1", "テスト公園", "テスト公園", NOW, NOW),
    )
    conn.execute(
        """
        INSERT INTO event_series(
          series_id, series_key, canonical_name, normalized_name, usual_venue_id,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("series_1", "test-series", "テスト盆踊り", "テスト盆踊り", "venue_1", NOW, NOW),
    )
    conn.execute(
        """
        INSERT INTO event_occurrences(
          occurrence_id, series_id, event_year, display_name, venue_id, date_start,
          date_status, lifecycle_status, confidence, source_url, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "occ_1",
            "series_1",
            2026,
            "テスト盆踊り",
            "venue_1",
            "2026-07-01",
            "confirmed",
            "published",
            "confirmed",
            "https://example.com",
            NOW,
            NOW,
        ),
    )
    conn.execute(
        """
        INSERT INTO event_occurrences(
          occurrence_id, series_id, event_year, occurrence_sequence, display_name, date_status,
          lifecycle_status, confidence, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("occ_2", "series_1", 2026, 2, "未確認テスト", "unknown", "未確認", "unknown", NOW, NOW),
    )
    conn.execute(
        """
        INSERT INTO event_investigation_tasks(
          task_id, occurrence_id, notion_page_id, event_name, event_year, status,
          missing_date, missing_venue, priority_score, priority_label,
          recommended_action, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("task_1", "occ_2", "legacy-page", "未確認テスト", 2026, "未確認", 1, 1, 100, "P0", "review", NOW, NOW),
    )
    conn.commit()
    conn.close()


class RunPostBatchMaintenanceTest(unittest.TestCase):
    def test_current_light_report_does_not_require_notion_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            db = data_dir / "bon_odori_master.sqlite"
            create_master_db(db)
            write_json(
                data_dir / "public" / "events_public.json",
                [
                    {
                        "name": "テスト盆踊り",
                        "date": "2026-07-01",
                        "public_status": "upcoming_confirmed",
                        "date_confidence": {"level": "confirmed"},
                        "source_urls": ["https://example.com"],
                    },
                    {
                        "name": "未確認テスト",
                        "date": "",
                        "public_status": "date_unknown",
                        "date_confidence": {"level": "unknown"},
                        "source_urls": [],
                    },
                ],
            )
            write_json(data_dir / "voices.json", [{"text": "盆踊り"}])
            write_json(data_dir / "x_account_scores.json", {"generated_at": NOW, "accounts": [{"account": "@test"}]})
            old_token = os.environ.pop("NOTION_API_TOKEN", None)
            try:
                report = maintenance.build_report(data_dir=data_dir, master_db=db, target_year=2026)
            finally:
                if old_token is not None:
                    os.environ["NOTION_API_TOKEN"] = old_token

        self.assertEqual(report["status"], "report_generated")
        self.assertFalse(report["notion_api_required"])
        self.assertEqual(report["input_errors"], [])
        self.assertEqual(report["master_rdb"]["target_year"]["occurrences"], 2)
        self.assertEqual(report["master_rdb"]["target_year"]["missing_date_start"], 1)
        self.assertEqual(report["master_rdb"]["review"]["open_p0_tasks"], 1)
        self.assertEqual(report["inputs"]["public_events"]["counts"]["events"], 2)
        self.assertEqual(report["inputs"]["public_events"]["counts"]["missing_source_urls"], 1)

    def test_missing_master_db_does_not_create_empty_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            missing_db = data_dir / "missing.sqlite"
            write_json(data_dir / "public" / "events_public.json", [])

            report = maintenance.build_report(data_dir=data_dir, master_db=missing_db, target_year=2026)

        self.assertFalse(missing_db.exists())
        self.assertEqual(report["status"], "blocked_missing_inputs")
        self.assertIn("master_rdb", report["input_errors"])


if __name__ == "__main__":
    unittest.main()
