"""Default-dry-run entrypoint for the D event-state axes RDB migration."""

import argparse
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

from public_json_postprocessors.compare_event_state_axes import compare_events
from event_model.state_axes_migration import migrate_event_state_axes
from master_rdb.master_db import MASTER_DB, connect_existing, table_counts


CONFIRM_TEXT = "MIGRATE EVENT STATE AXES"


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run(
    *,
    db_path,
    events_path,
    source_map_path,
    target_year,
    execute=False,
    confirm=None,
    derive_from_db=False,
    today=None,
):
    db_path = Path(db_path)
    if derive_from_db:
        from export_public_events import build_public_events_from_master, project_public_events

        raw_events, *_ = build_public_events_from_master(
            db_path, target_year=target_year
        )
        # Recompute the desired axes from current RDB facts and the legacy
        # projection.  Dropping stored axes here avoids a circular no-op and
        # lets the scheduled sync advance confirmed -> ended when the source
        # projection does so.
        for event in raw_events:
            event.pop("current_event_state", None)
            event.pop("date_certainty_tier", None)
            event["_canonical_state_axes"] = False
        projection = project_public_events(
            raw_events,
            target_year=target_year,
            db_path=db_path,
            today=today,
        )
        events = projection["public_events"]
        source_map = projection["source_map"]
    else:
        events = _load(events_path)
        source_map = _load(source_map_path)
    shadow = compare_events(events, target_year=target_year)
    if shadow["status"] != "pass":
        raise ValueError(
            f"legacy/axes shadow comparison failed: {shadow['mismatch_count']} mismatches"
        )
    if execute and confirm != CONFIRM_TEXT:
        raise ValueError(f"--execute requires --confirm {CONFIRM_TEXT!r}")

    temp_dir = None
    target = db_path
    if not execute:
        temp_dir = tempfile.TemporaryDirectory(prefix="event-state-axes-")
        target = Path(temp_dir.name) / db_path.name
        shutil.copy2(db_path, target)

    try:
        with connect_existing(target) as conn:
            before_counts = table_counts(conn)
            conn.execute("BEGIN IMMEDIATE")
            migration = migrate_event_state_axes(
                conn, events=events, source_map=source_map, target_year=target_year
            )
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
            after_counts = table_counts(conn)
            stable_tables = sorted((set(before_counts) | set(after_counts)) - {"schema_migrations"})
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
        "schema": "event_state_axes_migration_run_v1",
        "mode": "execute" if execute else "dry_run",
        "status": "pass",
        "shadow": {
            "event_count": shadow["event_count"],
            "mismatch_count": shadow["mismatch_count"],
        },
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
    parser.add_argument("--events", type=Path, default=Path("data/public/events_public.json"))
    parser.add_argument("--source-map", type=Path, default=Path("data/public_event_source_map.json"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm")
    parser.add_argument("--derive-from-db", action="store_true")
    parser.add_argument("--today")
    parser.add_argument("--target-year", type=int, required=True)
    parser.add_argument("--report-out", type=Path)
    args = parser.parse_args(argv)
    report = run(
        db_path=args.db,
        events_path=args.events,
        source_map_path=args.source_map,
        execute=args.execute,
        confirm=args.confirm,
        derive_from_db=args.derive_from_db,
        today=args.today,
        target_year=args.target_year,
    )
    if args.report_out:
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
