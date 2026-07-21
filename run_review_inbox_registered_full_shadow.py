#!/usr/bin/env python3
"""Explicitly gated entrypoint for the registered-investigation full shadow.

B1-5a adds this wiring but does not execute it. A production run requires the
reviewed B1-5a merge, four explicit environment gates, --execute, and the exact
confirmation phrase. The daily cron window is always rejected.
"""

from __future__ import annotations

import argparse
import os
from collections import Counter
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
from review_inbox_adapters.shadow_execution_gate import (
    prepare_evidence_paths,
    require_explicit_environment,
    require_outside_cron_window,
    validate_expected_rstart,
    validate_public_today,
    write_report,
)
from review_inbox_adapters.source_adapter import write_adapted_snapshot
from review_inbox_adapters.source_writer import (
    ArtifactStore,
    SourceWriterError,
    run_source_shadow,
)


CONFIRM = "RUN REGISTERED INVESTIGATION FULL SHADOW"


def run_registered_full_shadow(
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
            "registered full shadow execution is off; pass --execute only after B1-5a review"
        )
    if args.confirm != CONFIRM:
        raise SourceWriterError(f"--confirm must be exactly: {CONFIRM}")
    flags = require_explicit_environment(
        environ,
        dual_write_mode="bulk",
        selection_mode="all",
        run_label="registered full shadow",
    )
    require_outside_cron_window(now, run_label="registered full shadow")

    if not str(args.observation_id).strip():
        raise SourceWriterError("--observation-id is required")
    expected_rstart = validate_expected_rstart(args.expect_rstart_checksum)
    validate_public_today(args.public_today)
    input_path, snapshot_path, report_path = prepare_evidence_paths(
        input_path=args.input,
        snapshot_path=args.snapshot_out,
        report_path=args.report_out,
        run_label="registered full shadow",
    )

    snapshot = build_snapshot(input_path, canary=False)
    if snapshot.get("source_id") != "registered_event_investigation":
        raise SourceWriterError("registered full shadow selected the wrong source adapter")
    if not snapshot.get("items"):
        raise SourceWriterError("registered full shadow input must contain at least one item")
    source_keys = [str(item["source_key"]) for item in snapshot["items"]]
    if len(source_keys) != len(set(source_keys)):
        raise SourceWriterError("registered full shadow contains duplicate source keys")
    if SHIROKANE_CANARY_SOURCE_KEY not in source_keys:
        raise SourceWriterError("registered full shadow must include the Shirokane canary key")
    scope_counts = dict(
        sorted(Counter(item["time_scope"] for item in snapshot["items"]).items())
    )
    kind_counts = dict(sorted(Counter(item["kind"] for item in snapshot["items"]).items()))
    snapshot["selection"] = {"mode": "all", "source_keys": source_keys}
    snapshot["write_mode"] = "registered_full_shadow_explicit_gate"
    snapshot["execution_entrypoint"] = "run_review_inbox_registered_full_shadow.py"
    snapshot["scope_counts"] = scope_counts
    snapshot["kind_counts"] = kind_counts
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
        "name": "run_review_inbox_registered_full_shadow.py",
        "confirm": "matched",
        "public_today": args.public_today,
        "item_count": frozen_snapshot["item_count"],
        "scope_counts": scope_counts,
        "kind_counts": kind_counts,
        "shirokane_canary_key_retained": True,
        "cron_window_checked": True,
        "b1_5_execution_gate_acknowledged": True,
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
    report = run_registered_full_shadow(args)
    print(
        "Registered-investigation review inbox full shadow complete: "
        f"items={report['entrypoint']['item_count']} "
        f"published={report['published']} no_op={report['no_op']} "
        f"Rend={report['rend']['checksum']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
