#!/usr/bin/env python3
"""Apply the reviewed venue fix for Ph2 Shinagawa second district.

Default mode is dry-run and writes only review output. --apply updates the
master RDB venue row for 天妙国寺 and adds 天妙国寺境内 as a venue alias.
It does not call Notion, queue Notion sync jobs, or write public JSON.
"""

import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from operation_safety.manual_apply_guards import MASTER_RDB_ONE_OFF_CONFIRMATION, require_confirmation
from master_rdb.master_db import (
    MASTER_DB,
    MASTER_MANIFEST,
    connect_existing,
    normalize_text,
    refresh_manifest_database_state,
)


DATA = Path("data")
OUT_JSON = DATA / "ph2_shinagawa_second_venue_review.json"
OUT_MD = DATA / "ph2_shinagawa_second_venue_review.md"
BACKUP_DIR = DATA / "backups"

VENUE_ID = "ven_913dd815e8665e85"
CANONICAL_NAME = "天妙国寺"
CORRECT_ADDRESS = "東京都品川区南品川2-8-23"
ALIAS = "天妙国寺境内"
SOURCE_URL = "https://www.city.shinagawa.tokyo.jp/PC/shisetsu/shisetsu-kuyakusyo/shisetsu-kuyakusyo-chiiki/hpg000017088.html"


def rows(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render_markdown(result):
    before = result["before"]
    after = result["after"]
    lines = [
        "# Ph2 Shinagawa second venue review",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- applied: {result['applied']}",
        f"- venue_id: `{VENUE_ID}`",
        f"- source: {SOURCE_URL}",
        "",
        "| field | before | after |",
        "| --- | --- | --- |",
        f"| canonical_name | {before.get('canonical_name', '')} | {after.get('canonical_name', '')} |",
        f"| address | {before.get('address', '')} | {after.get('address', '')} |",
        f"| aliases | {', '.join(before.get('aliases', []))} | {', '.join(after.get('aliases', []))} |",
        "",
        "## Notes",
        "",
        "- Reviewed purpose: resolve `天妙国寺境内` to existing venue `天妙国寺` for 品川区民まつり 品川第二地区.",
        "- This is RDB-only: it updates the local master RDB but does not call Notion, queue Notion sync jobs, or write public JSON.",
        "",
    ]
    return "\n".join(lines)


def venue_state(conn):
    venue = rows(
        conn,
        """
        SELECT venue_id, canonical_name, normalized_name, area, address,
               source_url, updated_at
        FROM venues
        WHERE venue_id = ?
        """,
        (VENUE_ID,),
    )
    if not venue:
        raise ValueError(f"venue not found: {VENUE_ID}")
    aliases = rows(
        conn,
        """
        SELECT alias
        FROM venue_aliases
        WHERE venue_id = ?
        ORDER BY alias
        """,
        (VENUE_ID,),
    )
    data = venue[0]
    data["aliases"] = [row["alias"] for row in aliases]
    return data


def apply_review(conn, now):
    conn.execute(
        """
        UPDATE venues
        SET address = ?,
            source_url = ?,
            updated_at = ?
        WHERE venue_id = ?
        """,
        (CORRECT_ADDRESS, SOURCE_URL, now, VENUE_ID),
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO venue_aliases(
          venue_id, alias, normalized_alias, source, confidence
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (VENUE_ID, ALIAS, normalize_text(ALIAS), "ph2_shinagawa_second_review", "manual"),
    )

def backup_db(source, now):
    source = Path(source)
    stamp = now.replace("-", "").replace(":", "").replace("+00:00", "Z")
    backup = BACKUP_DIR / f"{source.stem}.{stamp}{source.suffix}.bak"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup)
    return backup


def run(args):
    now = datetime.now(timezone.utc).isoformat()
    backup_path = ""
    if args.apply:
        backup_path = str(backup_db(args.master_db, now))
    with connect_existing(args.master_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        before = venue_state(conn)
        if before["canonical_name"] != CANONICAL_NAME:
            raise ValueError(f"unexpected venue {VENUE_ID}: {before['canonical_name']}")
        if args.apply:
            apply_review(conn, now)
            conn.commit()
            after = venue_state(conn)
            refresh_manifest_database_state(args.master_db, args.manifest, updated_at=now)
        else:
            after = dict(before)
            after["address"] = CORRECT_ADDRESS
            after["source_url"] = SOURCE_URL
            after["updated_at"] = now
            after["aliases"] = sorted(set(after.get("aliases", []) + [ALIAS]))
        fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    result = {
        "generated_by": "apply_ph2_shinagawa_second_venue_review.py",
        "generated_at": now,
        "mode": "apply" if args.apply else "dry_run",
        "applied": bool(args.apply),
        "source_url": SOURCE_URL,
        "backup_db": backup_path,
        "before": before,
        "after": after,
        "foreign_key_issues": [tuple(row) for row in fk_rows],
    }
    write_json(args.out_json, result)
    Path(args.out_md).write_text(render_markdown(result), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-db", type=Path, default=MASTER_DB)
    parser.add_argument("--manifest", type=Path, default=MASTER_MANIFEST)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        require_confirmation(
            args.apply,
            args.confirm,
            MASTER_RDB_ONE_OFF_CONFIRMATION,
            "Ph2 Shinagawa second venue Master RDB update",
        )
    except ValueError as exc:
        parser.error(str(exc))
    result = run(args)
    print(
        "ph2 shinagawa second venue review: "
        f"mode={result['mode']} applied={result['applied']} "
        f"fk_issues={len(result['foreign_key_issues'])} out={args.out_json}"
    )
    return 1 if result["foreign_key_issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
