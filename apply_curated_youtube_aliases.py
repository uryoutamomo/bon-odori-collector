"""Move the curated YouTube-matching aliases from code into the master RDB.

``youtube_backfill/event_aliases.py`` used to own these records because the RDB
had no event-series alias store.  Now that ``event_series_aliases`` exists, the
seed below is written once into the RDB and the code-owned copy is dropped, so
adding an alias later is a data change rather than a pull request.
"""

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from master_rdb.master_db import MASTER_DB, connect_existing, normalize_text, table_counts


CONFIRM_TEXT = "APPLY CURATED YOUTUBE ALIASES"
SOURCE = "curated_youtube_matching"
CONFIDENCE = "manual"

SEED_EVENT_ALIASES = {
    "奥浅草盆踊り": (
        "Oku Asakusa Bon Odori",
        "Oku Asakusa Bon Dance",
        "Oku Asakusa Bon Odori Dance Festival",
    ),
    "自由が丘納涼盆踊り大会": (
        "Jiyugaoka Bon Odori",
        "Jiyugaoka Bon Odori Festival",
        "Jiyugaoka Bon Odori Dance Festival",
        "自由が丘盆踊り",
    ),
    "丸の内de盆踊り": (
        "Marunouchi Bon Odori",
        "Marunouchi Bon Odori Festival",
        "Marunouchi Bon Odori Dance Festival",
        "丸の内盆踊り",
        "東京丸の内盆踊り",
    ),
    "渋谷盆踊り": (
        "Shibuya Bon Odori",
        "Shibuya Bon Odori Festival",
        "Shibuya Bon Odori Dance Festival",
        "渋谷盆踊り",
    ),
    "神田明神納涼祭り": (
        "Kanda Myojin Noryo Matsuri",
        "Kanda Myojin Summer Festival",
        "Kanda Myojin Shrine Bon Dance",
        "Kanda Myojin Bon Odori",
        "神田明神納涼祭り アニソン盆踊り",
    ),
}

SEED_VENUE_ALIASES = {
    "自由が丘駅前ロータリー 特設会場": (
        "Jiyugaoka Station",
        "Jiyugaoka Station Rotary",
        "in front of Jiyugaoka Station",
        "自由が丘駅前",
    ),
    "行幸通り": (
        "Gyoko Dori",
        "Gyoko Avenue",
        "in front of Tokyo Station",
    ),
    "渋谷109前": (
        "Shibuya 109",
        "in front of Shibuya 109",
        "SHIBUYA109前",
    ),
    "神田明神境内": (
        "Kanda Myojin Shrine",
        "Kanda Myojin",
        "神田明神",
    ),
}


def resolve_ids(conn, table, id_column, canonical_names):
    """Map canonical names to ids, failing loudly on anything ambiguous."""

    resolved = {}
    for name in canonical_names:
        rows = conn.execute(
            f"SELECT {id_column} FROM {table} WHERE canonical_name = ?", (name,)
        ).fetchall()
        if len(rows) != 1:
            raise ValueError(
                f"{table}.canonical_name {name!r} resolved to {len(rows)} rows; expected exactly 1"
            )
        resolved[name] = rows[0][0]
    return resolved


def insert_aliases(conn, table, id_column, seed, resolved):
    inserted = []
    skipped = []
    for canonical, aliases in seed.items():
        owner_id = resolved[canonical]
        for alias in aliases:
            normalized = normalize_text(alias)
            if not normalized:
                skipped.append({"canonical": canonical, "alias": alias, "reason": "empty_normalized"})
                continue
            existing = conn.execute(
                f"SELECT alias FROM {table} WHERE {id_column} = ? AND normalized_alias = ?",
                (owner_id, normalized),
            ).fetchone()
            if existing:
                skipped.append(
                    {"canonical": canonical, "alias": alias, "reason": "already_present"}
                )
                continue
            conn.execute(
                f"""
                INSERT INTO {table}({id_column}, alias, normalized_alias, source, confidence)
                VALUES (?, ?, ?, ?, ?)
                """,
                (owner_id, alias, normalized, SOURCE, CONFIDENCE),
            )
            inserted.append({"canonical": canonical, "alias": alias, id_column: owner_id})
    return inserted, skipped


def apply_aliases(conn):
    series_ids = resolve_ids(conn, "event_series", "series_id", SEED_EVENT_ALIASES)
    venue_ids = resolve_ids(conn, "venues", "venue_id", SEED_VENUE_ALIASES)
    event_inserted, event_skipped = insert_aliases(
        conn, "event_series_aliases", "series_id", SEED_EVENT_ALIASES, series_ids
    )
    venue_inserted, venue_skipped = insert_aliases(
        conn, "venue_aliases", "venue_id", SEED_VENUE_ALIASES, venue_ids
    )
    return {
        "schema": "curated_youtube_alias_apply_v1",
        "event_alias_inserted": event_inserted,
        "event_alias_skipped": event_skipped,
        "venue_alias_inserted": venue_inserted,
        "venue_alias_skipped": venue_skipped,
        "event_alias_inserted_count": len(event_inserted),
        "venue_alias_inserted_count": len(venue_inserted),
    }


def run(*, db_path, execute=False, confirm=None):
    db_path = Path(db_path)
    if execute and confirm != CONFIRM_TEXT:
        raise ValueError(f"--execute requires --confirm {CONFIRM_TEXT!r}")

    temp_dir = None
    target = db_path
    if not execute:
        temp_dir = tempfile.TemporaryDirectory(prefix="curated-youtube-aliases-")
        target = Path(temp_dir.name) / db_path.name
        shutil.copy2(db_path, target)

    try:
        with connect_existing(target) as conn:
            before_counts = table_counts(conn)
            conn.execute("BEGIN IMMEDIATE")
            report = apply_aliases(conn)
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
            after_counts = table_counts(conn)
            changed_tables = {"event_series_aliases", "venue_aliases"}
            unexpected = {
                table: {"before": before_counts.get(table, 0), "after": after_counts.get(table, 0)}
                for table in sorted(set(before_counts) | set(after_counts))
                if table not in changed_tables
                and before_counts.get(table, 0) != after_counts.get(table, 0)
            }
            if integrity != "ok" or foreign_keys or unexpected:
                raise ValueError(
                    f"alias apply verification failed: integrity={integrity!r} "
                    f"foreign_keys={len(foreign_keys)} unexpected_table_changes={unexpected}"
                )
            conn.commit()
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()

    return {
        **report,
        "mode": "execute" if execute else "dry_run",
        "status": "pass",
        "verification": {
            "integrity_check": integrity,
            "foreign_key_issue_count": len(foreign_keys),
            "unexpected_table_changes": unexpected,
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
