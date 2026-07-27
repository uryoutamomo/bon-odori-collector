"""Default-dry-run entrypoint for the event-series alias store migration."""

import argparse
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

from event_model.series_alias_migration import migrate_event_series_aliases
from master_rdb.master_db import MASTER_DB, connect_existing, table_counts


CONFIRM_TEXT = "MIGRATE EVENT SERIES ALIASES"


def run(*, db_path, execute=False, confirm=None):
    db_path = Path(db_path)
    if execute and confirm != CONFIRM_TEXT:
        raise ValueError(f"--execute requires --confirm {CONFIRM_TEXT!r}")

    temp_dir = None
    target = db_path
    if not execute:
        temp_dir = tempfile.TemporaryDirectory(prefix="event-series-aliases-")
        target = Path(temp_dir.name) / db_path.name
        shutil.copy2(db_path, target)

    try:
        with connect_existing(target) as conn:
            before_counts = table_counts(conn)
            conn.execute("BEGIN IMMEDIATE")
            migration = migrate_event_series_aliases(conn)
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
            after_counts = table_counts(conn)
            stable_tables = sorted(
                (set(before_counts) | set(after_counts)) - {"schema_migrations"}
            )
            count_mismatches = {
                table: {"before": before_counts.get(table, 0), "after": after_counts.get(table, 0)}
                for table in stable_tables
                if before_counts.get(table, 0) != after_counts.get(table, 0)
            }
            if integrity != "ok" or foreign_keys or count_mismatches:
                raise ValueError(
                    f"migration verification failed: integrity={integrity!r} "
                    f"foreign_keys={len(foreign_keys)} count_mismatches={count_mismatches}"
                )
            conn.commit()
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()

    return {
        "schema": "event_series_alias_migration_run_v1",
        "mode": "execute" if execute else "dry_run",
        "status": "pass",
        "migration": migration,
        "verification": {
            "integrity_check": integrity,
            "foreign_key_issue_count": len(foreign_keys),
            "count_mismatches": count_mismatches,
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=MASTER_DB)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm")
    parser.add_argument("--report-out", type=Path)
    args = parser.parse_args(argv)
    report = run(db_path=args.db, execute=args.execute, confirm=args.confirm)
    if args.report_out:
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
