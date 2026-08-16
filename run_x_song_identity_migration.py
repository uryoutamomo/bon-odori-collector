"""Default-dry-run entrypoint for the E2-S v2 schema migration."""

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from event_model.x_song_identity_migration import migrate_x_song_identity
from master_rdb.master_db import MASTER_DB, connect_existing, table_counts


CONFIRM_TEXT = "MIGRATE X SONG IDENTITY V2"
E2_TABLES = {
    "x_song_resolution_decisions",
    "x_occurrence_resolution_decisions",
    "x_song_materializations",
    "x_song_retractions",
    "local_judgment_schema_migrations",
}


def run(*, db_path, execute=False, confirm=None):
    db_path = Path(db_path)
    if execute and confirm != CONFIRM_TEXT:
        raise ValueError(f"--execute requires --confirm {CONFIRM_TEXT!r}")

    temp_dir = None
    target = db_path
    if not execute:
        temp_dir = tempfile.TemporaryDirectory(prefix="x-song-identity-v2-")
        target = Path(temp_dir.name) / db_path.name
        shutil.copy2(db_path, target)

    try:
        with connect_existing(target) as conn:
            before = table_counts(conn)
            conn.execute("BEGIN IMMEDIATE")
            migration = migrate_x_song_identity(conn)
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
            after = table_counts(conn)
            changed = {
                name: {"before": before.get(name, 0), "after": after.get(name, 0)}
                for name in sorted((set(before) | set(after)) - E2_TABLES)
                if before.get(name, 0) != after.get(name, 0)
            }
            if integrity != "ok" or foreign_keys or changed:
                raise ValueError(
                    f"migration verification failed: integrity={integrity!r} "
                    f"foreign_keys={len(foreign_keys)} changed={changed}"
                )
            conn.commit()
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()

    return {
        "schema": "x_song_identity_migration_run_v2",
        "mode": "execute" if execute else "dry_run",
        "status": "pass",
        "migration": migration,
        "verification": {
            "integrity_check": integrity,
            "foreign_key_issue_count": len(foreign_keys),
            "unchanged_existing_tables": not changed,
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=MASTER_DB)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm")
    args = parser.parse_args(argv)
    print(json.dumps(run(db_path=args.db, execute=args.execute, confirm=args.confirm), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
