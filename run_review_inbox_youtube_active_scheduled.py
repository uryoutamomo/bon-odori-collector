#!/usr/bin/env python3
"""Default-off scheduled dual-write for YouTube active-video reviews."""

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
from review_inbox_adapters.source_writer import (
    ArtifactStore,
    SourceWriterError,
    SourceWriterFlags,
    run_source_shadow,
)
from review_inbox_adapters.youtube_adapter import DEFAULT_INPUT, build_snapshot


CONFIRM = "RUN SCHEDULED YOUTUBE ACTIVE DUAL WRITE"
SCHEDULED_ENABLE_ENV = "REVIEW_INBOX_YOUTUBE_ACTIVE_SCHEDULED_ENABLED"


def require_explicit_environment(environ: Mapping[str, str]) -> SourceWriterFlags:
    if environ.get(SCHEDULED_ENABLE_ENV, "").strip().lower() != "true":
        raise SourceWriterError("scheduled YouTube active dual-write is off")
    return require_shadow_environment(
        environ,
        dual_write_mode="bulk",
        selection_mode="all",
        run_label="scheduled YouTube active dual-write",
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
        raise SourceWriterError("scheduled YouTube active execution is off")
    if args.confirm != CONFIRM:
        raise SourceWriterError(f"--confirm must be exactly: {CONFIRM}")
    flags = require_explicit_environment(environ)
    require_outside_cron_window(now, run_label="scheduled YouTube active dual-write")

    observation_id = str(args.observation_id).strip()
    if not observation_id:
        raise SourceWriterError("--observation-id is required")
    validate_public_today(args.public_today)
    input_path, snapshot_path, report_path = prepare_evidence_paths(
        input_path=args.input,
        snapshot_path=args.snapshot_out,
        report_path=args.report_out,
        run_label="scheduled YouTube active dual-write",
    )

    try:
        snapshot = build_snapshot(input_path)
    except (OSError, ValueError) as exc:
        raise SourceWriterError(str(exc)) from exc
    if snapshot.get("source_id") != "youtube_evidence":
        raise SourceWriterError("scheduled YouTube active snapshot has the wrong source_id")
    if snapshot.get("selection", {}).get("mode") != "all":
        raise SourceWriterError("scheduled YouTube active snapshot must select all pending items")
    snapshot["write_mode"] = "scheduled_dual_write_explicit_gate"
    snapshot["execution_entrypoint"] = "run_review_inbox_youtube_active_scheduled.py"
    write_adapted_snapshot(snapshot, snapshot_path)
    frozen_snapshot = load_adapted_snapshot(snapshot_path)

    factory = store_factory or (
        lambda value: MasterDbS3ArtifactStore(bucket=value.bucket, prefix=value.prefix)
    )
    report = run_source_shadow(
        store=factory(args),
        adapted_snapshot=frozen_snapshot,
        observation_id=observation_id,
        public_projection_digest=lambda db: digest_function(db, today=args.public_today),
        flags=flags,
        work_dir=Path(args.work_dir) if args.work_dir else None,
    )
    report["entrypoint"] = {
        "name": "run_review_inbox_youtube_active_scheduled.py",
        "confirm": "matched",
        "public_today": args.public_today,
        "cron_window_checked": True,
        "legacy_writer_retained": True,
        "reader_mode": "legacy",
        "source_queue": "youtube_active_video_review",
    }
    write_report(report_path, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--snapshot-out", type=Path, required=True)
    parser.add_argument("--report-out", type=Path, required=True)
    parser.add_argument("--observation-id", required=True)
    parser.add_argument("--public-today", required=True, help="fixed JST date, YYYY-MM-DD")
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
        "scheduled YouTube active review inbox dual-write complete: "
        f"published={report['published']} no_op={report['no_op']} "
        f"Rend={report['rend']['checksum']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
