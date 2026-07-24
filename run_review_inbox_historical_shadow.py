#!/usr/bin/env python3
"""Explicitly gated B1-8 historical current-identity shadow entrypoint.

B1-8a adds review-only wiring and does not execute production. Historical
promotion recommendations are neutralized before they reach the inbox.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from review_inbox_adapters.historical_reference_adapter import (
    DEFAULT_INPUT,
    build_snapshot,
)
from review_inbox_adapters.parity import load_adapted_snapshot
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


CONFIRM = "RUN HISTORICAL REFERENCE SHADOW"
SOURCE_ID = "historical_reference"
RUN_LABEL = "historical current-identity shadow"
FORBIDDEN_EXACT_ACTIONS = {
    "confirm_current_year_date",
    "update_venue",
    "fill_source_url",
}
FORBIDDEN_ACTION_PREFIXES = ("promote_", "auto_promote_", "apply_")


def run_historical_shadow(
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
            f"{RUN_LABEL} execution is off; pass --execute only after B1-8a review"
        )
    if args.confirm != CONFIRM:
        raise SourceWriterError(f"--confirm must be exactly: {CONFIRM}")
    flags = require_explicit_environment(
        environ,
        dual_write_mode="bulk",
        selection_mode="all",
        run_label=RUN_LABEL,
    )
    require_outside_cron_window(now, run_label=RUN_LABEL)
    if not str(args.observation_id).strip():
        raise SourceWriterError("--observation-id is required")
    expected_rstart = validate_expected_rstart(args.expect_rstart_checksum)
    validate_public_today(args.public_today)
    input_path, snapshot_path, report_path = prepare_evidence_paths(
        input_path=args.input or DEFAULT_INPUT,
        snapshot_path=args.snapshot_out,
        report_path=args.report_out,
        run_label=RUN_LABEL,
    )

    source_payload = json.loads(input_path.read_text(encoding="utf-8"))
    source = source_payload.get("source") if isinstance(source_payload, dict) else None
    source_database_sha256 = str((source or {}).get("database_sha256") or "")
    if source_database_sha256 != expected_rstart:
        raise SourceWriterError(
            "historical input database checksum does not match operator-fixed Rstart: "
            f"input={source_database_sha256 or '(missing)'} expected={expected_rstart}"
        )
    identity_selection = source_payload.get("selection") or {}
    if identity_selection.get("mode") != "current_identity":
        raise SourceWriterError("historical input is not a current-identity snapshot")

    snapshot = build_snapshot(input_path)
    if snapshot.get("source_id") != SOURCE_ID:
        raise SourceWriterError("historical shadow selected the wrong source adapter")
    if not snapshot.get("items"):
        raise SourceWriterError("historical shadow input must contain at least one item")
    source_keys = [str(item["source_key"]) for item in snapshot["items"]]
    if len(source_keys) != len(set(source_keys)):
        raise SourceWriterError("historical shadow contains duplicate source keys")
    scope_counts = dict(sorted(Counter(item["time_scope"] for item in snapshot["items"]).items()))
    kind_counts = dict(sorted(Counter(item["kind"] for item in snapshot["items"]).items()))
    action_counts = dict(
        sorted(Counter(item["recommended_action"] for item in snapshot["items"]).items())
    )
    for action in action_counts:
        if action in FORBIDDEN_EXACT_ACTIONS or action.startswith(FORBIDDEN_ACTION_PREFIXES):
            raise SourceWriterError(f"historical shadow emitted forbidden action: {action}")

    snapshot["selection"] = {"mode": "all", "source_keys": source_keys}
    snapshot["identity_selection"] = identity_selection
    snapshot["write_mode"] = "historical_current_identity_shadow_explicit_gate"
    snapshot["execution_entrypoint"] = "run_review_inbox_historical_shadow.py"
    snapshot["scope_counts"] = scope_counts
    snapshot["kind_counts"] = kind_counts
    snapshot["action_counts"] = action_counts
    snapshot["safety_boundary"] = (
        "review only; no historical promotion, current-year confirmation, venue/source "
        "update, or domain apply"
    )
    write_adapted_snapshot(snapshot, snapshot_path)
    frozen_snapshot = load_adapted_snapshot(snapshot_path)

    factory = store_factory or (
        lambda value: MasterDbS3ArtifactStore(bucket=value.bucket, prefix=value.prefix)
    )
    report = run_source_shadow(
        store=factory(args),
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
        "name": "run_review_inbox_historical_shadow.py",
        "source_id": SOURCE_ID,
        "confirm": "matched",
        "public_today": args.public_today,
        "item_count": frozen_snapshot["item_count"],
        "scope_counts": scope_counts,
        "kind_counts": kind_counts,
        "action_counts": action_counts,
        "identity_selection": identity_selection,
        "source_database_sha256": source_database_sha256,
        "promotion_neutralization_checked": True,
        "direct_apply_boundary_checked": True,
        "cron_window_checked": True,
        "b1_8_execution_gate_acknowledged": True,
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
    report = run_historical_shadow(args)
    print(
        f"Historical review inbox shadow complete: items={report['entrypoint']['item_count']} "
        f"published={report['published']} no_op={report['no_op']} "
        f"Rend={report['rend']['checksum']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
