"""Shared plumbing for RDB apply scripts: copy/backup DB files, run audits, write reports.

Factored out of apply_ph2_ebara_fifth_rdb.py's preflight/backup/audit/report pattern so
new apply scripts (starting with apply_firsthand_field_report.py) don't have to re-copy it.
Existing one-off apply_ph2_*.py scripts are left untouched to avoid disturbing reviewed,
working behavior.
"""

import json
import shutil
import sqlite3
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from master_rdb import audit as audit_master_rdb


def rows(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def scalar(conn, query, params=()):
    return conn.execute(query, params).fetchone()[0]


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_db(source, out_db):
    source = Path(source)
    out_db = Path(out_db)
    if not source.exists():
        raise FileNotFoundError(source)
    out_db.parent.mkdir(parents=True, exist_ok=True)
    if out_db.exists():
        out_db.unlink()
    shutil.copy2(source, out_db)


def backup_db(source, now, backup_dir):
    source = Path(source)
    backup_dir = Path(backup_dir)
    if not source.exists():
        raise FileNotFoundError(source)
    stamp = now.replace("-", "").replace(":", "").replace("+00:00", "Z")
    backup = backup_dir / f"{source.stem}.{stamp}{source.suffix}.bak"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup)
    return backup


def audit_db(db_path, out_json, out_md):
    args = SimpleNamespace(
        db=str(db_path),
        notion_db=str(audit_master_rdb.NOTION_DB),
        song_occurrences=str(audit_master_rdb.SONG_OCCURRENCES),
        manifest=str(audit_master_rdb.MASTER_MANIFEST),
        out_json=str(out_json),
        out_md=str(out_md),
    )
    return audit_master_rdb.audit(args)


def issue_summary(issues):
    return dict(Counter(row.get("severity") for row in issues))


def has_high_issue(*issue_lists):
    return any(row.get("severity") == "high" for issues in issue_lists for row in issues)
