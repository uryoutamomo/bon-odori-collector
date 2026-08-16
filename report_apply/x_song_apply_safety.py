"""Shared preflight, backup, transaction, and verification for E2-S writers."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from master_rdb.master_db import connect_existing
from report_apply.rdb_apply_support import backup_db


DEFAULT_BACKUP_DIR = Path("data/backups/x_song_identity_v2")


def _verified_operation(target: Path, operation):
    with connect_existing(target) as conn:
        try:
            report = operation(conn)
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
            if integrity != "ok" or foreign_keys:
                raise ValueError(
                    f"post-write verification failed: integrity={integrity!r} "
                    f"foreign_keys={len(foreign_keys)}"
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return report, integrity, len(foreign_keys)


def run_guarded(
    *, db_path, execute: bool, timestamp: str, temp_prefix: str, operation,
    backup_dir=DEFAULT_BACKUP_DIR,
):
    """Run on a copy first; execute only after preflight, with a backup.

    `operation` must leave its transaction open so integrity/foreign-key
    checks happen before this helper commits it.
    """
    source = Path(db_path)
    with tempfile.TemporaryDirectory(prefix=temp_prefix) as temp:
        preflight = Path(temp) / source.name
        shutil.copy2(source, preflight)
        preflight_report, integrity, foreign_key_count = _verified_operation(preflight, operation)
    if not execute:
        return {
            "report": preflight_report,
            "integrity_check": integrity,
            "foreign_key_issue_count": foreign_key_count,
            "backup_db": None,
        }

    backup = backup_db(source, timestamp, backup_dir)
    report, integrity, foreign_key_count = _verified_operation(source, operation)
    return {
        "report": report,
        "integrity_check": integrity,
        "foreign_key_issue_count": foreign_key_count,
        "backup_db": str(backup),
    }
