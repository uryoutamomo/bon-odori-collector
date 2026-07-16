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

    def test_summarize_reports_before_and_after_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            before = tmp / "before.json"
            requests = tmp / "requests.json"
            dry_run = tmp / "dry_run.json"
            after = tmp / "after.json"
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
            dry_run.write_text(
                json.dumps(
                    {
                        "requests_applied": 2,
                        "requests_unresolved": 0,
                        "issues_by_severity": {},
                        "audit_issues_by_severity": {},
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

            summary = MODULE.summarize(
                "2026-07-16",
                tmp,
                tmp / "events.json",
                tmp / "source_map.json",
                before,
                requests,
                dry_run,
                after,
            )

        self.assertEqual(summary["before"]["blocking_row_count"], 8)
        self.assertEqual(summary["historical_requests"]["request_count"], 2)
        self.assertTrue(summary["historical_requests"]["all_dry_run_only"])
        self.assertEqual(summary["dry_run_apply"]["requests_applied"], 2)
        self.assertEqual(summary["after_historical_dry_run"]["blocking_row_count"], 1)


if __name__ == "__main__":
    unittest.main()
