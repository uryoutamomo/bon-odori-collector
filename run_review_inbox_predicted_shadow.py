#!/usr/bin/env python3
"""Explicitly gated entrypoint for one predicted-occurrence shadow source.

B1-6a adds two independent source adapters behind this entrypoint but does not
execute either against production. Each source requires its own frozen input,
evidence paths, Rstart expectation, confirmation phrase, and CAS publication.
"""

from __future__ import annotations

import argparse
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from review_inbox_adapters.parity import load_adapted_snapshot
from review_inbox_adapters.predicted_occurrence_date_review_adapter import (
    DEFAULT_INPUT as DATE_REVIEW_INPUT,
    build_snapshot as build_date_review_snapshot,
)
from review_inbox_adapters.predicted_occurrence_research_adapter import (
    DEFAULT_INPUT as RESEARCH_INPUT,
    build_snapshot as build_research_snapshot,
)
from review_inbox_adapters.production_wiring import (
    MasterDbS3ArtifactStore,
    public_projection_digest,
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
from review_inbox_adapters.source_writer import ArtifactStore, SourceWriterError, run_source_shadow


SOURCE_CONFIGS = {
    "research": {
        "source_id": "predicted_occurrence_research",
        "build_snapshot": build_research_snapshot,
        "input": RESEARCH_INPUT,
        "confirm": "RUN PREDICTED OCCURRENCE RESEARCH SHADOW",
        "run_label": "predicted occurrence research shadow",
    },
    "date-review": {
        "source_id": "predicted_occurrence_date_review",
        "build_snapshot": build_date_review_snapshot,
        "input": DATE_REVIEW_INPUT,
        "confirm": "RUN PREDICTED OCCURRENCE DATE REVIEW SHADOW",
        "run_label": "predicted occurrence date review shadow",
    },
}


def run_predicted_shadow(
    args: argparse.Namespace,
    *,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
    store_factory: Callable[[argparse.Namespace], ArtifactStore] | None = None,
    digest_function: Callable[..., str] = public_projection_digest,
) -> dict[str, Any]:
    config = SOURCE_CONFIGS[args.source]
    run_label = str(config["run_label"])
    environ = os.environ if environ is None else environ
    if not args.execute:
        raise SourceWriterError(
            f"{run_label} execution is off; pass --execute only after B1-6a review"
        )
    if args.confirm != config["confirm"]:
        raise SourceWriterError(f"--confirm must be exactly: {config['confirm']}")
    flags = require_explicit_environment(
        environ,
        dual_write_mode="bulk",
        selection_mode="all",
        run_label=run_label,
    )
    require_outside_cron_window(now, run_label=run_label)

    if not str(args.observation_id).strip():
        raise SourceWriterError("--observation-id is required")
    expected_rstart = validate_expected_rstart(args.expect_rstart_checksum)
    validate_public_today(args.public_today)
    selected_input = args.input or config["input"]
    input_path, snapshot_path, report_path = prepare_evidence_paths(
        input_path=selected_input,
        snapshot_path=args.snapshot_out,
        report_path=args.report_out,
        run_label=run_label,
    )

    snapshot = config["build_snapshot"](input_path)
    if snapshot.get("source_id") != config["source_id"]:
        raise SourceWriterError(f"{run_label} selected the wrong source adapter")
    if not snapshot.get("items"):
        raise SourceWriterError(f"{run_label} input must contain at least one item")
    source_keys = [str(item["source_key"]) for item in snapshot["items"]]
    if len(source_keys) != len(set(source_keys)):
        raise SourceWriterError(f"{run_label} contains duplicate source keys")
    scope_counts = dict(
        sorted(Counter(item["time_scope"] for item in snapshot["items"]).items())
    )
    kind_counts = dict(sorted(Counter(item["kind"] for item in snapshot["items"]).items()))
    action_counts = dict(
        sorted(Counter(item["recommended_action"] for item in snapshot["items"]).items())
    )
    snapshot["selection"] = {"mode": "all", "source_keys": source_keys}
    snapshot["write_mode"] = "predicted_source_shadow_explicit_gate"
    snapshot["execution_entrypoint"] = "run_review_inbox_predicted_shadow.py"
    snapshot["scope_counts"] = scope_counts
    snapshot["kind_counts"] = kind_counts
    snapshot["action_counts"] = action_counts
    snapshot["safety_boundary"] = (
        "prediction review only; no current-year confirmation or domain apply"
    )
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
        public_projection_digest=lambda db: digest_function(
            db, target_year=args.public_target_year, today=args.public_today
        ),
        flags=flags,
        work_dir=Path(args.work_dir) if args.work_dir else None,
        expected_rstart_checksum=expected_rstart,
    )
    report["entrypoint"] = {
        "name": "run_review_inbox_predicted_shadow.py",
        "source": args.source,
        "source_id": config["source_id"],
        "confirm": "matched",
        "public_today": args.public_today,
        "item_count": frozen_snapshot["item_count"],
        "scope_counts": scope_counts,
        "kind_counts": kind_counts,
        "action_counts": action_counts,
        "prediction_confirmation_boundary_checked": True,
        "cron_window_checked": True,
        "b1_6_execution_gate_acknowledged": True,
    }
    write_report(report_path, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=sorted(SOURCE_CONFIGS), required=True)
    parser.add_argument("--input", type=Path)
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
    report = run_predicted_shadow(args)
    print(
        f"Predicted review inbox shadow complete: source={args.source} "
        f"items={report['entrypoint']['item_count']} "
        f"published={report['published']} no_op={report['no_op']} "
        f"Rend={report['rend']['checksum']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
