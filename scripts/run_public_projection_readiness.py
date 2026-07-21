#!/usr/bin/env python3
"""Run the C-phase public projection readiness dry-run.

This script does not mutate the master DB or public data files. It exports the
current public JSON into an output directory, uses the internal source-map
sidecar for projection comparison, builds historical-reference change requests,
dry-runs those requests into a throwaway DB copy, and compares projection
readiness again.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_public_export_postprocessors import prepared_master_db


ROOT = Path(__file__).resolve().parents[1]
MASTER_DB = ROOT / "data" / "bon_odori_master.sqlite"


def root_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(command: list[str], env: dict[str, str] | None, quiet: bool) -> None:
    if not quiet:
        print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def export_public_json(python: str, out_dir: Path, today: str, quiet: bool) -> tuple[Path, Path]:
    public_dir = out_dir / "fresh_public"
    source_map = public_dir / "public_event_source_map.json"
    env = dict(os.environ)
    env["BON_ODORI_PUBLIC_OUT_DIR"] = str(public_dir)
    env["BON_ODORI_PUBLIC_EVENT_SOURCE_MAP_JSON"] = str(source_map)
    env["BON_ODORI_PUBLIC_DATE_PREDICTION_REPORT"] = str(public_dir / "public_date_prediction_apply_result.json")
    env["BON_ODORI_PUBLIC_TODAY"] = today
    run([python, "export_public_events.py"], env=env, quiet=quiet)
    return public_dir / "events_public.json", source_map


def compare_projection(
    python: str,
    public_events: Path,
    source_map: Path,
    master_db: Path,
    out_json: Path,
    out_md: Path,
    target_year: int,
    quiet: bool,
) -> None:
    run(
        [
            python,
            "-m",
            "public_json_postprocessors.compare_public_projection_sources",
            "--public-events",
            str(public_events),
            "--source-map",
            str(source_map),
            "--master-db",
            str(master_db),
            "--target-year",
            str(target_year),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ],
        env=None,
        quiet=quiet,
    )


def build_historical_requests(
    python: str,
    public_events: Path,
    source_map: Path,
    out_requests: Path,
    out_report: Path,
    quiet: bool,
) -> None:
    run(
        [
            python,
            "build_public_historical_reference_change_requests.py",
            "--public-events",
            str(public_events),
            "--source-map",
            str(source_map),
            "--master-db",
            str(MASTER_DB),
            "--out-requests",
            str(out_requests),
            "--out-report",
            str(out_report),
        ],
        env=None,
        quiet=quiet,
    )


def dry_run_historical_requests(
    python: str,
    requests: Path,
    out_db: Path,
    out_json: Path,
    out_md: Path,
    quiet: bool,
) -> None:
    run(
        [
            python,
            "-m",
            "report_apply.apply_change_requests",
            "--requests",
            str(requests),
            "--master-db",
            str(MASTER_DB),
            "--out-db",
            str(out_db),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ],
        env=None,
        quiet=quiet,
    )


def promote_historical_requests(
    python: str,
    requests: Path,
    out_json: Path,
    out_md: Path,
    quiet: bool,
) -> None:
    run(
        [
            python,
            "scripts/promote_change_requests_for_review.py",
            "--requests",
            str(requests),
            "--reviewed-by",
            "readiness機械検査（人レビュー未了）",
            "--review-note",
            "readiness機械検査用に自動生成。人レビュー済みではなく、実applyには使用しない。",
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ],
        env=None,
        quiet=quiet,
    )


def write_noop_historical_outputs(
    requests: Path,
    reviewed_json: Path,
    reviewed_md: Path,
    dry_run_json: Path,
    dry_run_md: Path,
) -> None:
    payload = load_json(requests)
    reviewed_payload = dict(payload)
    reviewed_payload.update(
        {
            "reviewed_by": "not_applicable (no requests)",
            "reviewed_at": None,
            "review_note": "No historical-reference requests were generated; promote and dry-run were skipped.",
        }
    )
    write_json(reviewed_json, reviewed_payload)
    reviewed_md.write_text(
        "# Reviewed historical-reference requests\n\n- request_count: 0\n- status: skipped_no_requests\n",
        encoding="utf-8",
    )
    dry_run_payload = {
        "mode": "skipped_no_requests",
        "applied": {"requests_applied": [], "requests_unresolved": []},
        "summary": {"issues_by_severity": {}, "audit_issues_by_severity": {}},
    }
    write_json(dry_run_json, dry_run_payload)
    dry_run_md.write_text(
        "# Historical-reference dry-run\n\n- request_count: 0\n- status: skipped_no_requests\n",
        encoding="utf-8",
    )


def build_mismatch_review(
    python: str,
    compare_report: Path,
    public_events: Path,
    out_json: Path,
    out_md: Path,
    quiet: bool,
) -> None:
    run(
        [
            python,
            "scripts/build_public_projection_mismatch_review.py",
            "--compare-report",
            str(compare_report),
            "--public-events",
            str(public_events),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ],
        env=None,
        quiet=quiet,
    )


def summarize(
    today: str,
    out_dir: Path,
    public_events: Path,
    source_map: Path,
    before_json: Path,
    requests_json: Path,
    reviewed_requests_json: Path,
    dry_run_json: Path,
    after_json: Path,
    mismatch_json: Path,
) -> dict[str, Any]:
    before = load_json(before_json)
    requests_payload = load_json(requests_json)
    requests = requests_payload.get("requests") or []
    reviewed_payload = load_json(reviewed_requests_json)
    reviewed_requests = reviewed_payload.get("requests") or []
    dry_run = load_json(dry_run_json)
    dry_run_applied = dry_run.get("applied") or {}
    dry_run_summary = dry_run.get("summary") or {}
    after = load_json(after_json)
    mismatch_review = load_json(mismatch_json)
    return {
        "generated_by": "scripts/run_public_projection_readiness.py",
        "today": today,
        "outputs": {
            "out_dir": str(out_dir),
            "public_events": str(public_events),
            "source_map": str(source_map),
            "before_compare": str(before_json),
            "historical_requests": str(requests_json),
            "reviewed_historical_requests": str(reviewed_requests_json),
            "dry_run_apply": str(dry_run_json),
            "after_historical_dry_run_compare": str(after_json),
            "mismatch_review": str(mismatch_json),
        },
        "before": {
            "public_event_count": before.get("public_event_count"),
            "source_counts": before.get("source_counts"),
            "summary": before.get("summary"),
            "blocking_row_count": before.get("blocking_row_count"),
        },
        "historical_requests": {
            "request_count": len(requests),
            "all_dry_run_only": all(request.get("dry_run_only") is True for request in requests),
        },
        "reviewed_historical_requests": {
            "request_count": len(reviewed_requests),
            "dry_run_only_count": sum(1 for request in reviewed_requests if request.get("dry_run_only")),
            "reviewed_by": reviewed_payload.get("reviewed_by"),
            "reviewed_at": reviewed_payload.get("reviewed_at"),
        },
        "dry_run_apply": {
            "requests_applied": len(dry_run_applied.get("requests_applied") or []),
            "requests_unresolved": len(dry_run_applied.get("requests_unresolved") or []),
            "issues_by_severity": dry_run_summary.get("issues_by_severity"),
            "audit_issues_by_severity": dry_run_summary.get("audit_issues_by_severity"),
        },
        "after_historical_dry_run": {
            "source_counts": after.get("source_counts"),
            "summary": after.get("summary"),
            "blocking_row_count": after.get("blocking_row_count"),
        },
        "mismatch_review": {
            "row_count": mismatch_review.get("row_count"),
            "statuses": mismatch_review.get("statuses"),
        },
    }


def run_readiness(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = root_path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with prepared_master_db(args.master_db):
        public_events, source_map = export_public_json(args.python, out_dir, args.today, args.quiet)
        before_json = out_dir / "public_projection_source_compare.json"
        before_md = out_dir / "public_projection_source_compare.md"
        compare_projection(
            args.python,
            public_events,
            source_map,
            MASTER_DB,
            before_json,
            before_md,
            args.target_year,
            args.quiet,
        )

        requests_json = out_dir / "public_historical_references.json"
        requests_md = out_dir / "public_historical_reference_change_requests.md"
        build_historical_requests(args.python, public_events, source_map, requests_json, requests_md, args.quiet)

        reviewed_requests_json = out_dir / "public_historical_references_reviewed.json"
        reviewed_requests_md = out_dir / "public_historical_references_reviewed.md"
        dry_run_db = out_dir / "historical_reference_dry_run.sqlite"
        dry_run_json = out_dir / "public_historical_references_dry_run_apply_report.json"
        dry_run_md = out_dir / "public_historical_references_dry_run_apply_report.md"
        request_count = len((load_json(requests_json).get("requests") or []))
        if request_count:
            promote_historical_requests(args.python, requests_json, reviewed_requests_json, reviewed_requests_md, args.quiet)
            dry_run_historical_requests(args.python, requests_json, dry_run_db, dry_run_json, dry_run_md, args.quiet)
            after_master_db = dry_run_db
        else:
            write_noop_historical_outputs(
                requests_json,
                reviewed_requests_json,
                reviewed_requests_md,
                dry_run_json,
                dry_run_md,
            )
            after_master_db = MASTER_DB

        after_json = out_dir / "public_projection_after_historical_dry_run.json"
        after_md = out_dir / "public_projection_after_historical_dry_run.md"
        compare_projection(
            args.python,
            public_events,
            source_map,
            after_master_db,
            after_json,
            after_md,
            args.target_year,
            args.quiet,
        )

        mismatch_json = out_dir / "public_projection_mismatch_review.json"
        mismatch_md = out_dir / "public_projection_mismatch_review.md"
        build_mismatch_review(args.python, after_json, public_events, mismatch_json, mismatch_md, args.quiet)

        summary = summarize(
            args.today,
            out_dir,
            public_events,
            source_map,
            before_json,
            requests_json,
            reviewed_requests_json,
            dry_run_json,
            after_json,
            mismatch_json,
        )
        write_json(out_dir / "readiness_summary.json", summary)
        return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run public projection readiness checks with a fresh internal source-map export."
    )
    parser.add_argument("--today", required=True, help="YYYY-MM-DD used by date-sensitive public export logic")
    parser.add_argument("--target-year", type=int, default=2026)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument(
        "--master-db",
        help="optional DB copied to data/bon_odori_master.sqlite while running in a clean worktree",
    )
    parser.add_argument("--out-dir", default="data/public_projection_readiness")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run_readiness(args)
    before = summary["before"]["blocking_row_count"]
    after = summary["after_historical_dry_run"]["blocking_row_count"]
    requests = summary["historical_requests"]["request_count"]
    reviewed = summary["reviewed_historical_requests"]["request_count"]
    print(
        "public projection readiness: "
        f"before_blocking={before} "
        f"historical_requests={requests} "
        f"reviewed_historical_requests={reviewed} "
        f"after_historical_dry_run_blocking={after} "
        f"mismatch_review_rows={summary['mismatch_review']['row_count']} "
        f"summary={summary['outputs']['out_dir']}/readiness_summary.json"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
