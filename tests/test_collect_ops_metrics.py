import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import collect_ops_metrics as metrics


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class CollectOpsMetricsTest(unittest.TestCase):
    def test_latest_reports_show_daily_youtube_run_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            write_json(
                data_dir / "youtube_daily_backfill_report.json",
                {
                    "generated_at": "2026-06-25T21:41:59+00:00",
                    "status": "harvested_until_quota_limited",
                    "selected_rows": 3,
                    "completed_batches": 2,
                    "remaining_rows_before": 94,
                    "remaining_rows_after": 92,
                    "estimated_search_calls": 6,
                },
            )
            write_json(
                data_dir / "youtube_year_backfill_candidates.json",
                {
                    "summary": {
                        "candidate_count": 556,
                        "strong_count": 183,
                        "review_count": 48,
                        "status_counts": {"weak": 325},
                    },
                    "selected_queue_rows": [{"queue_id": "q1"}],
                },
            )
            write_json(data_dir / "month_06_youtube_backfill_queue.json", {"summary": {"items": 0}})

            current = metrics.collect_metrics(
                data_dir=data_dir,
                now=datetime(2026, 6, 25, 21, 42, tzinfo=timezone.utc),
            )
            markdown = metrics.render_latest_markdown(current, [current])
            dashboard = metrics.render_dashboard([current])

        self.assertEqual(current["snapshot_date"], "2026-06-26")
        self.assertEqual(current["youtube_run_status"], "harvested_until_quota_limited")
        self.assertEqual(current["youtube_run_selected_rows"], 3)
        self.assertEqual(current["youtube_run_completed_batches"], 2)
        self.assertEqual(current["youtube_run_remaining_before"], 94)
        self.assertEqual(current["youtube_run_remaining_after"], 92)
        self.assertEqual(current["youtube_run_estimated_search_calls"], 6)

        self.assertIn("| 今回選択 | 3 |", markdown)
        self.assertIn("| 完了バッチ | 2 |", markdown)
        self.assertIn("| 実行前の残り | 94 |", markdown)
        self.assertIn("| 今回対象の残り | 92 |", markdown)
        self.assertIn("| 推定検索数 | 6 |", markdown)

        self.assertIn("YouTube APIの上限まで取得しました。", dashboard)
        self.assertIn("選択 3 件、完了 2 batches、残り 94 → 92、推定検索 6 件", dashboard)
        self.assertIn('<div class="metric-label">今回選択</div><div class="metric-value">3</div>', dashboard)


if __name__ == "__main__":
    unittest.main()
