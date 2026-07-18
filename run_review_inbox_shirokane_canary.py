#!/usr/bin/env python3
"""Explicitly gated entrypoint for the Shirokane review inbox canary.

B1-3a adds this wiring but does not execute it.  A production run requires a
separate B1-3b approval, four explicit environment gates, --execute, and the
exact confirmation phrase.  The daily cron window is always rejected.
"""

from __future__ import annotations

import argparse
import json
import os
import string
import tempfile
from datetime import datetime, time
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from review_inbox_parity import load_adapted_snapshot
from review_inbox_production_wiring import (
    MasterDbS3ArtifactStore,
    public_projection_digest,
)
from review_inbox_registered_event_investigation_adapter import (
    DEFAULT_INPUT,
    SHIROKANE_CANARY_SOURCE_KEY,
    build_snapshot,
)
from review_inbox_source_adapter import write_adapted_snapshot
from review_inbox_source_writer import (
    ArtifactStore,
    SourceWriterError,
    SourceWriterFlags,
    run_source_shadow,
)


CONFIRM = "RUN SHIROKANE CANARY DUAL WRITE"
CRON_WINDOW_START = time(17, 20)
CRON_WINDOW_END = time(18, 0)
JST = ZoneInfo("Asia/Tokyo")
EXPLICIT_ENV = {
    "REVIEW_INBOX_DUAL_WRITE_MODE": "canary",
    "REVIEW_INBOX_CAS_PUBLISH_ENABLED": "true",
    "REVIEW_INBOX_READER_MODE": "legacy",
    "REVIEW_INBOX_LEGACY_WRITER_ENABLED": "true",
}


def require_explicit_environment(environ: Mapping[str, str]) -> SourceWriterFlags:
    missing = [name for name in EXPLICIT_ENV if name not in environ]
    if missing:
        raise SourceWriterError(
            "canary requires explicit environment gates: " + ", ".join(missing)
        )
    cas_enabled = environ["REVIEW_INBOX_CAS_PUBLISH_ENABLED"].strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    legacy_writer_enabled = environ[
        "REVIEW_INBOX_LEGACY_WRITER_ENABLED"
    ].strip().lower() in {"1", "true", "yes", "on"}
    flags = SourceWriterFlags(
        dual_write_mode=environ["REVIEW_INBOX_DUAL_WRITE_MODE"].strip(),
        cas_publish_enabled=cas_enabled,
        reader_mode=environ["REVIEW_INBOX_READER_MODE"].strip(),
        legacy_writer_enabled=legacy_writer_enabled,
    )
    flags.require_shadow_run("canary")
    if environ["REVIEW_INBOX_READER_MODE"].strip() != "legacy":
        raise SourceWriterError("canary reader must be explicitly set to legacy")
    if not legacy_writer_enabled:
        raise SourceWriterError("legacy writer must be explicitly enabled")
    return flags


def require_outside_cron_window(now: datetime | None = None) -> None:
    current = now or datetime.now(JST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=JST)
    current_time = current.astimezone(JST).time().replace(tzinfo=None)
    if CRON_WINDOW_START <= current_time < CRON_WINDOW_END:
        raise SourceWriterError("canary execution is forbidden during 17:20-18:00 JST")


def write_report(path: Path, report: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temp_path = Path(handle.name)
    os.replace(temp_path, path)


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
    expected_rstart = str(args.expect_rstart_checksum or "").strip().lower()
    if len(expected_rstart) != 64 or any(
        char not in string.hexdigits for char in expected_rstart
    ):
        raise SourceWriterError("--expect-rstart-checksum must be a 64-character SHA-256")
    try:
        datetime.strptime(str(args.public_today), "%Y-%m-%d")
    except ValueError as exc:
        raise SourceWriterError("--public-today must be YYYY-MM-DD") from exc
    input_path = Path(args.input).resolve()
    snapshot_path = Path(args.snapshot_out).resolve()
    report_path = Path(args.report_out).resolve()
    if snapshot_path == report_path or input_path in {snapshot_path, report_path}:
        raise SourceWriterError("input, snapshot, and report paths must be distinct")
    for output_path in (snapshot_path, report_path):
        if output_path.exists():
            raise SourceWriterError(f"refusing to overwrite canary evidence: {output_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)

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
