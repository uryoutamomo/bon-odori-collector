#!/usr/bin/env python3
"""Explicitly gated one-item x_gap review-inbox canary runner.

This entrypoint is default-off and intentionally has no workflow wiring.  It
only accepts one row from lane2_operator_review or lane3_user_review; lane1
plans and archived candidates remain outside the review-inbox write path.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from review_inbox_adapters.parity import load_adapted_snapshot
from review_inbox_adapters.production_wiring import (
    MasterDbS3ArtifactStore,
    public_projection_digest,
)
from review_inbox_adapters.shadow_execution_gate import (
    prepare_evidence_paths,
    require_explicit_environment as require_shadow_environment,
    require_outside_cron_window as require_shadow_outside_cron_window,
    validate_expected_rstart,
    validate_public_today,
    write_report,
)
from review_inbox_adapters.source_adapter import write_adapted_snapshot
from review_inbox_adapters.source_writer import (
    ArtifactStore,
    SourceWriterError,
    SourceWriterFlags,
    run_source_shadow,
)
from review_inbox_adapters.x_gap_adapter import (
    DEFAULT_LANES_INPUT,
    build_canary_snapshot,
)


CONFIRM = "RUN X GAP REVIEW INBOX CANARY"


def require_explicit_environment(environ: Mapping[str, str]) -> SourceWriterFlags:
    return require_shadow_environment(
        environ,
        dual_write_mode="canary",
        selection_mode="canary",
        run_label="x gap review-inbox canary",
    )


def require_outside_cron_window(now: datetime | None = None) -> None:
    require_shadow_outside_cron_window(now, run_label="x gap review-inbox canary")


def run_canary(
    args: argparse.Namespace,
    *,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
    store_factory: Callable[[argparse.Namespace], ArtifactStore] | None = None,
    digest_function: Callable[..., str] = public_projection_digest,
) -> dict[str, Any]:
    environ = os.environ if environ is None else environ
    if not args.execute:
        raise SourceWriterError(
            "x gap canary execution is off; pass --execute only after execution GO"
        )
    if args.confirm != CONFIRM:
        raise SourceWriterError(f"--confirm must be exactly: {CONFIRM}")
    flags = require_explicit_environment(environ)
    require_outside_cron_window(now)

    source_key = str(args.canary_source_key or "").strip()
    if not source_key:
        raise SourceWriterError("--canary-source-key is required")
    observation_id = str(args.observation_id or "").strip()
    if not observation_id:
        raise SourceWriterError("--observation-id is required")
    expected_rstart = validate_expected_rstart(args.expect_rstart_checksum)
    validate_public_today(args.public_today)
    input_path, snapshot_path, report_path = prepare_evidence_paths(
        input_path=args.input,
        snapshot_path=args.snapshot_out,
        report_path=args.report_out,
        run_label="x gap canary",
    )
    try:
        snapshot = build_canary_snapshot(input_path, canary_source_key=source_key)
    except (OSError, ValueError) as exc:
        raise SourceWriterError(str(exc)) from exc
    if snapshot.get("source_id") != "x_gap" or snapshot.get("item_count") != 1:
        raise SourceWriterError("x gap canary must contain exactly one x_gap item")
    if snapshot["items"][0].get("source_key") != source_key:
        raise SourceWriterError("x gap canary selected the wrong source key")
    if snapshot.get("lane") not in {"lane2_operator_review", "lane3_user_review"}:
        raise SourceWriterError("x gap canary selected a non-reviewable lane")
    snapshot["write_mode"] = "canary_shadow_explicit_gate"
    snapshot["execution_entrypoint"] = "run_review_inbox_x_gap_canary.py"
    write_adapted_snapshot(snapshot, snapshot_path)
    frozen_snapshot = load_adapted_snapshot(snapshot_path)

    factory = store_factory or (
        lambda value: MasterDbS3ArtifactStore(bucket=value.bucket, prefix=value.prefix)
    )
    report = run_source_shadow(
        store=factory(args),
        adapted_snapshot=frozen_snapshot,
        observation_id=observation_id,
        public_projection_digest=lambda db: digest_function(
            db, target_year=args.public_target_year, today=args.public_today
        ),
        flags=flags,
        work_dir=Path(args.work_dir) if args.work_dir else None,
        expected_rstart_checksum=expected_rstart,
    )
    report["entrypoint"] = {
        "name": "run_review_inbox_x_gap_canary.py",
        "confirm": "matched",
        "public_today": args.public_today,
        "cron_window_checked": True,
        "canary_source_key": source_key,
        "lane": snapshot["lane"],
    }
    write_report(report_path, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_LANES_INPUT)
    parser.add_argument("--canary-source-key", required=True)
    parser.add_argument("--snapshot-out", type=Path, required=True)
    parser.add_argument("--report-out", type=Path, required=True)
    parser.add_argument("--observation-id", required=True)
    parser.add_argument("--expect-rstart-checksum", required=True)
    parser.add_argument("--public-target-year", type=int, required=True)
    parser.add_argument("--public-today", required=True, help="fixed JST date, YYYY-MM-DD")
    parser.add_argument("--bucket", default="")
    parser.add_argument("--prefix", default="")
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_canary(args)
    print(
        "x gap review-inbox canary complete: "
        f"published={report['published']} no_op={report['no_op']} "
        f"Rend={report['rend']['checksum']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
