#!/usr/bin/env python3
"""Export master RDB event/venue aliases to a runtime JSON file.

Matching paths (YouTube title/description name resolution) must not open the
master RDB themselves, and they must keep working in environments where the RDB
artifact is absent.  This mirrors ``build_glossary_runtime.py``: the RDB stays
the source of truth, and the committed runtime file is what code reads.
"""

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from master_rdb.master_db import MASTER_DB, connect_existing


OUT = Path("data/event_alias_runtime.json")

EVENT_ALIAS_QUERY = """
SELECT s.canonical_name AS canonical, a.alias AS alias
FROM event_series_aliases a
JOIN event_series s ON s.series_id = a.series_id
ORDER BY s.canonical_name, a.alias
"""

VENUE_ALIAS_QUERY = """
SELECT v.canonical_name AS canonical, a.alias AS alias
FROM venue_aliases a
JOIN venues v ON v.venue_id = a.venue_id
ORDER BY v.canonical_name, a.alias
"""


def table_exists(conn, name):
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
    )


def collect_aliases(conn, query, *, alias_table):
    """Group aliases by canonical name.

    Rows where the alias equals the canonical name are kept on purpose.  The
    matchers ask "does any known name for this event appear in the text", and
    dropping the canonical spelling silently removed matches that the previous
    code-owned table used to make.
    """

    if not table_exists(conn, alias_table):
        return {}
    grouped = {}
    for canonical, alias in conn.execute(query):
        canonical = str(canonical or "").strip()
        alias = str(alias or "").strip()
        if not canonical or not alias:
            continue
        aliases = grouped.setdefault(canonical, [])
        if alias not in aliases:
            aliases.append(alias)
    return grouped


def build_runtime(db_path=MASTER_DB, previous=None):
    """Build the runtime tables, keeping sections the RDB cannot currently supply.

    A database that predates the alias store has no ``event_series_aliases``
    table.  Overwriting the committed file with an empty section there would
    silently drop every alias the matchers rely on, so an absent table keeps
    whatever the previous runtime file held.
    """

    previous = previous if isinstance(previous, dict) else {}
    carried = []
    with connect_existing(Path(db_path)) as conn:
        events = collect_aliases(conn, EVENT_ALIAS_QUERY, alias_table="event_series_aliases")
        venues = collect_aliases(conn, VENUE_ALIAS_QUERY, alias_table="venue_aliases")
        for name, table, current in (
            ("event_aliases", "event_series_aliases", events),
            ("venue_aliases", "venue_aliases", venues),
        ):
            if table_exists(conn, table):
                continue
            kept = previous.get(name)
            if isinstance(kept, dict) and kept:
                carried.append(name)
                if name == "event_aliases":
                    events = kept
                else:
                    venues = kept
    return {
        "generated_by": "build_event_alias_runtime.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "master_rdb",
        "event_aliases": events,
        "venue_aliases": venues,
        "event_alias_count": sum(len(values) for values in events.values()),
        "venue_alias_count": sum(len(values) for values in venues.values()),
        "carried_over_sections": sorted(carried),
    }


def atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".tmp-", suffix=".json", delete=False
    ) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp_name = handle.name
    Path(tmp_name).replace(path)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=MASTER_DB)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    if not Path(args.db).exists():
        print(f"event alias runtime: master RDB not found ({args.db}); keeping existing {args.out}")
        return 0
    previous = {}
    if Path(args.out).exists():
        try:
            previous = json.loads(Path(args.out).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = {}
    runtime = build_runtime(args.db, previous=previous)
    atomic_write_json(args.out, runtime)
    carried = runtime["carried_over_sections"]
    print(
        "event alias runtime: "
        f"events={len(runtime['event_aliases'])} series / {runtime['event_alias_count']} aliases, "
        f"venues={len(runtime['venue_aliases'])} / {runtime['venue_alias_count']} aliases "
        f"-> {args.out}"
    )
    if carried:
        print(
            "event alias runtime: alias table missing from the RDB; kept the previous "
            f"{', '.join(carried)} section(s). Run run_series_alias_migration.py on the RDB."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
