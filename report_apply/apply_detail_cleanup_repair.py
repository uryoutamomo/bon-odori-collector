#!/usr/bin/env python3
"""Apply the one-time, hash-pinned 14-occurrence detail cleanup repair.

The repair deliberately has no evidence or schedule side effects: it replaces
only ``event_occurrences.detail`` and its audit timestamp after all fourteen
current-detail preconditions have been checked.
"""

import argparse
from contextlib import closing
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from master_rdb.master_db import connect_existing, table_counts
from report_apply.rdb_apply_support import audit_db, backup_db, copy_db, write_json


CONFIRM = "APPLY DETAIL CLEANUP REPAIR 14"


def digest(value):
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def report_digest(report):
    payload = {key: value for key, value in report.items() if key != "report_sha256"}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate(report):
    events, expected = report.get("events"), report.get("expected_current_detail_sha256")
    if report.get("report_type") != "detail_cleanup_repair" or not isinstance(events, list) or len(events) != 14 or not isinstance(expected, dict):
        raise ValueError("invalid repair report")
    if report.get("report_sha256") != report_digest(report):
        raise ValueError("repair report digest mismatch")
    ids = [event.get("occurrence_id") for event in events]
    if len(set(ids)) != 14 or set(ids) != set(expected):
        raise ValueError("repair report must pin exactly 14 occurrence ids")
    for event in events:
        expected_hash = expected[event["occurrence_id"]]
        if event.get("action") != "confirm_existing" or not event.get("detail_replacement") or not isinstance(expected_hash, str) or len(expected_hash) != 64:
            raise ValueError("missing replacement or expected detail hash")


def apply(conn, report, now):
    """Preflight every row before issuing the first UPDATE."""
    planned = []
    for event in report["events"]:
        occurrence_id = event["occurrence_id"]
        row = conn.execute("SELECT detail FROM event_occurrences WHERE occurrence_id = ?", (occurrence_id,)).fetchone()
        if not row:
            raise ValueError(f"occurrence missing: {occurrence_id}")
        actual = digest(row[0])
        wanted = report["expected_current_detail_sha256"][occurrence_id]
        if actual != wanted:
            raise ValueError(f"detail precondition mismatch: {occurrence_id} expected={wanted} actual={actual}")
        planned.append((event["detail_replacement"], occurrence_id))
    for detail, occurrence_id in planned:
        conn.execute("UPDATE event_occurrences SET detail = ?, updated_at = ? WHERE occurrence_id = ?", (detail, now, occurrence_id))
    return [occurrence_id for _, occurrence_id in planned]


def _transaction_checks(conn):
    foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if foreign_keys or integrity != "ok":
        raise ValueError(f"integrity check failed: fk={foreign_keys[:10]} integrity={integrity}")


def _replace_after_verified(source, destination):
    destination = Path(destination)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
        staged = Path(handle.name)
    try:
        shutil.copy2(source, staged)
        os.replace(staged, destination)
    finally:
        staged.unlink(missing_ok=True)


def run(args):
    report = json.loads(args.report.read_text(encoding="utf-8"))
    validate(report)
    if args.apply and args.confirm != CONFIRM:
        raise ValueError(f"--apply requires --confirm '{CONFIRM}'")

    now = datetime.now(timezone.utc).isoformat()
    with tempfile.TemporaryDirectory(prefix="detail-cleanup-repair-") as temp_dir:
        working = Path(temp_dir) / "verified.sqlite"
        copy_db(args.master_db, working)
        with closing(connect_existing(working)) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            changes = apply(conn, report, now)
            _transaction_checks(conn)
            conn.commit()
            counts = table_counts(conn)
        audit = audit_db(working, args.out_json.with_suffix(".audit.json"), args.out_md.with_suffix(".audit.md"))
        if audit["issue_count"]:
            raise ValueError(f"audit findings: {audit['issue_count']}")
        if args.apply:
            backup = backup_db(args.master_db, now, Path("data/backups"))
            _replace_after_verified(working, args.master_db)
            target = args.master_db
        else:
            copy_db(working, args.out_db)
            backup = None
            target = args.out_db

    result = {
        "mode": "apply" if args.apply else "dry_run",
        "report_sha256": report["report_sha256"],
        "write_guard": {"db_committed": True, "rolled_back": False},
        "summary": {"issues_count": 0, "issues_by_severity": {}, "table_counts": counts},
        "audit": {"issue_count": 0, "issues_by_severity": {}},
        "applied": {"events_applied": [{"occurrence_id": value} for value in changes], "events_unresolved": []},
        "outputs": {"target_db": str(target), "backup_db": str(backup) if backup else ""},
    }
    write_json(args.out_json, result)
    args.out_md.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--master-db", type=Path, default=Path("data/bon_odori_master.sqlite"))
    parser.add_argument("--out-db", type=Path, default=Path("data/detail_cleanup_repair_dry_run.sqlite"))
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        run(args)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
