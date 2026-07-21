import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_public_projection_readiness.py"
SPEC = importlib.util.spec_from_file_location("run_public_projection_readiness", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RunPublicProjectionReadinessTest(unittest.TestCase):
    def test_export_public_json_uses_non_public_sidecar_output(self):
        with patch.object(MODULE, "run") as run:
            public_events, source_map = MODULE.export_public_json(
                "python3",
                Path("/tmp/readiness"),
                today="2026-07-16",
                quiet=True,
            )

        self.assertEqual(public_events, Path("/tmp/readiness/fresh_public/events_public.json"))
        self.assertEqual(source_map, Path("/tmp/readiness/fresh_public/public_event_source_map.json"))
        command = run.call_args.args[0]
        env = run.call_args.kwargs["env"]
        self.assertEqual(command, ["python3", "export_public_events.py"])
        self.assertEqual(env["BON_ODORI_PUBLIC_OUT_DIR"], "/tmp/readiness/fresh_public")
        self.assertEqual(
            env["BON_ODORI_PUBLIC_EVENT_SOURCE_MAP_JSON"],
            "/tmp/readiness/fresh_public/public_event_source_map.json",
        )
        self.assertEqual(env["BON_ODORI_PUBLIC_TODAY"], "2026-07-16")

    def test_compare_projection_uses_public_json_postprocessors_module(self):
        with patch.object(MODULE, "run") as run:
            MODULE.compare_projection(
                "python3",
                Path("/tmp/readiness/fresh_public/events_public.json"),
                Path("/tmp/readiness/fresh_public/public_event_source_map.json"),
                Path("/tmp/master.sqlite"),
                Path("/tmp/readiness/compare.json"),
                Path("/tmp/readiness/compare.md"),
                2026,
                quiet=True,
            )

        command = run.call_args.args[0]
        self.assertEqual(
            command[:3],
            ["python3", "-m", "public_json_postprocessors.compare_public_projection_sources"],
        )
        self.assertNotIn("compare_public_projection_sources.py", command)

    def test_promote_historical_requests_marks_output_as_machine_only(self):
        with patch.object(MODULE, "run") as run:
            MODULE.promote_historical_requests(
                "python3",
                Path("requests.json"),
                Path("reviewed.json"),
                Path("reviewed.md"),
                quiet=True,
            )

        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--reviewed-by") + 1], "readiness機械検査（人レビュー未了）")
        self.assertIn("実applyには使用しない", command[command.index("--review-note") + 1])

    def test_write_noop_historical_outputs_supports_empty_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            requests = tmp / "requests.json"
            reviewed_json = tmp / "reviewed.json"
            reviewed_md = tmp / "reviewed.md"
            dry_run_json = tmp / "dry_run.json"
            dry_run_md = tmp / "dry_run.md"
            requests.write_text(
                json.dumps({"request_type": "rdb_change_requests", "requests": []}),
                encoding="utf-8",
            )

            MODULE.write_noop_historical_outputs(
                requests,
                reviewed_json,
                reviewed_md,
                dry_run_json,
                dry_run_md,
            )

            reviewed = json.loads(reviewed_json.read_text(encoding="utf-8"))
            dry_run = json.loads(dry_run_json.read_text(encoding="utf-8"))
        self.assertEqual(reviewed["requests"], [])
        self.assertEqual(reviewed["reviewed_by"], "not_applicable (no requests)")
        self.assertEqual(dry_run["mode"], "skipped_no_requests")
        self.assertEqual(dry_run["applied"]["requests_applied"], [])

    def test_summarize_reports_before_and_after_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            before = tmp / "before.json"
            requests = tmp / "requests.json"
            reviewed = tmp / "reviewed.json"
            dry_run = tmp / "dry_run.json"
            after = tmp / "after.json"
            mismatch = tmp / "mismatch.json"
            before.write_text(
                json.dumps(
                    {
                        "public_event_count": 10,
                        "source_counts": {"sidecar_hits": 10},
                        "summary": {"historical:missing_rdb_source": 8},
                        "blocking_row_count": 8,
                    }
                ),
                encoding="utf-8",
            )
            requests.write_text(
                json.dumps(
                    {
                        "requests": [
                            {"request_id": "r1", "dry_run_only": True},
                            {"request_id": "r2", "dry_run_only": True},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            reviewed.write_text(
                json.dumps(
                    {
                        "reviewed_by": "おと（Codex）",
                        "reviewed_at": "2026-07-17T00:00:00+00:00",
                        "requests": [
                            {"request_id": "r1"},
                            {"request_id": "r2"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            dry_run.write_text(
                json.dumps(
                    {
                        "applied": {
                            "requests_applied": [{"request_id": "r1"}, {"request_id": "r2"}],
                            "requests_unresolved": [],
                        },
                        "summary": {
                            "issues_by_severity": {},
                            "audit_issues_by_severity": {},
                        },
                    }
                ),
                encoding="utf-8",
            )
            after.write_text(
                json.dumps(
                    {
                        "source_counts": {"sidecar_hits": 10},
                        "summary": {"historical:match": 8},
                        "blocking_row_count": 1,
                    }
                ),
                encoding="utf-8",
            )
            mismatch.write_text(
                json.dumps({"row_count": 0, "statuses": ["date_mismatch"]}),
                encoding="utf-8",
            )

            summary = MODULE.summarize(
                "2026-07-16",
                tmp,
                tmp / "events.json",
                tmp / "source_map.json",
                before,
                requests,
                reviewed,
                dry_run,
                after,
                mismatch,
            )

        self.assertEqual(summary["before"]["blocking_row_count"], 8)
        self.assertEqual(summary["historical_requests"]["request_count"], 2)
        self.assertTrue(summary["historical_requests"]["all_dry_run_only"])
        self.assertEqual(summary["reviewed_historical_requests"]["request_count"], 2)
        self.assertEqual(summary["reviewed_historical_requests"]["dry_run_only_count"], 0)
        self.assertEqual(summary["dry_run_apply"]["requests_applied"], 2)
        self.assertEqual(summary["dry_run_apply"]["requests_unresolved"], 0)
        self.assertEqual(summary["dry_run_apply"]["issues_by_severity"], {})
        self.assertEqual(summary["dry_run_apply"]["audit_issues_by_severity"], {})
        self.assertEqual(summary["after_historical_dry_run"]["blocking_row_count"], 1)
        self.assertEqual(summary["mismatch_review"]["row_count"], 0)


if __name__ == "__main__":
    unittest.main()
