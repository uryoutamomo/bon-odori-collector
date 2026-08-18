#!/usr/bin/env python3
"""CAS-publish the daily five-item X backlog cohort to Review Inbox.

The workflow must opt in through both its repository-variable guard and the
explicit environment gates below.  The backlog moves to ``in_progress`` only
after the Review Inbox run has completed successfully; a failed CAS or audit
therefore leaves every candidate eligible for the next run.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from review_inbox_adapters.parity import load_adapted_snapshot
from review_inbox_adapters.production_wiring import (
    MasterDbS3ArtifactStore,
    public_projection_digest,
)
from review_inbox_adapters.shadow_execution_gate import (
    prepare_evidence_paths,
    require_explicit_environment as common_gates,
    require_outside_cron_window,
    validate_public_today,
    write_report,
)
from review_inbox_adapters.source_adapter import write_adapted_snapshot
from review_inbox_adapters.source_writer import (
    ArtifactStore,
    SourceWriterError,
    run_source_shadow,
)
from x_candidate_backlog import load_json, mark_in_progress, write_backlog


CONFIRM = "RUN SCHEDULED X GAP COHORT DUAL WRITE"
ENABLE_ENV = "REVIEW_INBOX_X_GAP_SCHEDULED_ENABLED"
SOURCE_ID = "x_gap"
DAILY_MAX = 5


def require_explicit_environment(environ: Mapping[str, str]):
    if environ.get(ENABLE_ENV, "").strip().lower() != "true":
        raise SourceWriterError("scheduled X gap cohort dual-write is off")
    return common_gates(
        environ,
        dual_write_mode="cohort",
        selection_mode="cohort",
        run_label="scheduled X gap cohort dual-write",
    )


def _validated_snapshot(input_path: Path) -> dict:
    try:
        snapshot = load_adapted_snapshot(input_path)
    except (OSError, ValueError, TypeError) as exc:
        raise SourceWriterError(str(exc)) from exc
    selection = snapshot.get("selection") or {}
    if snapshot.get("source_id") != SOURCE_ID:
        raise SourceWriterError("scheduled X gap snapshot has the wrong source_id")
    if selection.get("mode") != "cohort" or selection.get("cohort") != "daily_canary":
        raise SourceWriterError("scheduled X gap snapshot must be the daily canary cohort")
    if selection.get("max_items") != DAILY_MAX:
        raise SourceWriterError("scheduled X gap cohort limit must remain five")
    if snapshot.get("item_count") != len(snapshot.get("items") or []):
        raise SourceWriterError("scheduled X gap snapshot item count is inconsistent")
    if not 0 <= int(snapshot.get("item_count") or 0) <= DAILY_MAX:
        raise SourceWriterError("scheduled X gap snapshot exceeds five items")
    source_keys = list(selection.get("source_keys") or [])
    item_keys = [item.get("source_key") for item in snapshot.get("items") or []]
    if source_keys != item_keys or len(item_keys) != len(set(item_keys)):
        raise SourceWriterError("scheduled X gap cohort source keys are inconsistent")
    if snapshot.get("upstream_boundary") != "durable_x_candidate_backlog_unprocessed_only":
        raise SourceWriterError("scheduled X gap snapshot bypassed the durable backlog")
    return snapshot


def run_scheduled(
    args: argparse.Namespace,
    *,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
    store_factory: Callable[[argparse.Namespace], ArtifactStore] | None = None,
    digest_function: Callable[..., str] = public_projection_digest,
) -> dict:
    environ = os.environ if environ is None else environ
    now = now or datetime.now(timezone.utc)
    if not args.execute:
        raise SourceWriterError("scheduled X gap cohort execution is off")
    if args.confirm != CONFIRM:
        raise SourceWriterError(f"--confirm must be exactly: {CONFIRM}")
    flags = require_explicit_environment(environ)
    require_outside_cron_window(
        now, run_label="scheduled X gap cohort dual-write", environ=environ
    )
    validate_public_today(args.public_today)
    observation_id = str(args.observation_id or "").strip()
    if not observation_id:
        raise SourceWriterError("--observation-id is required")

    input_path, snapshot_path, report_path = prepare_evidence_paths(
        input_path=args.input,
        snapshot_path=args.snapshot_out,
        report_path=args.report_out,
        run_label="scheduled X gap cohort dual-write",
    )
    backlog_path = Path(args.backlog).resolve()
    if backlog_path in {input_path, snapshot_path, report_path}:
        raise SourceWriterError("backlog and evidence paths must be distinct")
    snapshot = _validated_snapshot(input_path)
    snapshot["write_mode"] = "scheduled_cohort_dual_write_explicit_gate"
    snapshot["execution_entrypoint"] = "run_review_inbox_x_gap_scheduled.py"
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
    )
    report["entrypoint"] = {
        "name": "run_review_inbox_x_gap_scheduled.py",
        "confirm": "matched",
        "public_today": args.public_today,
        "cron_window_checked": True,
        "reader_mode": flags.reader_mode,
        "legacy_writer_retained": flags.legacy_writer_enabled,
        "cohort": "daily_canary",
        "daily_max": DAILY_MAX,
    }
    write_report(report_path, report)

    # This mutation is deliberately last.  Any store, audit, parity, or report
    # failure above leaves the source ledger untouched for a safe retry.
    backlog = load_json(backlog_path, None)
    updated = mark_in_progress(
        backlog,
        frozen_snapshot.get("items") or [],
        now=now,
        observation_id=observation_id,
    )
    write_backlog(backlog_path, updated)
    report["backlog_transition"] = {
        "status": "in_progress",
        "count": frozen_snapshot.get("item_count") or 0,
        "source_keys": list((frozen_snapshot.get("selection") or {}).get("source_keys") or []),
    }
    # Rewrite only our own fresh report with the completed local transition.
    write_report(report_path, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--backlog", type=Path, required=True)
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
        "scheduled X gap cohort review inbox dual-write complete: "
        f"items={report['backlog_transition']['count']} "
        f"published={report['published']} no_op={report['no_op']} "
        f"Rend={report['rend']['checksum']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
