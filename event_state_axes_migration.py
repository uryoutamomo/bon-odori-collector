"""Explicit Master RDB migration for canonical event-state axes."""

from collections import Counter

from event_model.event_state_axes import (
    CURRENT_EVENT_STATES,
    DATE_CERTAINTY_TIERS,
    axes_from_legacy_occurrence,
    canonicalize_legacy_current_event_state,
    validate_event_state_axes,
)


MIGRATION_VERSION = 3
MIGRATION_NAME = "event_state_axes_v1"
AXIS_COLUMNS = {
    "current_event_state": "TEXT NOT NULL DEFAULT 'predicted'",
    "date_certainty_tier": "TEXT NOT NULL DEFAULT 'historical_reference'",
}


def table_columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _event_identity(event):
    return "|".join(str(event.get(key) or "") for key in ("name", "venue", "date", "date_end"))


def _public_axes_by_occurrence(events, source_map):
    by_identity = {}
    for event in events:
        identity = _event_identity(event)
        if identity in by_identity:
            raise ValueError(f"duplicate public event identity: {identity}")
        by_identity[identity] = event

    rows = source_map.get("rows") or []
    if int(source_map.get("mapped_count") or len(rows)) != len(rows):
        raise ValueError("source map mapped_count does not match row count")
    if len(rows) != len(events):
        raise ValueError(
            f"public/source-map count mismatch: events={len(events)} source_map={len(rows)}"
        )

    mapped = {}
    for source_row in rows:
        identity = source_row.get("public_event_key") or ""
        occurrence_id = source_row.get("occurrence_id") or ""
        if not occurrence_id or occurrence_id in mapped:
            raise ValueError(f"invalid or duplicate mapped occurrence_id: {occurrence_id!r}")
        event = by_identity.get(identity)
        if event is None:
            raise ValueError(f"source map identity missing from public events: {identity}")
        state = canonicalize_legacy_current_event_state(event.get("current_event_state"))
        tier = event.get("date_certainty_tier")
        validate_event_state_axes(state, tier)
        mapped[occurrence_id] = (state, tier)
    return mapped


def _install_validation_triggers(conn):
    states = ", ".join(f"'{value}'" for value in CURRENT_EVENT_STATES)
    tiers = ", ".join(f"'{value}'" for value in DATE_CERTAINTY_TIERS)
    invalid = f"""
      NEW.current_event_state NOT IN ({states})
      OR NEW.date_certainty_tier NOT IN ({tiers})
      OR (
        NEW.current_event_state IN ('confirmed', 'ended')
        AND NEW.date_certainty_tier != 'confirmed'
      )
      OR (
        NEW.current_event_state IN ('predicted', 'announced')
        AND NEW.date_certainty_tier = 'confirmed'
      )
    """
    conn.executescript(
        f"""
        CREATE TRIGGER IF NOT EXISTS validate_event_state_axes_insert
        BEFORE INSERT ON event_occurrences
        WHEN {invalid}
        BEGIN
          SELECT RAISE(ABORT, 'invalid event state axes');
        END;

        CREATE TRIGGER IF NOT EXISTS validate_event_state_axes_update
        BEFORE UPDATE OF current_event_state, date_certainty_tier ON event_occurrences
        WHEN {invalid}
        BEGIN
          SELECT RAISE(ABORT, 'invalid event state axes');
        END;
        """
    )


def migrate_event_state_axes(conn, *, events, source_map, target_year=2026):
    before_columns = table_columns(conn, "event_occurrences")
    for name, declaration in AXIS_COLUMNS.items():
        if name not in before_columns:
            conn.execute(f"ALTER TABLE event_occurrences ADD COLUMN {name} {declaration}")

    conn.row_factory = None
    occurrence_columns = table_columns(conn, "event_occurrences")
    required = {
        "occurrence_id",
        "event_year",
        "date_start",
        "date_status",
        "lifecycle_status",
        "source_kind",
        "source_url",
        *AXIS_COLUMNS,
    }
    missing = required - occurrence_columns
    if missing:
        raise ValueError(f"event_occurrences missing required columns: {sorted(missing)}")

    mapped = _public_axes_by_occurrence(events, source_map)
    occurrence_ids = {
        row[0] for row in conn.execute("SELECT occurrence_id FROM event_occurrences")
    }
    missing_ids = sorted(set(mapped) - occurrence_ids)
    if missing_ids:
        raise ValueError(f"mapped occurrence ids absent from RDB: {missing_ids[:10]}")

    changed = 0
    rows = conn.execute(
        """
        SELECT occurrence_id, event_year, date_start, date_status, lifecycle_status,
               source_kind, source_url, current_event_state, date_certainty_tier
        FROM event_occurrences
        """
    ).fetchall()
    for row in rows:
        occurrence_id = row[0]
        axes = mapped.get(occurrence_id)
        if axes is None:
            fallback = axes_from_legacy_occurrence(
                {
                    "event_year": row[1],
                    "date_start": row[2],
                    "date_status": row[3],
                    "lifecycle_status": row[4],
                    "source_kind": row[5],
                    "source_url": row[6],
                },
                target_year=target_year,
            )
            axes = (fallback["current_event_state"], fallback["date_certainty_tier"])
        if axes != (row[7], row[8]):
            conn.execute(
                """
                UPDATE event_occurrences
                SET current_event_state = ?, date_certainty_tier = ?
                WHERE occurrence_id = ?
                """,
                (*axes, occurrence_id),
            )
            changed += 1

    _install_validation_triggers(conn)
    if "schema_migrations" in {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }:
        from master_db import now_utc

        conn.execute(
            """
            INSERT OR IGNORE INTO schema_migrations(version, name, applied_at)
            VALUES (?, ?, ?)
            """,
            (MIGRATION_VERSION, MIGRATION_NAME, now_utc()),
        )

    invalid_rows = []
    pair_counts = Counter()
    for occurrence_id, state, tier in conn.execute(
        "SELECT occurrence_id, current_event_state, date_certainty_tier FROM event_occurrences"
    ):
        try:
            validate_event_state_axes(state, tier)
        except ValueError as exc:
            invalid_rows.append({"occurrence_id": occurrence_id, "error": str(exc)})
        pair_counts[(state, tier)] += 1
    if invalid_rows:
        raise ValueError(f"invalid migrated event axes: {invalid_rows[:10]}")

    return {
        "schema": "event_state_axes_migration_v1",
        "migration_version": MIGRATION_VERSION,
        "migration_name": MIGRATION_NAME,
        "columns_added": sorted(set(AXIS_COLUMNS) - before_columns),
        "occurrence_count": len(rows),
        "public_mapped_count": len(mapped),
        "changed_row_count": changed,
        "invalid_row_count": 0,
        "axis_pair_counts": [
            {
                "current_event_state": state,
                "date_certainty_tier": tier,
                "count": count,
            }
            for (state, tier), count in sorted(pair_counts.items())
        ],
    }
