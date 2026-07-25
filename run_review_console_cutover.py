#!/usr/bin/env python3
"""Fail-closed B1 review-console reader cutover executor.

The executor never writes the Master DB, inbox export, legacy inputs, adapter
snapshots, parity inputs, decisions, stages, or public data.  It validates a
separately fetched S3 artifact and an explicitly prepared console root before
starting the local console in canary or inbox mode.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from master_rdb.master_db import file_sha256
from review_console import data
from review_console.server import serve
from review_inbox import inbox_rows
from review_inbox_adapters.parity import build_parity_report, load_adapted_snapshot
from review_inbox_adapters.production_wiring import public_projection_digest
from review_inbox_adapters.shadow_execution_gate import (
    require_explicit_environment,
    require_outside_cron_window,
    validate_expected_rstart,
    validate_public_today,
    write_report,
)
from review_inbox_adapters.source_adapter import input_sha256
from review_inbox_adapters.source_writer import SourceWriterError


RUN_LABEL = "B1 review console reader cutover"
CONFIRM_BY_MODE = {
    "canary": "ACTIVATE B1 REVIEW CONSOLE CANARY READER",
    "inbox": "ACTIVATE B1 REVIEW CONSOLE INBOX READER",
}
EXPECTED_INBOX_COUNTS = {
    "official_source": 52,
    "registered_event_investigation": 79,
    "predicted_occurrence_research": 8,
    "predicted_occurrence_date_review": 12,
    "missing_source_url": 0,
    "missing_venue": 3,
    "historical_reference": 16,
}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SourceWriterError(f"invalid JSON input: {path}") from exc


def _canonical_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _require_new_evidence_path(path: Path) -> Path:
    result = Path(path).resolve()
    if result.exists():
        raise SourceWriterError(f"refusing to overwrite {RUN_LABEL} evidence: {result}")
    result.parent.mkdir(parents=True, exist_ok=True)
    return result


def _artifact_lineage(database: Path, manifest_path: Path, expected_rstart: str, expected_snapshot: str) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    manifest_checksum = str(manifest.get("database_checksum") or "").lower()
    artifact = manifest.get("artifact") or {}
    snapshot_id = str(artifact.get("snapshot_id") or "")
    actual_checksum = file_sha256(database)
    if actual_checksum != expected_rstart or manifest_checksum != expected_rstart:
        raise SourceWriterError(
            "S3 fetch lineage checksum mismatch: "
            f"database={actual_checksum or '(missing)'} manifest={manifest_checksum or '(missing)'} "
            f"expected={expected_rstart}"
        )
    if not expected_snapshot or snapshot_id != expected_snapshot:
        raise SourceWriterError(
            f"S3 fetch lineage snapshot mismatch: manifest={snapshot_id or '(missing)'} "
            f"expected={expected_snapshot or '(missing)'}"
        )
    return {"database_sha256": actual_checksum, "snapshot_id": snapshot_id}


def _database_audit(database: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        conn = sqlite3.connect(f"file:{Path(database).resolve()}?mode=ro", uri=True)
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
        rows = inbox_rows(conn, status="pending", ensure_schema=False)
        decision_nonnull = conn.execute(
            "SELECT COUNT(*) FROM review_inbox_items WHERE "
            "decision IS NOT NULL OR decided_by IS NOT NULL OR decided_at IS NOT NULL "
            "OR closed_at IS NOT NULL OR decision_route IS NOT NULL"
        ).fetchone()[0]
    except sqlite3.Error as exc:
        raise SourceWriterError(f"Master DB audit failed: {exc}") from exc
    finally:
        if "conn" in locals():
            conn.close()
    if integrity != "ok" or foreign_keys:
        raise SourceWriterError(
            f"Master DB audit failed: integrity={integrity} foreign_key_violations={len(foreign_keys)}"
        )
    if decision_nonnull:
        raise SourceWriterError(f"review inbox contains {decision_nonnull} lifecycle decisions")
    counts = dict(sorted(Counter(str(row.get("source_id") or "") for row in rows).items()))
    if counts != {key: value for key, value in EXPECTED_INBOX_COUNTS.items() if value}:
        raise SourceWriterError(f"unexpected B1 review inbox source counts: {counts}")
    return rows, {
        "integrity": integrity,
        "foreign_key_violation_count": len(foreign_keys),
        "decision_nonnull_count": decision_nonnull,
        "pending_item_count": len(rows),
        "source_counts": {key: counts.get(key, 0) for key in EXPECTED_INBOX_COUNTS},
    }


def _prepared_inputs(
    root: Path,
    database_rows: list[dict[str, Any]],
    snapshot_paths: list[Path],
    *,
    reader_mode: str,
) -> dict[str, Any]:
    root = Path(root).resolve()
    inbox_path = root / "data/review_inbox.json"
    inbox_payload = _read_json(inbox_path)
    exported_rows = list(inbox_payload.get("items") or [])
    if _canonical_sha(exported_rows) != _canonical_sha(database_rows):
        raise SourceWriterError("prepared review_inbox.json does not match the operator-fixed S3 database")

    snapshots = [load_adapted_snapshot(path) for path in snapshot_paths]
    snapshot_by_source = {str(snapshot.get("source_id") or ""): snapshot for snapshot in snapshots}
    if len(snapshot_by_source) != len(snapshots) or set(snapshot_by_source) != set(EXPECTED_INBOX_COUNTS):
        raise SourceWriterError(
            "adapted snapshots must contain each B1 source exactly once: "
            + ", ".join(sorted(EXPECTED_INBOX_COUNTS))
        )

    source_by_id = {source.id: source for source in data.SOURCES}
    legacy_hashes: dict[str, str] = {}
    adapter_input_hashes: dict[str, str] = {}
    adapter_hashes: dict[str, str] = {}
    for legacy_source_id, inbox_source_id in data.B1_LEGACY_TO_INBOX_SOURCE_IDS.items():
        legacy_path = root / source_by_id[legacy_source_id].path
        if not legacy_path.is_file():
            raise SourceWriterError(f"prepared legacy input is missing: {legacy_path}")
        legacy_hashes[legacy_source_id] = input_sha256(legacy_path.read_bytes())

        snapshot = snapshot_by_source[inbox_source_id]
        adapter_input_path = Path(str(snapshot.get("input_path") or ""))
        expected_input_sha = str(snapshot.get("input_sha256") or "").lower()
        if not adapter_input_path.is_file():
            raise SourceWriterError(
                f"adapter input is missing for {inbox_source_id}: {adapter_input_path}"
            )
        actual_input_sha = input_sha256(adapter_input_path.read_bytes())
        if actual_input_sha != expected_input_sha:
            raise SourceWriterError(
                f"adapter input lineage mismatch for {inbox_source_id}: "
                f"actual={actual_input_sha} snapshot={expected_input_sha or '(missing)'}"
            )
        adapter_input_hashes[inbox_source_id] = actual_input_sha
        adapter_hashes[inbox_source_id] = file_sha256(
            Path(snapshot["adapter_snapshot_path"])
        )

    parity = build_parity_report(snapshots, {**inbox_payload, "items": database_rows})
    summary = parity["summary"]
    if (
        not summary["parity"]
        or summary["source_count"] != len(EXPECTED_INBOX_COUNTS)
        or summary["expected_count"] != sum(EXPECTED_INBOX_COUNTS.values())
        or summary["inbox_count"] != sum(EXPECTED_INBOX_COUNTS.values())
        or summary["missing_count"]
        or summary["extra_count"]
        or summary["content_mismatch_count"]
    ):
        raise SourceWriterError(f"B1 adapter parity failed: {summary}")

    preview = data.build_reader_mode_preview(
        root=root,
        decisions_path=root / "data/review_console/decisions.json",
    )
    required_check_names = [
        "default_mode_is_legacy",
        "canary_exact_replacement",
        "legacy_reader_excludes_inbox",
        "cutover_introduced_duplicate_item_ids_zero",
    ]
    if reader_mode == "inbox":
        required_check_names.extend(
            (
                "full_legacy_b1_removed",
                "full_b1_exact_replacement",
                "inbox_reader_excludes_legacy",
                "inbox_reader_is_single_source",
                "inbox_reader_includes_complete_export",
            )
        )
    reader_mode_checks = {
        name: bool(preview["checks"].get(name)) for name in required_check_names
    }
    if not all(reader_mode_checks.values()):
        raise SourceWriterError(
            f"B1 {reader_mode} reader preview failed: {reader_mode_checks}"
        )
    return {
        "review_inbox_export": {
            "path": str(inbox_path),
            "sha256": file_sha256(inbox_path),
            "items_sha256": _canonical_sha(exported_rows),
            "item_count": len(exported_rows),
        },
        "legacy_input_sha256": legacy_hashes,
        "adapter_input_sha256": adapter_input_hashes,
        "adapter_snapshot_sha256": adapter_hashes,
        "parity": parity,
        "parity_sha256": _canonical_sha(parity),
        "reader_preview": preview,
        "reader_mode_gate": {
            "mode": reader_mode,
            "required_checks": reader_mode_checks,
            "ok": all(reader_mode_checks.values()),
            "full_readiness": bool(preview["ok"]),
        },
    }


def run_cutover(
    args: argparse.Namespace,
    *,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
    digest_function: Callable[..., str] = public_projection_digest,
    activate: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    environ = os.environ if environ is None else environ
    mode = str(args.reader_mode or "")
    if mode not in CONFIRM_BY_MODE:
        raise SourceWriterError("--reader-mode must be canary or inbox")
    if not args.execute:
        raise SourceWriterError(f"{RUN_LABEL} is off; pass --execute only after explicit execution GO")
    if args.confirm != CONFIRM_BY_MODE[mode]:
        raise SourceWriterError(f"--confirm must be exactly: {CONFIRM_BY_MODE[mode]}")
    require_explicit_environment(
        environ,
        dual_write_mode="bulk",
        selection_mode="all",
        run_label=RUN_LABEL,
    )
    console_mode = str(environ.get(data.REVIEW_CONSOLE_READER_MODE_ENV, ""))
    if console_mode != mode:
        raise SourceWriterError(
            f"{data.REVIEW_CONSOLE_READER_MODE_ENV} must be explicitly set to {mode}"
        )
    require_outside_cron_window(now, run_label=RUN_LABEL)
    expected_rstart = validate_expected_rstart(args.expect_rstart_checksum)
    validate_public_today(args.public_today)
    public_today = str(args.public_today)
    evidence_path = _require_new_evidence_path(args.evidence_out)

    database = Path(args.master_db).resolve()
    artifact = _artifact_lineage(
        database,
        Path(args.artifact_manifest).resolve(),
        expected_rstart,
        str(args.expect_snapshot_id or ""),
    )
    database_rows, database_audit = _database_audit(database)
    prepared = _prepared_inputs(
        Path(args.input_root),
        database_rows,
        [Path(path) for path in args.adapted_snapshot],
        reader_mode=mode,
    )
    public_sha = digest_function(
        database, target_year=args.public_target_year, today=public_today
    )
    expected_public_sha = validate_expected_rstart(args.expect_public_sha256)
    if public_sha != expected_public_sha:
        raise SourceWriterError(
            f"public projection changed: actual={public_sha} expected={expected_public_sha}"
        )

    report = {
        "schema_version": 1,
        "generated_by": "run_review_console_cutover.py",
        "read_only": True,
        "reader_mode": mode,
        "confirm": "matched",
        "artifact": artifact,
        "database_audit": database_audit,
        "prepared_inputs": prepared,
        "public_projection_sha256": public_sha,
        "activation": {
            "scope": "local review console process only",
            "environment": {data.REVIEW_CONSOLE_READER_MODE_ENV: mode},
            "master_db_write": False,
            "decision_write": False,
            "stage_write": False,
            "public_write": False,
            "workflow_change": False,
            "rollback": f"restart with {data.REVIEW_CONSOLE_READER_MODE_ENV}=legacy",
        },
    }
    write_report(evidence_path, report)
    if activate is not None:
        activate(mode)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=data.ROOT)
    parser.add_argument("--master-db", type=Path, required=True)
    parser.add_argument("--artifact-manifest", type=Path, required=True)
    parser.add_argument("--adapted-snapshot", type=Path, action="append", required=True)
    parser.add_argument("--expect-rstart-checksum", required=True)
    parser.add_argument("--expect-snapshot-id", required=True)
    parser.add_argument("--expect-public-sha256", required=True)
    parser.add_argument("--public-target-year", type=int, required=True)
    parser.add_argument("--public-today", required=True)
    parser.add_argument("--reader-mode", choices=tuple(CONFIRM_BY_MODE), required=True)
    parser.add_argument("--evidence-out", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8751)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if Path(args.input_root).resolve() != data.ROOT.resolve():
        raise SourceWriterError("interactive activation requires --input-root to be this checkout")
    run_cutover(
        args,
        activate=lambda mode: serve(args.host, args.port),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
