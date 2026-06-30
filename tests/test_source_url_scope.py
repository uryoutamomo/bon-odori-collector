import sqlite3
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import build_official_source_review
import build_rare_signal_backcheck_queue
import review_missing_source_urls


class SourceUrlScopeTest(unittest.TestCase):
    def make_missing_source_db(self, path: Path) -> None:
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE event_series (
              series_id TEXT PRIMARY KEY,
              canonical_name TEXT,
              area TEXT,
              usual_venue_id TEXT,
              source_url TEXT
            );
            CREATE TABLE event_occurrences (
              occurrence_id TEXT PRIMARY KEY,
              series_id TEXT,
              display_name TEXT,
              event_year INTEGER,
              venue_id TEXT,
              date_start TEXT,
              date_end TEXT,
              date_status TEXT,
              lifecycle_status TEXT,
              source_kind TEXT,
              source_url TEXT
            );
            CREATE TABLE venues (
              venue_id TEXT PRIMARY KEY,
              area TEXT,
              address TEXT
            );
            """
        )
        conn.execute("INSERT INTO venues VALUES ('v23', '江東区', '東京都江東区豊洲')")
        conn.execute("INSERT INTO venues VALUES ('vout', '国立市', '東京都国立市東')")
        conn.execute("INSERT INTO event_series VALUES ('s23', '豊洲盆踊り', '江東区', 'v23', '')")
        conn.execute("INSERT INTO event_series VALUES ('sout', '国立旭通り盆踊り', '国立市', 'vout', '')")
        conn.execute(
            "INSERT INTO event_occurrences VALUES ('occ23', 's23', '豊洲盆踊り', 2026, 'v23', '', '', 'unknown', '未確認', 'notion_events', '')"
        )
        conn.execute(
            "INSERT INTO event_occurrences VALUES ('occout', 'sout', '国立旭通り盆踊り', 2026, 'vout', '', '', 'unknown', '未確認', 'notion_events', '')"
        )
        conn.commit()
        conn.close()

    def test_missing_source_url_review_skips_outside_tokyo_23(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "master.sqlite"
            self.make_missing_source_db(db_path)

            result = review_missing_source_urls.build(
                Namespace(
                    master_db=db_path,
                    out_json=tmp_path / "missing_source_url_review.json",
                    out_md=tmp_path / "missing_source_url_review.md",
                )
            )

            self.assertEqual(result["summary"]["missing_source_url_occurrence_count"], 1)
            self.assertEqual(result["summary"]["skipped_outside_tokyo_23_count"], 1)
            self.assertEqual(result["review"][0]["event_name"], "豊洲盆踊り")
            self.assertEqual(result["skipped_outside_tokyo_23"][0]["event_name"], "国立旭通り盆踊り")

    def test_official_source_review_skips_outside_tokyo_23_blog_candidates(self):
        row = build_official_source_review.row_from_blog_item(
            {
                "venue_name": "山下公園",
                "region": "横浜市",
                "event": {
                    "name": "横浜開港祭 BON ODORI",
                    "source_url": "https://www.kaikosai.com/",
                },
            },
            existing_urls=set(),
        )
        self.assertIsNone(row)

        row = build_official_source_review.row_from_blog_item(
            {
                "venue_name": "芝公園",
                "region": "港区",
                "event": {
                    "name": "芝公園盆踊り",
                    "source_url": "https://example.com/shiba",
                },
            },
            existing_urls=set(),
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["region"], "港区")

    def test_official_source_review_skips_outside_tokyo_23_youtube_candidates(self):
        rows = build_official_source_review.rows_from_youtube_validation(
            {
                "rows": [
                    {
                        "primary_url": "https://example.com/kunitachi",
                        "best_existing_matches": [
                            {
                                "venue": "国立旭通り",
                                "event_name": "国立旭通り盆踊り",
                                "reasons": ["title_token:国立"],
                            }
                        ],
                        "detected_dates": ["2026-06-01"],
                    },
                    {
                        "primary_url": "https://example.com/toyosu",
                        "best_existing_matches": [
                            {
                                "venue": "豊洲公園",
                                "event_name": "豊洲盆踊り",
                                "reasons": ["title_token:豊洲"],
                            }
                        ],
                        "detected_dates": ["2026-07-01"],
                    },
                ]
            },
            existing_urls=set(),
            public_by_name={
                "国立旭通り盆踊り": {"area": "国立市"},
                "豊洲盆踊り": {"area": "江東区"},
            },
        )

        self.assertEqual([row["event_name"] for row in rows], ["豊洲盆踊り"])

    def test_official_source_review_skips_youtube_date_only_existing_match(self):
        rows = build_official_source_review.rows_from_youtube_validation(
            {
                "rows": [
                    {
                        "status": "source_date_hold",
                        "primary_url": "https://ginbura.ginza.jp/",
                        "best_existing_matches": [
                            {
                                "score": 35,
                                "reasons": ["date_overlap"],
                                "venue": "",
                                "event_name": "岡本自治会「盆踊り大会」",
                            }
                        ],
                        "detected_dates": ["2025-08-02"],
                        "titles": [
                            "【 大銀座盆踊り ゆかたで銀ぶら2025】東京音頭 2025.8.2 @銀座通り"
                        ],
                    }
                ]
            },
            existing_urls=set(),
            public_by_name={"岡本自治会「盆踊り大会」": {"area": "世田谷区"}},
        )

        self.assertEqual(rows, [])

    def test_official_source_review_keeps_youtube_identity_existing_match(self):
        rows = build_official_source_review.rows_from_youtube_validation(
            {
                "rows": [
                    {
                        "status": "existing_event_review",
                        "primary_url": "https://example.com/toyosu",
                        "best_existing_matches": [
                            {
                                "score": 45,
                                "reasons": ["date_overlap", "title_token:豊洲"],
                                "venue": "豊洲公園",
                                "event_name": "豊洲盆踊り",
                            }
                        ],
                        "detected_dates": ["2026-07-01"],
                    }
                ]
            },
            existing_urls=set(),
            public_by_name={"豊洲盆踊り": {"area": "江東区"}},
        )

        self.assertEqual([row["event_name"] for row in rows], ["豊洲盆踊り"])

    def test_official_source_review_preserves_existing_decision_by_id(self):
        rows = [
            {
                "id": "same-row",
                "decision": "pending",
                "venue": "豊洲公園",
                "event_name": "豊洲盆踊り",
                "source_url": "https://example.com/toyosu",
            }
        ]
        states = build_official_source_review.collect_existing_review_states(
            [
                {
                    "id": "same-row",
                    "decision": "official",
                    "venue": "豊洲公園",
                    "event_name": "豊洲盆踊り",
                    "source_url": "https://example.com/toyosu",
                }
            ]
        )

        preserved = build_official_source_review.apply_existing_review_states(rows, states)

        self.assertEqual(preserved, 1)
        self.assertEqual(rows[0]["decision"], "official")

    def test_official_source_review_does_not_preserve_by_url_only(self):
        rows = [
            {
                "id": "new-row",
                "decision": "pending",
                "venue": "",
                "event_name": "自由が丘盆踊り",
                "source_url": "https://example.com/shared",
            }
        ]
        states = build_official_source_review.collect_existing_review_states(
            [
                {
                    "id": "old-row",
                    "decision": "reject",
                    "venue": "大蔵氷川神社",
                    "event_name": "大蔵本村睦会 盆踊り大会",
                    "source_url": "https://example.com/shared",
                }
            ]
        )

        preserved = build_official_source_review.apply_existing_review_states(rows, states)

        self.assertEqual(preserved, 0)
        self.assertEqual(rows[0]["decision"], "pending")

    def test_rare_signal_backcheck_skips_outside_tokyo_23(self):
        result = build_rare_signal_backcheck_queue.build(
            {
                "candidates": [
                    {
                        "candidate_id": "outside",
                        "promotion_target": "event",
                        "review_status": "needs_backcheck",
                        "possible_event_name": "大阪大学夏まつり 盆踊り",
                        "possible_venue": "大阪大学箕面キャンパス",
                    },
                    {
                        "candidate_id": "inside",
                        "promotion_target": "event",
                        "review_status": "needs_backcheck",
                        "possible_event_name": "神田明神納涼祭り 盆踊り",
                        "possible_area": "千代田区",
                    },
                ]
            },
            include_targets={"event"},
        )

        self.assertEqual([row["candidate_id"] for row in result["queue"]], ["inside"])
        self.assertEqual(result["skipped"][0]["candidate_id"], "outside")
        self.assertEqual(result["skipped"][0]["reason"], "outside_tokyo_23_scope")


if __name__ == "__main__":
    unittest.main()
