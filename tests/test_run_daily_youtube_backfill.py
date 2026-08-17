import io
import unittest
import urllib.error

import run_daily_youtube_backfill as daily


class Args:
    month = 7
    limit = 1
    max_results = 5
    dry_run = False
    until_quota_limited = True
    max_batches = 0
    focus_months = None
    retry_selected = False
    retry_min_candidates = 10
    retry_cooldown_days = 30
    max_consecutive_no_yield = 10
    as_of = "2026-08-17"

    def __init__(self):
        self.retry_state = daily.empty_retry_state()


def queue_row(queue_id, score):
    return {
        "queue_id": queue_id,
        "priority": "high",
        "priority_score": score,
        "target_year": 2025,
        "event_name": f"イベント{queue_id}",
        "venue": "会場",
        "public_date": "2025-07-01",
        "search_queries": [f"盆踊り {queue_id}", f"会場 {queue_id}"],
    }


class RunDailyYoutubeBackfillTest(unittest.TestCase):
    def test_bootstrap_puts_existing_searches_on_cooldown(self):
        state = daily.empty_retry_state()
        candidates = {"selected_queue_rows": [queue_row("q1", 30)]}

        count = daily.bootstrap_retry_state(candidates, state, "2026-08-17", 30)

        self.assertEqual(count, 1)
        self.assertEqual(state["attempts"]["q1"]["next_retry_on"], "2026-09-16")
        self.assertEqual(state["attempts"]["q1"]["last_result"], "bootstrap_existing")

    def test_retry_cooldown_suppresses_row_until_due_date(self):
        row = queue_row("q1", 30)
        queue = {"rows": [row]}
        candidates = {"selected_queue_rows": [row], "candidates": []}
        state = daily.empty_retry_state()
        daily.bootstrap_retry_state(candidates, state, "2026-08-17", 30)

        blocked = daily.retryable_rows(
            queue,
            candidates,
            7,
            set(),
            10,
            retry_state=state,
            run_date="2026-09-15",
        )
        due = daily.retryable_rows(
            queue,
            candidates,
            7,
            set(),
            10,
            retry_state=state,
            run_date="2026-09-16",
        )

        self.assertEqual(blocked, [])
        self.assertEqual([item["queue_id"] for item in due], ["q1"])

    def test_unseen_rows_across_focus_months_precede_retries(self):
        retry_row = queue_row("q8-retry", 50)
        retry_row["public_date"] = "2025-08-01"
        new_row = queue_row("q7-new", 10)
        queue = {"rows": [retry_row, new_row]}
        candidates = {"selected_queue_rows": [retry_row], "candidates": []}
        args = Args()
        args.month = 8
        args.focus_months = [8, 7]
        args.retry_selected = True

        month, selected, _remaining = daily.next_rows_for_args(queue, candidates, args)

        self.assertEqual(month, 7)
        self.assertEqual([row["queue_id"] for row in selected], ["q7-new"])

    def test_first_month_with_rows_skips_empty_start_month(self):
        row = queue_row("q1", 30)
        row["public_date"] = "2025-08-01"
        queue = {"rows": [row]}

        self.assertEqual(daily.first_month_with_rows(queue, {}, start_month=7, limit=1), 8)

    def test_next_rows_prefers_newer_target_year_for_same_month(self):
        row_2023 = queue_row("q1", 30)
        row_2023["target_year"] = 2023
        row_2024 = queue_row("q2", 30)
        row_2024["target_year"] = 2024
        queue = {"rows": [row_2023, row_2024]}

        selected, _remaining = daily.next_rows(queue, {}, month=7, limit=1)

        self.assertEqual(selected[0]["target_year"], 2024)

    def test_quota_limited_error_detects_youtube_403_reason(self):
        error = urllib.error.HTTPError(
            "https://www.googleapis.com/youtube/v3/search",
            403,
            "Forbidden",
            None,
            io.BytesIO(b'{"error":{"errors":[{"reason":"quotaExceeded"}]}}'),
        )
        body = daily.http_error_body(error)

        self.assertTrue(daily.is_quota_limited_http_error(error, body))
        self.assertIn("quotaExceeded", daily.quota_error_message(error, body))

    def test_run_harvest_batches_continues_until_max_batches(self):
        queue = {"rows": [queue_row("q1", 30), queue_row("q2", 20), queue_row("q3", 10)]}
        args = Args()
        args.max_batches = 2
        calls = []

        original_harvest = daily.harvest_mod.harvest
        original_write_json = daily.harvest_mod.atomic_write_json
        original_write_text = daily.harvest_mod.atomic_write_text

        def fake_harvest(batch_queue, **_kwargs):
            row = batch_queue["rows"][0]
            calls.append(row["queue_id"])
            return {
                "generated_at": "now",
                "selected_queue_count": 1,
                "max_results_per_query": 5,
                "selected_queue_rows": [row],
                "candidates": [{
                    "queue_id": row["queue_id"],
                    "video_id": f"v-{row['queue_id']}",
                    "video_url": f"https://www.youtube.com/watch?v=v-{row['queue_id']}",
                    "score": 80,
                    "status": "strong",
                    "target_year": row["target_year"],
                    "event_name": row["event_name"],
                    "venue": row["venue"],
                    "detected_event_date": "2025-07-01",
                    "channel_title": "channel",
                    "title": row["event_name"],
                }],
                "summary": {"candidate_count": 1, "strong_count": 1, "review_count": 0},
            }

        try:
            daily.harvest_mod.harvest = fake_harvest
            daily.harvest_mod.atomic_write_json = lambda *_args, **_kwargs: None
            daily.harvest_mod.atomic_write_text = lambda *_args, **_kwargs: None

            result = daily.run_harvest_batches(queue, {}, args, api_key="key")
        finally:
            daily.harvest_mod.harvest = original_harvest
            daily.harvest_mod.atomic_write_json = original_write_json
            daily.harvest_mod.atomic_write_text = original_write_text

        self.assertEqual(result["status"], "harvested_max_batches")
        self.assertEqual(calls, ["q1", "q2"])
        self.assertEqual(result["completed_batches"], 2)
        self.assertEqual(result["selected_rows"], 2)
        self.assertEqual(result["remaining_rows_after"], 1)

    def test_run_harvest_batches_stops_cleanly_on_quota_limit(self):
        queue = {"rows": [queue_row("q1", 30)]}
        args = Args()

        original_harvest = daily.harvest_mod.harvest

        def fake_harvest(*_args, **_kwargs):
            raise urllib.error.HTTPError(
                "https://www.googleapis.com/youtube/v3/search",
                403,
                "Forbidden",
                None,
                io.BytesIO(b'{"error":{"errors":[{"reason":"quotaExceeded"}]}}'),
            )

        try:
            daily.harvest_mod.harvest = fake_harvest
            result = daily.run_harvest_batches(queue, {}, args, api_key="key")
        finally:
            daily.harvest_mod.harvest = original_harvest

        self.assertEqual(result["status"], "quota_limited")
        self.assertEqual(result["completed_batches"], 0)
        self.assertEqual(result["selected_rows"], 1)
        self.assertEqual(result["remaining_rows_after"], 1)
        self.assertIn("quotaExceeded", result["error"])
        self.assertNotIn("q1", args.retry_state["attempts"])

    def test_run_harvest_batches_stops_after_consecutive_no_yield(self):
        queue = {"rows": [queue_row("q1", 30), queue_row("q2", 20), queue_row("q3", 10)]}
        args = Args()
        args.max_consecutive_no_yield = 2
        calls = []

        original_harvest = daily.harvest_mod.harvest
        original_write_json = daily.harvest_mod.atomic_write_json
        original_write_text = daily.harvest_mod.atomic_write_text

        def fake_harvest(batch_queue, **_kwargs):
            row = batch_queue["rows"][0]
            calls.append(row["queue_id"])
            return {
                "generated_at": "now",
                "selected_queue_count": 1,
                "selected_queue_rows": [row],
                "candidates": [],
                "summary": {"candidate_count": 0, "strong_count": 0, "review_count": 0},
            }

        try:
            daily.harvest_mod.harvest = fake_harvest
            daily.harvest_mod.atomic_write_json = lambda *_args, **_kwargs: None
            daily.harvest_mod.atomic_write_text = lambda *_args, **_kwargs: None
            result = daily.run_harvest_batches(queue, {}, args, api_key="key")
        finally:
            daily.harvest_mod.harvest = original_harvest
            daily.harvest_mod.atomic_write_json = original_write_json
            daily.harvest_mod.atomic_write_text = original_write_text

        self.assertEqual(result["status"], "harvested_no_yield_limit")
        self.assertEqual(calls, ["q1", "q2"])
        self.assertEqual(result["new_candidates"], 0)
        self.assertEqual(result["consecutive_no_yield"], 2)
        self.assertEqual(args.retry_state["attempts"]["q1"]["next_retry_on"], "2026-09-16")
        self.assertEqual(args.retry_state["attempts"]["q2"]["last_result"], "no_yield")

    def test_regenerate_outputs_uses_single_public_export_path(self):
        commands = []
        original_run_command = daily.run_command
        try:
            daily.run_command = lambda command: commands.append(command) or {"returncode": 0}

            daily.regenerate_outputs(7, 2027, "2027-06-17")
        finally:
            daily.run_command = original_run_command

        public_export_commands = [
            command
            for command in commands
            if command[:2] == ["python3", "export_public_events.py"]
        ]
        self.assertEqual(
            public_export_commands,
            [[
                "python3",
                "export_public_events.py",
                "--target-year",
                "2027",
                "--today",
                "2027-06-17",
            ]],
        )
        self.assertIn(
            [
                "python3",
                "-m",
                "youtube_backfill.build_event_schedule_rules",
                "--target-year",
                "2027",
            ],
            commands,
        )
        self.assertNotIn(["python3", "apply_public_date_predictions.py"], commands)
        self.assertNotIn(["python3", "apply_public_season_hints.py"], commands)
        self.assertFalse(
            any(command[:2] == ["python3", "apply_public_historical_references.py"] for command in commands)
        )


if __name__ == "__main__":
    unittest.main()
