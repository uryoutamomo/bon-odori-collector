import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import collect
from collection_support import x_cost_ledger


class XCostLedgerTest(unittest.TestCase):
    def test_initial_actions_log_backfill_reconciles_to_shared_budget_total(self):
        ledger = x_cost_ledger.load_ledger(Path("data/x_cost_ledger.json"))
        backfill = [
            row for row in ledger["entries"]
            if row.get("date") == "2026-08-11"
            and row.get("source") == "github_actions_log_backfill"
        ]

        self.assertEqual({row["route"] for row in backfill}, {
            "search", "whitelist", "cohort_evidence", "unattributed",
        })
        self.assertAlmostEqual(sum(row["cost_usd"] for row in backfill), 0.7146)

    def test_record_run_appends_without_rewriting_prior_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x_cost_ledger.json"
            path.write_text(
                json.dumps({"schema_version": 1, "entries": [{"route": "search", "cost_usd": 0.1}]}),
                encoding="utf-8",
            )
            entry = x_cost_ledger.record_run(
                "search",
                cost_usd=0.003,
                requests=2,
                tweets_fetched=20,
                new_urls=4,
                voices_accepted=3,
                query_id="q-base",
                path=path,
                now=datetime(2026, 8, 12, tzinfo=timezone.utc),
            )
            saved = x_cost_ledger.load_ledger(path)

        self.assertEqual(len(saved["entries"]), 2)
        self.assertEqual(saved["entries"][0]["cost_usd"], 0.1)
        self.assertEqual(entry["date"], "2026-08-12")
        self.assertEqual(entry["query_id"], "q-base")
        self.assertEqual(entry["voices_accepted"], 3)

    def test_route_must_be_from_the_fixed_reporting_vocabulary(self):
        with self.assertRaisesRegex(ValueError, "unknown X cost route"):
            x_cost_ledger.record_run("typo", cost_usd=0)

    def test_candidate_and_social_workflows_write_their_own_route(self):
        root = Path(__file__).resolve().parents[1]
        candidate = (root / "review_x_candidate_posts.py").read_text(encoding="utf-8")
        social = (root / "discover_x_social_graph.py").read_text(encoding="utf-8")

        self.assertIn('"candidate_probe"', candidate)
        self.assertIn('"social_graph"', social)
        self.assertIn("x_cost_ledger.record_run", candidate)
        self.assertIn("x_cost_ledger.record_run", social)

    def test_keyword_collection_records_each_query_with_cost_and_outcomes(self):
        cfg = {
            "budget": {"cost_per_tweet_usd": 0.00015, "daily_usd": 10, "monthly_usd": 100},
            "queries": [{"id": "q-base", "query": "盆踊り"}],
            "max_pages_per_query": 1,
            "page_sleep_sec": 0,
        }
        tweets = [{"id": "1", "text": "盆踊りに行った", "author": {"userName": "tester"}}]
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(collect, "TWITTERAPI_IO_KEY", "test"),
                patch.object(collect, "X_BUDGET_FILE", str(Path(tmp) / "x_budget.json")),
                patch.object(collect, "_load_x_config", return_value=cfg),
                patch.object(collect, "_x_budget_state", return_value={}),
                patch.object(collect, "_x_search", return_value={"tweets": tweets}),
                patch.object(collect, "capture_raw_x_posts"),
                patch.object(collect, "_append_x_log_row"),
                patch.object(x_cost_ledger, "record_run") as record_run,
            ):
                items, _ = collect.collect_x_voices(set())

        self.assertEqual(len(items), 1)
        record_run.assert_called_once_with(
            "search",
            path=Path(tmp).joinpath("x_cost_ledger.json"),
            query_id="q-base",
            cost_usd=0.00015,
            requests=1,
            tweets_fetched=1,
            new_urls=1,
            voices_accepted=1,
        )


if __name__ == "__main__":
    unittest.main()
