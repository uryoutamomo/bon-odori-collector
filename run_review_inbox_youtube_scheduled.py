#!/usr/bin/env python3
"""Default-off scheduled dual-write for the complete YouTube review aggregate."""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping

from review_inbox_adapters.parity import load_adapted_snapshot
from review_inbox_adapters.production_wiring import MasterDbS3ArtifactStore, public_projection_digest
from review_inbox_adapters.shadow_execution_gate import (
    prepare_evidence_paths,
    require_explicit_environment as require_shadow_environment,
    require_outside_cron_window,
    validate_public_today,
    write_report,
)
from review_inbox_adapters.source_adapter import write_adapted_snapshot
from review_inbox_adapters.source_writer import ArtifactStore, SourceWriterError, SourceWriterFlags, run_source_shadow
from review_inbox_adapters.youtube_adapter import DEFAULT_INPUT as ACTIVE_INPUT
from review_inbox_adapters.youtube_aggregate import build_aggregate_snapshot, require_complete_aggregate
from review_inbox_adapters.youtube_user_confirmation_adapter import DEFAULT_INPUT as USER_INPUT
from review_inbox_adapters.youtube_year_backfill_adapter import DEFAULT_INPUT as YEAR_INPUT


CONFIRM = "RUN SCHEDULED YOUTUBE AGGREGATE DUAL WRITE"
SCHEDULED_ENABLE_ENV = "REVIEW_INBOX_YOUTUBE_AGGREGATE_SCHEDULED_ENABLED"


def require_explicit_environment(environ: Mapping[str, str]) -> SourceWriterFlags:
    if environ.get(SCHEDULED_ENABLE_ENV, "").strip().lower() != "true":
        raise SourceWriterError("scheduled YouTube aggregate dual-write is off")
    return require_shadow_environment(
        environ,
        dual_write_mode="bulk",
        selection_mode="all",
        run_label="scheduled YouTube aggregate dual-write",
    )


def run_scheduled(
    args: argparse.Namespace,
    *,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
    store_factory: Callable[[argparse.Namespace], ArtifactStore] | None = None,
    digest_function: Callable[..., str] = public_projection_digest,
) -> dict:
    environ = os.environ if environ is None else environ
    if not args.execute:
        raise SourceWriterError("scheduled YouTube aggregate execution is off")
    if args.confirm != CONFIRM:
        raise SourceWriterError(f"--confirm must be exactly: {CONFIRM}")
    flags = require_explicit_environment(environ)
    require_outside_cron_window(
        now, run_label="scheduled YouTube aggregate dual-write", environ=environ
    )
    observation_id = str(args.observation_id).strip()
    if not observation_id:
        raise SourceWriterError("--observation-id is required")
    validate_public_today(args.public_today)
    active_input, snapshot_path, report_path = prepare_evidence_paths(
        input_path=args.active_input,
        snapshot_path=args.snapshot_out,
        report_path=args.report_out,
        run_label="scheduled YouTube aggregate dual-write",
    )
    inputs = [active_input, Path(args.year_input).resolve(), Path(args.user_input).resolve()]
    if len(set(inputs)) != 3:
        raise SourceWriterError("scheduled YouTube aggregate inputs must be distinct")
    if any(path in {snapshot_path, report_path} for path in inputs):
        raise SourceWriterError("input, snapshot, and report paths must be distinct")
    try:
        snapshot = build_aggregate_snapshot(*inputs)
        require_complete_aggregate(snapshot)
    except (OSError, ValueError) as exc:
        raise SourceWriterError(str(exc)) from exc
    snapshot["write_mode"] = "scheduled_dual_write_explicit_gate"
    snapshot["execution_entrypoint"] = "run_review_inbox_youtube_scheduled.py"
    write_adapted_snapshot(snapshot, snapshot_path)
    frozen_snapshot = load_adapted_snapshot(snapshot_path)
    require_complete_aggregate(frozen_snapshot)

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
    )
    report["entrypoint"] = {
        "name": "run_review_inbox_youtube_scheduled.py",
        "confirm": "matched",
        "public_today": args.public_today,
        "cron_window_checked": True,
        "legacy_writer_retained": flags.legacy_writer_enabled,
        "reader_mode": flags.reader_mode,
        "source_queue": "youtube_aggregate",
        "required_queues": snapshot["aggregate"]["required_queues"],
    }
    write_report(report_path, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-input", type=Path, default=ACTIVE_INPUT)
    parser.add_argument("--year-input", type=Path, default=YEAR_INPUT)
    parser.add_argument("--user-input", type=Path, default=USER_INPUT)
    parser.add_argument("--snapshot-out", type=Path, required=True)
    parser.add_argument("--report-out", type=Path, required=True)
    parser.add_argument("--observation-id", required=True)
    parser.add_argument("--public-target-year", type=int, required=True)
    parser.add_argument("--public-today", required=True)
    parser.add_argument("--bucket", default="")
    parser.add_argument("--prefix", default="")
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_scheduled(args)
    print(
        "scheduled YouTube aggregate review inbox dual-write complete: "
        f"published={report['published']} no_op={report['no_op']} Rend={report['rend']['checksum']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
