#!/usr/bin/env python3
"""Default-off B2-3c runner for one rare-signal inbox decision."""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from review_inbox_decision_writer import (
    DecisionWriterFlags,
    load_decision_payload,
    run_decision_write,
    validate_decision_payload,
)
from review_inbox_production_wiring import MasterDbS3ArtifactStore, public_projection_digest
from review_inbox_shadow_execution_gate import (
    require_outside_cron_window,
    validate_expected_rstart,
    validate_public_today,
    write_report,
)
from review_inbox_source_writer import ArtifactStore, SourceWriterError


CONFIRM = "WRITE RARE SIGNAL CANARY DECISION"
ENVIRONMENT_GATE_NAMES = (
    "REVIEW_INBOX_DECISION_WRITE_MODE",
    "REVIEW_INBOX_CAS_PUBLISH_ENABLED",
    "REVIEW_INBOX_READER_MODE",
    "REVIEW_INBOX_LEGACY_WRITER_ENABLED",
)


def require_explicit_environment(environ: Mapping[str, str]) -> DecisionWriterFlags:
    missing = [name for name in ENVIRONMENT_GATE_NAMES if name not in environ]
    if missing:
        raise SourceWriterError(
            "rare signal decision canary requires explicit environment gates: "
            + ", ".join(missing)
        )
    flags = DecisionWriterFlags.from_env(environ)
    if flags.decision_write_mode != "canary":
        raise SourceWriterError("rare signal decision write mode must be explicitly set to canary")
    flags.require_write(1)
    return flags


def _freeze_stage(input_path: Path, output_path: Path) -> None:
    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()
    if input_path == output_path:
        raise SourceWriterError("staged decision input and frozen evidence path must differ")
    if output_path.exists():
        raise SourceWriterError(f"refusing to overwrite decision evidence: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(input_path.read_bytes())


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
            "rare signal decision execution is off; pass --execute only after B2-3c GO"
        )
    if args.confirm != CONFIRM:
        raise SourceWriterError(f"--confirm must be exactly: {CONFIRM}")
    flags = require_explicit_environment(environ)
    require_outside_cron_window(now, run_label="rare signal decision canary")
    expected_rstart = validate_expected_rstart(args.expect_rstart_checksum)
    validate_public_today(args.public_today)

    staged_path = Path(args.staged_decisions).resolve()
    frozen_path = Path(args.frozen_stage_out).resolve()
    report_path = Path(args.report_out).resolve()
    if len({staged_path, frozen_path, report_path}) != 3:
        raise SourceWriterError("staged input, frozen evidence, and report paths must be distinct")
    if report_path.exists():
        raise SourceWriterError(f"refusing to overwrite decision evidence: {report_path}")
    payload, payload_sha = load_decision_payload(staged_path)
    updates = validate_decision_payload(payload)
    if len(updates) != 1 or updates[0]["inbox_id"] != args.inbox_id:
        raise SourceWriterError("rare signal decision canary must select exactly the approved inbox_id")
    if not str(args.source_key).strip():
        raise SourceWriterError("--source-key is required")
    _freeze_stage(staged_path, frozen_path)

    factory = store_factory or (
        lambda value: MasterDbS3ArtifactStore(bucket=value.bucket, prefix=value.prefix)
    )
    report = run_decision_write(
        store=factory(args),
        staged_payload=payload,
        staged_payload_sha256=payload_sha,
        expected_targets={
            args.inbox_id: {"source_id": "rare_signal", "source_key": args.source_key}
        },
        public_projection_digest=lambda db: digest_function(db, today=args.public_today),
        expected_rstart_checksum=expected_rstart,
        flags=flags,
        work_dir=Path(args.work_dir) if args.work_dir else None,
    )
    report["entrypoint"] = {
        "name": "run_review_inbox_rare_signal_decision_canary.py",
        "confirm": "matched",
        "public_today": args.public_today,
        "cron_window_checked": True,
        "b2_3c_execution_gate_acknowledged": True,
        "inbox_id": args.inbox_id,
        "source_key": args.source_key,
        "frozen_stage_path": str(frozen_path),
    }
    write_report(report_path, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged-decisions", type=Path, required=True)
    parser.add_argument("--frozen-stage-out", type=Path, required=True)
    parser.add_argument("--report-out", type=Path, required=True)
    parser.add_argument("--inbox-id", required=True)
    parser.add_argument("--source-key", required=True)
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
        "rare signal decision canary complete: "
        f"published={report['published']} no_op={report['no_op']} Rend={report['rend']['checksum']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
