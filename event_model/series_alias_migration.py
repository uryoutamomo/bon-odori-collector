"""Master RDB migration that adds the event-series alias store.

Venue and song aliases already live in the RDB (``venue_aliases`` /
``song_aliases``).  Event series had no equivalent, so matchers that need to
recognise an event under a shorter or romanized name had to keep those aliases
in code.  This migration adds the missing table so aliases become data.
"""

from master_rdb.master_db import now_utc


MIGRATION_VERSION = 4
MIGRATION_NAME = "event_series_aliases_v1"
TABLE = "event_series_aliases"

CREATE_TABLE = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
  series_id TEXT NOT NULL,
  alias TEXT NOT NULL,
  normalized_alias TEXT NOT NULL,
  source TEXT NOT NULL,
  confidence TEXT NOT NULL DEFAULT 'manual',
  PRIMARY KEY (series_id, normalized_alias),
  FOREIGN KEY (series_id) REFERENCES event_series(series_id)
);
"""


def table_names(conn):
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def migrate_event_series_aliases(conn):
    """Create the event-series alias table.  Existing rows are never touched."""

    before = table_names(conn)
    if "event_series" not in before:
        raise ValueError("event_series table is required before adding its alias store")

    conn.executescript(CREATE_TABLE)

    after = table_names(conn)
    if TABLE not in after:
        raise ValueError(f"{TABLE} was not created")

    if "schema_migrations" in after:
        conn.execute(
            """
            INSERT OR IGNORE INTO schema_migrations(version, name, applied_at)
            VALUES (?, ?, ?)
            """,
            (MIGRATION_VERSION, MIGRATION_NAME, now_utc()),
        )

    return {
        "schema": "event_series_alias_migration_v1",
        "migration_version": MIGRATION_VERSION,
        "migration_name": MIGRATION_NAME,
        "table_created": TABLE not in before,
        "alias_row_count": conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0],
        "series_count": conn.execute("SELECT COUNT(*) FROM event_series").fetchone()[0],
    }
