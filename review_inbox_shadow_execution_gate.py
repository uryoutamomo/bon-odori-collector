#!/usr/bin/env python3
"""Shared fail-closed gates for manually approved review inbox shadow runs."""

from __future__ import annotations

import json
import os
import string
import tempfile
from datetime import datetime, time
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from review_inbox_source_writer import SourceWriterError, SourceWriterFlags


CRON_WINDOW_START = time(17, 20)
CRON_WINDOW_END = time(18, 0)
JST = ZoneInfo("Asia/Tokyo")
ENVIRONMENT_GATE_NAMES = (
    "REVIEW_INBOX_DUAL_WRITE_MODE",
    "REVIEW_INBOX_CAS_PUBLISH_ENABLED",
    "REVIEW_INBOX_READER_MODE",
    "REVIEW_INBOX_LEGACY_WRITER_ENABLED",
)
TRUE_VALUES = {"1", "true", "yes", "on"}


def require_explicit_environment(
    environ: Mapping[str, str],
    *,
    dual_write_mode: str,
    selection_mode: str,
    run_label: str,
) -> SourceWriterFlags:
    missing = [name for name in ENVIRONMENT_GATE_NAMES if name not in environ]
    if missing:
        raise SourceWriterError(
            f"{run_label} requires explicit environment gates: " + ", ".join(missing)
        )
    cas_enabled = (
        environ["REVIEW_INBOX_CAS_PUBLISH_ENABLED"].strip().lower() in TRUE_VALUES
    )
    legacy_writer_enabled = (
        environ["REVIEW_INBOX_LEGACY_WRITER_ENABLED"].strip().lower() in TRUE_VALUES
    )
    flags = SourceWriterFlags(
        dual_write_mode=environ["REVIEW_INBOX_DUAL_WRITE_MODE"].strip(),
        cas_publish_enabled=cas_enabled,
        reader_mode=environ["REVIEW_INBOX_READER_MODE"].strip(),
        legacy_writer_enabled=legacy_writer_enabled,
    )
    if flags.dual_write_mode != dual_write_mode:
        raise SourceWriterError(
            f"{run_label} dual-write mode must be explicitly set to {dual_write_mode}"
        )
    flags.require_shadow_run(selection_mode)
    if flags.reader_mode != "legacy":
        raise SourceWriterError(f"{run_label} reader must be explicitly set to legacy")
    if not legacy_writer_enabled:
        raise SourceWriterError("legacy writer must be explicitly enabled")
    return flags


def require_outside_cron_window(
    now: datetime | None = None,
    *,
    run_label: str,
) -> None:
    current = now or datetime.now(JST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=JST)
    current_time = current.astimezone(JST).time().replace(tzinfo=None)
    if CRON_WINDOW_START <= current_time < CRON_WINDOW_END:
        raise SourceWriterError(
            f"{run_label} execution is forbidden during 17:20-18:00 JST"
        )


def validate_expected_rstart(value: Any) -> str:
    expected = str(value or "").strip().lower()
    if len(expected) != 64 or any(char not in string.hexdigits for char in expected):
        raise SourceWriterError("--expect-rstart-checksum must be a 64-character SHA-256")
    return expected


def validate_public_today(value: Any) -> str:
    public_today = str(value)
    try:
        datetime.strptime(public_today, "%Y-%m-%d")
    except ValueError as exc:
        raise SourceWriterError("--public-today must be YYYY-MM-DD") from exc
    return public_today


def prepare_evidence_paths(
    *,
    input_path: Path,
    snapshot_path: Path,
    report_path: Path,
    run_label: str,
) -> tuple[Path, Path, Path]:
    input_path = Path(input_path).resolve()
    snapshot_path = Path(snapshot_path).resolve()
    report_path = Path(report_path).resolve()
    if snapshot_path == report_path or input_path in {snapshot_path, report_path}:
        raise SourceWriterError("input, snapshot, and report paths must be distinct")
    for output_path in (snapshot_path, report_path):
        if output_path.exists():
            raise SourceWriterError(
                f"refusing to overwrite {run_label} evidence: {output_path}"
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
    return input_path, snapshot_path, report_path


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
