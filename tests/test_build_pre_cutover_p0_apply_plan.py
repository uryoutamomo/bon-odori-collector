import json
import sqlite3
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import build_pre_cutover_p0_apply_plan as planner


class BuildPreCutoverP0ApplyPlanTest(unittest.TestCase):
    def test_existing_historical_reference_is_marked_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            queue_json = tmp / "queue.json"
            master_db = tmp / "master.sqlite"
            out_json = tmp / "plan.json"
            out_md = tmp / "plan.md"
            occurrence_id = "occ1"
            queue_json.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "scope": "primary_unconfirmed",
                                "priority_label": "P0",
                                "event_name": "濱町音頭盆踊り大会",
                                "task_id": "task1",
                                "occurrence_id": occurrence_id,
                                "notion_page_id": "page1",
                                "event_year": 2026,
                                "known_venue_names": ["浜町公園"],
                                "source_url": "",
                                "priority_score": 12,
                                "reason_codes": ["missing_date"],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with sqlite3.connect(master_db) as conn:
                conn.execute(
                    """
                    CREATE TABLE occurrence_dates(
                      occurrence_id TEXT,
                      date_start TEXT,
                      date_end TEXT,
                      date_type TEXT
                    )
                    """
                )
                conn.execute(
                    "INSERT INTO occurrence_dates VALUES (?, ?, ?, ?)",
                    (occurrence_id, "2025-09-27", "", "historical_reference"),
                )
                conn.commit()

            result = planner.build(
                Namespace(
                    queue_json=queue_json,
                    master_db=master_db,
                    out_json=out_json,
                    out_md=out_md,
                )
            )

            self.assertEqual(result["summary"]["by_bucket"], {"historical_reference_recorded": 1})
            self.assertEqual(result["rows"][0]["recommended_action"], "already_recorded_historical_reference")
            self.assertFalse(result["rows"][0]["requires_human_review"])
            self.assertTrue(result["rows"][0]["requires_human_review_before_recorded"])
            self.assertEqual(result["summary"]["human_review_required_count"], 0)


if __name__ == "__main__":
    unittest.main()
