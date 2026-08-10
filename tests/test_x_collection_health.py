import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import collect
from collection_support.x_collection_health import (
    check_health_report,
    finalize_health_report,
    new_health_report,
    render_github_summary,
    write_health_report,
)


def payment_required():
    return urllib.error.HTTPError(
        "https://api.twitterapi.io/test",
        402,
        "Payment Required",
        {},
        None,
    )


class XCollectionHealthTest(unittest.TestCase):
    def keyword_config(self):
        return {
            "budget": {
                "cost_per_tweet_usd": 0.00015,
                "daily_usd": 10,
                "monthly_usd": 100,
            },
            "queries": [{"id": "q-bon", "query": "盆踊り"}],
            "max_pages_per_query": 1,
            "page_sleep_sec": 0,
        }

    def whitelist_config(self):
        return {
            "budget": {
                "cost_per_tweet_usd": 0.00015,
                "daily_usd": 10,
                "monthly_usd": 100,
            },
            "whitelist_batch_size": 1,
            "whitelist_max_pages_per_batch": 1,
            "page_sleep_sec": 0,
            "account_ranking": {"min_keep_post_score": 0},
        }

    def test_keyword_http_402_is_recorded_without_immediate_raise(self):
        health = new_health_report(collection_enabled=True)
        with (
            patch.object(collect, "TWITTERAPI_IO_KEY", "test"),
            patch.object(collect, "_load_x_config", return_value=self.keyword_config()),
            patch.object(collect, "_x_budget_state", return_value={}),
            patch.object(collect, "_x_search", side_effect=payment_required()),
        ):
            items, seen = collect.collect_x_voices(set(), health=health)

        finalize_health_report(health)
        self.assertEqual(items, [])
        self.assertEqual(seen, [])
        self.assertEqual(health["totals"]["http_402_count"], 1)
        self.assertIn("http_402_threshold:1>=1", health["failure_reasons"])
        self.assertEqual(health["status"], "unhealthy")

    def test_successful_but_zero_item_run_is_unhealthy(self):
        health = new_health_report(collection_enabled=True)
        with (
            patch.object(collect, "TWITTERAPI_IO_KEY", "test"),
            patch.object(collect, "_load_x_config", return_value=self.keyword_config()),
            patch.object(collect, "_x_budget_state", return_value={}),
            patch.object(collect, "_x_search", return_value={"tweets": []}),
        ):
            collect.collect_x_voices(set(), health=health)

        finalize_health_report(health)
        self.assertEqual(health["lanes"]["keyword"]["completed_units"], 1)
        self.assertIn("x_items_accepted_zero", health["failure_reasons"])

    def test_required_collection_fails_when_api_is_disabled(self):
        health = new_health_report(
            collection_enabled=False,
            collection_required=True,
        )

        finalize_health_report(health)

        self.assertEqual(health["status"], "unhealthy")
        self.assertIn("x_collection_required_but_disabled", health["failure_reasons"])

    def test_whitelist_402_after_partial_success_does_not_advance_since_time(self):
        health = new_health_report(collection_enabled=True)
        ranked = [
            {"handle": "@first", "since": 100, "reason": "test"},
            {"handle": "@second", "since": 100, "reason": "test"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(collect, "TWITTERAPI_IO_KEY", "test"),
                patch.object(collect, "X_BUDGET_FILE", str(Path(tmp) / "x_budget.json")),
                patch.object(collect, "_load_x_config", return_value=self.whitelist_config()),
                patch.object(collect, "load_whitelist_accounts", return_value=[{"handle": "@first"}, {"handle": "@second"}]),
                patch.object(collect, "_rank_whitelist_accounts", return_value=ranked),
                patch.object(collect, "_sync_x_account_scores_to_notion"),
                patch.object(collect, "_load_known_venues", return_value={}),
                patch.object(collect, "_x_budget_state", return_value={}),
                patch.object(collect, "_x_search", side_effect=[{"tweets": []}, payment_required()]),
                patch.object(collect, "_save_whitelist_since") as save_since,
            ):
                collect.collect_x_whitelist(set(), health=health)

        finalize_health_report(health)
        save_since.assert_not_called()
        lane = health["lanes"]["whitelist"]
        self.assertEqual(lane["planned_units"], 2)
        self.assertEqual(lane["completed_units"], 1)
        self.assertEqual(lane["http_errors"]["402"], 1)

    def test_whitelist_advances_since_time_only_after_every_batch_completes(self):
        health = new_health_report(collection_enabled=True)
        ranked = [
            {"handle": "@first", "since": 100, "reason": "test"},
            {"handle": "@second", "since": 100, "reason": "test"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(collect, "TWITTERAPI_IO_KEY", "test"),
                patch.object(collect, "X_BUDGET_FILE", str(Path(tmp) / "x_budget.json")),
                patch.object(collect, "_load_x_config", return_value=self.whitelist_config()),
                patch.object(collect, "load_whitelist_accounts", return_value=[{"handle": "@first"}, {"handle": "@second"}]),
                patch.object(collect, "_rank_whitelist_accounts", return_value=ranked),
                patch.object(collect, "_sync_x_account_scores_to_notion"),
                patch.object(collect, "_load_known_venues", return_value={}),
                patch.object(collect, "_x_budget_state", return_value={}),
                patch.object(collect, "_x_search", side_effect=[{"tweets": []}, {"tweets": []}]),
                patch.object(collect, "_save_whitelist_since") as save_since,
            ):
                collect.collect_x_whitelist(set(), health=health)

        save_since.assert_called_once()
        self.assertGreater(save_since.call_args.args[0], 0)
        self.assertEqual(health["lanes"]["whitelist"]["completed_units"], 2)

    def test_report_checker_fails_unhealthy_report_and_summary_has_unit_metrics(self):
        health = new_health_report(collection_enabled=True)
        health["lanes"] = {
            "keyword": {
                "planned_units": 1,
                "completed_units": 0,
                "attempts": 1,
                "successful_requests": 0,
                "failed_requests": 1,
                "http_errors": {"402": 1},
                "tweets_fetched": 0,
                "items_accepted": 0,
                "estimated_cost_usd": 0.0,
                "skipped_reason": None,
                "units": {
                    "q-bon": {
                        "attempts": 1,
                        "successful_requests": 0,
                        "failed_requests": 1,
                        "http_errors": {"402": 1},
                        "tweets_fetched": 0,
                        "items_accepted": 0,
                        "estimated_cost_usd": 0.0,
                        "completed": False,
                        "incomplete_reason": "HTTP 402",
                    }
                },
            }
        }
        finalize_health_report(health)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "health.json"
            summary_path = Path(tmp) / "step-summary.md"
            write_health_report(
                health,
                path,
                github_summary_path=summary_path,
            )
            self.assertEqual(check_health_report(path), 1)
            self.assertIn("keyword / q-bon", summary_path.read_text(encoding="utf-8"))

        summary = render_github_summary(health)
        self.assertIn("keyword / q-bon", summary)
        self.assertIn("HTTP 402", summary)
        self.assertIn("$0.00000", summary)


if __name__ == "__main__":
    unittest.main()
