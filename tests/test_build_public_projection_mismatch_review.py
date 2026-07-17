import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_public_projection_mismatch_review.py"
SPEC = importlib.util.spec_from_file_location("build_public_projection_mismatch_review", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BuildPublicProjectionMismatchReviewTest(unittest.TestCase):
    def test_builds_historical_date_mismatch_rows_with_sources(self):
        compare_report = {
            "blocking_rows": [
                {
                    "name": "サンプル盆踊り",
                    "venue": "中央公園",
                    "occurrence_id": "occ1",
                    "historical_reference": {
                        "status": "date_mismatch",
                        "public_dates": ["2025-07-20"],
                        "rdb_dates": ["2024-07-21"],
                        "rdb_sources": [
                            {
                                "source_id": "od1",
                                "dates": ["2024-07-21"],
                                "source_title": "RDB source",
                                "source_url": "https://example.com/rdb",
                            }
                        ],
                    },
                },
                {
                    "name": "別イベント",
                    "venue": "別会場",
                    "historical_reference": {"status": "missing_rdb_source"},
                },
            ]
        }
        public_events = [
            {
                "name": "サンプル盆踊り",
                "venue": "中央公園",
                "historical_reference": {"last_seen_dates": ["2025-07-20"], "last_seen_year": 2025},
                "source_urls": [{"label": "public source", "url": "https://example.com/public"}],
            }
        ]

        rows = MODULE.build_rows(compare_report, public_events, {"date_mismatch"})

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["issue_type"], "historical:date_mismatch")
        self.assertEqual(rows[0]["public"]["dates"], ["2025-07-20"])
        self.assertEqual(rows[0]["public"]["sources"][0]["url"], "https://example.com/public")
        self.assertEqual(rows[0]["rdb"]["dates"], ["2024-07-21"])
        self.assertEqual(rows[0]["rdb"]["sources"][0]["source_url"], "https://example.com/rdb")

    def test_parse_statuses_accepts_prefixed_names(self):
        self.assertEqual(MODULE.parse_statuses(["historical:date_mismatch"]), {"date_mismatch"})

    def test_explicit_status_does_not_include_default(self):
        args = MODULE.parse_args(["--status", "missing_rdb_source"])

        self.assertEqual(args.status, ["missing_rdb_source"])


if __name__ == "__main__":
    unittest.main()
