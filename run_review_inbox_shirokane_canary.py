#!/usr/bin/env python3
"""Explicitly gated entrypoint for the Shirokane review inbox canary.

B1-3a adds this wiring but does not execute it.  A production run requires a
separate B1-3b approval, four explicit environment gates, --execute, and the
exact confirmation phrase.  The daily cron window is always rejected.
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
from review_inbox_adapters.registered_event_investigation_adapter import (
    DEFAULT_INPUT,
    SHIROKANE_CANARY_SOURCE_KEY,
    build_snapshot,
)
from review_inbox_adapters.source_adapter import write_adapted_snapshot
from review_inbox_adapters.shadow_execution_gate import (
    prepare_evidence_paths,
    require_explicit_environment as require_shadow_environment,
    require_outside_cron_window as require_shadow_outside_cron_window,
    validate_expected_rstart,
    validate_public_today,
    write_report,
)
from review_inbox_adapters.source_writer import (
    ArtifactStore,
    SourceWriterError,
    SourceWriterFlags,
    run_source_shadow,
)


CONFIRM = "RUN SHIROKANE CANARY DUAL WRITE"
EXPLICIT_ENV = {
    "REVIEW_INBOX_DUAL_WRITE_MODE": "canary",
    "REVIEW_INBOX_CAS_PUBLISH_ENABLED": "true",
    "REVIEW_INBOX_READER_MODE": "legacy",
    "REVIEW_INBOX_LEGACY_WRITER_ENABLED": "true",
}


def require_explicit_environment(environ: Mapping[str, str]) -> SourceWriterFlags:
    return require_shadow_environment(
        environ,
        dual_write_mode="canary",
        selection_mode="canary",
        run_label="canary",
    )


def require_outside_cron_window(now: datetime | None = None) -> None:
    require_shadow_outside_cron_window(now, run_label="canary")


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
        raise SourceWriterError("canary execution is off; pass --execute only after B1-3b GO")
    if args.confirm != CONFIRM:
        raise SourceWriterError(f"--confirm must be exactly: {CONFIRM}")
    flags = require_explicit_environment(environ)
    require_outside_cron_window(now)

    if not str(args.observation_id).strip():
        raise SourceWriterError("--observation-id is required")
    expected_rstart = validate_expected_rstart(args.expect_rstart_checksum)
    validate_public_today(args.public_today)
    input_path, snapshot_path, report_path = prepare_evidence_paths(
        input_path=args.input,
        snapshot_path=args.snapshot_out,
        report_path=args.report_out,
        run_label="canary",
    )

    snapshot = build_snapshot(input_path, canary=True)
    if snapshot.get("item_count") != 1:
        raise SourceWriterError("Shirokane canary must contain exactly one item")
    item = snapshot["items"][0]
    if item.get("source_key") != SHIROKANE_CANARY_SOURCE_KEY:
        raise SourceWriterError("Shirokane canary selected the wrong source key")
    snapshot["write_mode"] = "canary_dual_write_explicit_gate"
    snapshot["execution_entrypoint"] = "run_review_inbox_shirokane_canary.py"
    write_adapted_snapshot(snapshot, snapshot_path)
    frozen_snapshot = load_adapted_snapshot(snapshot_path)

    factory = store_factory or (
        lambda value: MasterDbS3ArtifactStore(bucket=value.bucket, prefix=value.prefix)
    )
    store = factory(args)
    report = run_source_shadow(
        store=store,
        adapted_snapshot=frozen_snapshot,
        observation_id=args.observation_id,
        public_projection_digest=lambda db: digest_function(db, today=args.public_today),
        flags=flags,
        work_dir=Path(args.work_dir) if args.work_dir else None,
        expected_rstart_checksum=expected_rstart,
    )
    report["entrypoint"] = {
        "name": "run_review_inbox_shirokane_canary.py",
        "confirm": "matched",
        "public_today": args.public_today,
        "cron_window_checked": True,
        "b1_3b_execution_gate_acknowledged": True,
    }
    write_report(report_path, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--snapshot-out", type=Path, required=True)
    parser.add_argument("--report-out", type=Path, required=True)
    parser.add_argument("--observation-id", required=True)
    parser.add_argument("--expect-rstart-checksum", required=True)
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
        "Shirokane review inbox canary complete: "
        f"published={report['published']} no_op={report['no_op']} "
        f"Rend={report['rend']['checksum']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
