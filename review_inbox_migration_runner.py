#!/usr/bin/env python3
"""Safely migrate the review inbox schema without publishing the Master DB."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from master_db import MASTER_DB, file_sha256
from review_inbox import INBOX_SCHEMA_VERSION, V2_COLUMNS, migrate_inbox_schema_v2


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DEFAULT_OUT_DB = DATA / "review_inbox_v2_dry_run.sqlite"
DEFAULT_REPORT_JSON = DATA / "review_inbox_v2_migration_report.json"
DEFAULT_REPORT_MD = DATA / "review_inbox_v2_migration_report.md"
DEFAULT_BACKUP_DIR = DATA / "backups"
APPLY_CONFIRMATION = "APPLY REVIEW INBOX V2"
LIFECYCLE_COLUMNS = {
    "decision",
    "decided_by",
    "decided_at",
    "closed_at",
    "decision_route",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    before = report["before"]
    after = report["after"]
    lines = [
        "# Review inbox v2 migration report",
        "",
        f"- mode: `{report['mode']}`",
        f"- source_db: `{report['source_db']}`",
        f"- target_db: `{report['target_db']}`",
        f"- backup_db: `{report.get('backup_db') or ''}`",
        f"- expected_local_checksum: `{report['expected_local_checksum']}`",
        f"- before_checksum: `{report['before_checksum']}`",
        f"- after_checksum: `{report['after_checksum']}`",
        f"- schema_version: {before['schema_version']} -> {after['schema_version']}",
        f"- migration_changed: {report['migration_changed']}",
        f"- audit_passed: {report['audit_passed']}",
        "",
        "## Audit checks",
        "",
    ]
    for name, check in report["checks"].items():
        lines.append(f"- {name}: {'PASS' if check['passed'] else 'FAIL'} — {check['detail']}")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def connect(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    mode = "ro" if read_only else "rw"
    uri = f"file:{path.as_posix()}?mode={mode}"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    if not table_exists(conn, table):
        return []
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}


def rows_digest(conn: sqlite3.Connection, columns: list[str]) -> str:
    if not columns:
        return hashlib.sha256(b"[]").hexdigest()
    quoted = ", ".join(f'"{column}"' for column in columns)
    rows = [
        {column: row[column] for column in columns}
        for row in conn.execute(
            f"SELECT {quoted} FROM review_inbox_items ORDER BY inbox_id"
        )
    ]
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def db_snapshot(conn: sqlite3.Connection, legacy_columns: list[str] | None = None) -> dict[str, Any]:
    columns = table_columns(conn, "review_inbox_items")
    schema_version = INBOX_SCHEMA_VERSION if set(V2_COLUMNS).issubset(columns) else 1
    legacy_columns = legacy_columns if legacy_columns is not None else [
        column for column in columns if column not in V2_COLUMNS
    ]
    inbox_count = 0
    status_counts: dict[str, int] = {}
    missing_backfill = {"time_scope": 0, "source_payload_hash": 0, "last_seen_at": 0}
    lifecycle_nonnull = {column: 0 for column in sorted(LIFECYCLE_COLUMNS)}
    if columns:
        inbox_count = conn.execute("SELECT COUNT(*) FROM review_inbox_items").fetchone()[0]
        status_counts = dict(
            Counter(
                row[0]
                for row in conn.execute("SELECT status FROM review_inbox_items")
            )
        )
        for column in missing_backfill:
            if column in columns:
                missing_backfill[column] = conn.execute(
                    f"SELECT COUNT(*) FROM review_inbox_items "
                    f"WHERE {column} IS NULL OR {column} = ''"
                ).fetchone()[0]
        for column in lifecycle_nonnull:
            if column in columns:
                lifecycle_nonnull[column] = conn.execute(
                    f"SELECT COUNT(*) FROM review_inbox_items WHERE {column} IS NOT NULL"
                ).fetchone()[0]
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_key_violations = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    migration_record_count = 0
    if table_exists(conn, "schema_migrations"):
        migration_record_count = conn.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = ? AND name = ?",
            (INBOX_SCHEMA_VERSION, "review_inbox_v2"),
        ).fetchone()[0]
    return {
        "schema_version": schema_version,
        "columns": columns,
        "table_counts": table_counts(conn),
        "inbox_count": inbox_count,
        "status_counts": status_counts,
        "legacy_rows_sha256": rows_digest(conn, legacy_columns),
        "missing_backfill": missing_backfill,
        "lifecycle_nonnull": lifecycle_nonnull,
        "integrity_check": integrity,
        "foreign_key_violations": foreign_key_violations,
        "migration_record_count": migration_record_count,
    }


def audit_migration(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    before_counts = before["table_counts"]
    after_counts = after["table_counts"]
    domain_tables = sorted((set(before_counts) | set(after_counts)) - {"schema_migrations"})
    domain_count_diffs = {
        table: [before_counts.get(table, 0), after_counts.get(table, 0)]
        for table in domain_tables
        if before_counts.get(table, 0) != after_counts.get(table, 0)
    }
    schema_migration_delta = after_counts.get("schema_migrations", 0) - before_counts.get(
        "schema_migrations", 0
    )
    expected_schema_delta = 0 if before["migration_record_count"] else 1
    before_was_v1 = before["schema_version"] == 1
    decision_nonnull = sum(after["lifecycle_nonnull"].values())
    checks = {
        "schema_v2": {
            "passed": after["schema_version"] == INBOX_SCHEMA_VERSION,
            "detail": f"after={after['schema_version']}",
        },
        "integrity_check": {
            "passed": after["integrity_check"] == "ok",
            "detail": after["integrity_check"],
        },
        "foreign_key_check": {
            "passed": after["foreign_key_violations"] == 0,
            "detail": f"violations={after['foreign_key_violations']}",
        },
        "domain_table_counts_unchanged": {
            "passed": not domain_count_diffs,
            "detail": json.dumps(domain_count_diffs, ensure_ascii=False, sort_keys=True),
        },
        "schema_migration_record": {
            "passed": schema_migration_delta == expected_schema_delta
            and after["migration_record_count"] == 1,
            "detail": f"delta={schema_migration_delta} expected={expected_schema_delta}",
        },
        "legacy_rows_unchanged": {
            "passed": before["legacy_rows_sha256"] == after["legacy_rows_sha256"],
            "detail": (
                f"before={before['legacy_rows_sha256']} after={after['legacy_rows_sha256']}"
            ),
        },
        "status_distribution_unchanged": {
            "passed": before["status_counts"] == after["status_counts"],
            "detail": f"before={before['status_counts']} after={after['status_counts']}",
        },
        "observation_backfill_complete": {
            "passed": all(value == 0 for value in after["missing_backfill"].values()),
            "detail": json.dumps(after["missing_backfill"], sort_keys=True),
        },
        "no_decision_auto_promotion": {
            "passed": not before_was_v1 or decision_nonnull == 0,
            "detail": f"before_was_v1={before_was_v1} nonnull={decision_nonnull}",
        },
    }
    return checks


def guard_fetch(master_db: Path, expected_remote_checksum: str) -> dict[str, Any]:
    actual = file_sha256(master_db)
    if not actual:
        raise SystemExit(f"local Master DB is missing: {master_db}")
    if actual != expected_remote_checksum:
        raise SystemExit(
            "refusing fetch --overwrite because local checksum differs from remote: "
            f"local={actual} remote={expected_remote_checksum}"
        )
    result = {
        "guard": "fetch_overwrite",
        "master_db": str(master_db),
        "local_checksum": actual,
        "expected_remote_checksum": expected_remote_checksum,
        "safe_to_fetch_overwrite": True,
    }
    print(f"fetch overwrite guard passed: checksum={actual}")
    return result


def make_backup(source: Path, backup_dir: Path, timestamp: str) -> Path:
    stamp = timestamp.replace("-", "").replace(":", "").replace("+00:00", "Z")
    destination = Path(backup_dir) / f"{source.stem}.pre-review-inbox-v2.{stamp}{source.suffix}.bak"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def run_migration(
    *,
    master_db: Path,
    expected_local_checksum: str,
    apply: bool,
    out_db: Path,
    backup_dir: Path,
    report_json: Path,
    report_md: Path,
) -> dict[str, Any]:
    master_db = Path(master_db)
    actual_checksum = file_sha256(master_db)
    if not actual_checksum:
        raise SystemExit(f"local Master DB is missing: {master_db}")
    if actual_checksum != expected_local_checksum:
        raise SystemExit(
            "local checksum changed: "
            f"expected={expected_local_checksum} actual={actual_checksum}"
        )
    target_db = master_db if apply else Path(out_db)
    if not apply:
        if target_db.resolve() == master_db.resolve():
            raise SystemExit("dry-run --out-db must differ from --master-db")
        target_db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(master_db, target_db)
    timestamp = now_iso()
    backup = make_backup(master_db, backup_dir, timestamp) if apply else None

    with closing(connect(target_db)) as conn:
        before_columns = table_columns(conn, "review_inbox_items")
        legacy_columns = [column for column in before_columns if column not in V2_COLUMNS]
        before = db_snapshot(conn, legacy_columns)
        try:
            conn.execute("BEGIN IMMEDIATE")
            changed = migrate_inbox_schema_v2(conn)
            after_in_transaction = db_snapshot(conn, legacy_columns)
            checks = audit_migration(before, after_in_transaction)
            failed = [name for name, check in checks.items() if not check["passed"]]
            if failed:
                raise RuntimeError(f"migration audit failed: {', '.join(failed)}")
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    with closing(connect(target_db, read_only=True)) as conn:
        after = db_snapshot(conn, legacy_columns)
    checks = audit_migration(before, after)
    audit_passed = all(check["passed"] for check in checks.values())
    if not audit_passed:
        raise RuntimeError("post-commit migration audit failed")
    report = {
        "generated_by": "review_inbox_migration_runner.py",
        "generated_at": timestamp,
        "mode": "apply" if apply else "dry-run",
        "source_db": str(master_db),
        "target_db": str(target_db),
        "backup_db": str(backup) if backup else "",
        "expected_local_checksum": expected_local_checksum,
        "before_checksum": actual_checksum,
        "after_checksum": file_sha256(target_db),
        "migration_changed": changed,
        "audit_passed": audit_passed,
        "before": before,
        "after": after,
        "checks": checks,
        "scope": "local_database_only_no_s3_no_public_export_no_deploy",
    }
    write_json(report_json, report)
    write_markdown(report_md, report)
    print(
        f"review inbox v2 migration {report['mode']}: "
        f"audit_passed={audit_passed} checksum={report['after_checksum']} -> {target_db}"
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    guard = subparsers.add_parser("guard-fetch")
    guard.add_argument("--master-db", type=Path, default=MASTER_DB)
    guard.add_argument("--expect-remote-checksum", required=True)

    for command in ("dry-run", "apply"):
        migrate = subparsers.add_parser(command)
        migrate.add_argument("--master-db", type=Path, default=MASTER_DB)
        migrate.add_argument("--expect-local-checksum", required=True)
        migrate.add_argument("--out-db", type=Path, default=DEFAULT_OUT_DB)
        migrate.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
        migrate.add_argument("--report-json", type=Path, default=DEFAULT_REPORT_JSON)
        migrate.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD)
        if command == "apply":
            migrate.add_argument("--confirm", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "guard-fetch":
        guard_fetch(args.master_db, args.expect_remote_checksum)
        return 0
    if args.command == "apply" and args.confirm != APPLY_CONFIRMATION:
        raise SystemExit(f"--confirm must be exactly: {APPLY_CONFIRMATION}")
    run_migration(
        master_db=args.master_db,
        expected_local_checksum=args.expect_local_checksum,
        apply=args.command == "apply",
        out_db=args.out_db,
        backup_dir=args.backup_dir,
        report_json=args.report_json,
        report_md=args.report_md,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
