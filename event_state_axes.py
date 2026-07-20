"""Canonical event-state axes and legacy public compatibility mappings."""

CURRENT_EVENT_STATES = (
    "predicted",
    "announced",
    "confirmed",
    "ended",
    "cancelled",
)

DATE_CERTAINTY_TIERS = (
    "confirmed",
    "rule_predicted",
    "historical_slide",
    "season_hint",
    "historical_reference",
)


class EventStateAxesError(ValueError):
    """Raised when an event-state axis value or combination is invalid."""


def validate_event_state_axes(current_event_state, date_certainty_tier):
    if current_event_state not in CURRENT_EVENT_STATES:
        raise EventStateAxesError(f"invalid current_event_state: {current_event_state!r}")
    if date_certainty_tier not in DATE_CERTAINTY_TIERS:
        raise EventStateAxesError(f"invalid date_certainty_tier: {date_certainty_tier!r}")
    if current_event_state in {"confirmed", "ended"} and date_certainty_tier != "confirmed":
        raise EventStateAxesError(
            f"{current_event_state} requires date_certainty_tier='confirmed'"
        )
    if current_event_state in {"predicted", "announced"} and date_certainty_tier == "confirmed":
        raise EventStateAxesError(
            f"{current_event_state} cannot use date_certainty_tier='confirmed'"
        )
    return current_event_state, date_certainty_tier


def canonicalize_legacy_current_event_state(value):
    """Map the temporary public-axis vocabulary onto the finite D vocabulary."""
    return "predicted" if value in {None, "", "unknown", "unconfirmed"} else str(value)


def legacy_public_fields_from_axes(current_event_state, date_certainty_tier):
    """Derive legacy public category/tier fields from the canonical axes."""
    current_event_state = canonicalize_legacy_current_event_state(current_event_state)
    validate_event_state_axes(current_event_state, date_certainty_tier)
    if current_event_state == "cancelled":
        return {"public_category": "cancelled", "display_tier": "cancelled"}
    if current_event_state == "ended":
        return {"public_category": "ended", "display_tier": "ended"}
    if current_event_state == "confirmed":
        return {"public_category": "upcoming", "display_tier": "confirmed"}
    if date_certainty_tier == "season_hint":
        return {"public_category": "date_unknown", "display_tier": "season_hint"}
    return {
        "public_category": "recurring_last_year",
        "display_tier": date_certainty_tier,
    }


def axes_from_legacy_public_event(event):
    """One-way shadow-migration adapter from the lossy pre-D projection.

    The old fields conflate current state and display, so this is intentionally not
    the inverse of ``legacy_public_fields_from_axes``.  Use it only to backfill and
    shadow-compare legacy rows; canonical axes are authoritative after migration.
    """
    lifecycle = str(event.get("lifecycle_status") or "").lower()
    category = event.get("public_category")
    date_value = str(event.get("date") or "")

    if lifecycle == "cancelled" or category == "cancelled":
        state = "cancelled"
    elif category == "ended":
        state = "ended"
    elif date_value.startswith("2026-") and category == "upcoming":
        state = "confirmed"
    elif category == "upcoming":
        state = "announced"
    else:
        state = "predicted"

    if state in {"confirmed", "ended"}:
        tier = "confirmed"
    elif event.get("date_prediction"):
        tier = "rule_predicted"
    elif event.get("historical_slide"):
        tier = "historical_slide"
    elif event.get("season_hint") or category == "date_unknown":
        tier = "season_hint"
    elif event.get("historical_reference") or category == "recurring_last_year":
        tier = "historical_reference"
    else:
        tier = "season_hint"

    validate_event_state_axes(state, tier)
    return {
        "current_event_state": state,
        "date_certainty_tier": tier,
    }


def axes_from_legacy_occurrence(row, *, target_year=2026):
    """Finite fallback mapping for RDB rows not present in the public projection."""
    date_status = str(row.get("date_status") or "unknown").lower()
    lifecycle = str(row.get("lifecycle_status") or "").lower()
    source_kind = str(row.get("source_kind") or "").lower()
    source_url = str(row.get("source_url") or "").strip()
    event_year = int(row.get("event_year") or 0)

    if date_status == "cancelled" or lifecycle == "cancelled":
        state = "cancelled"
        tier = "confirmed" if row.get("date_start") else "season_hint"
    elif date_status == "ended":
        state, tier = "ended", "confirmed"
    elif date_status == "confirmed":
        state, tier = "confirmed", "confirmed"
    elif date_status == "predicted":
        state, tier = "predicted", "rule_predicted"
    elif (
        event_year == target_year
        and source_url
        and (source_kind.endswith("_current_year") or source_kind == "official")
    ):
        state, tier = "announced", "season_hint"
    else:
        state, tier = "predicted", "historical_reference"
    validate_event_state_axes(state, tier)
    return {
        "current_event_state": state,
        "date_certainty_tier": tier,
    }


def event_state_axes_columns_present(conn):
    columns = {row[1] for row in conn.execute("PRAGMA table_info(event_occurrences)")}
    return {"current_event_state", "date_certainty_tier"}.issubset(columns)


def update_occurrence_state_axes(conn, occurrence_id, current_event_state, date_certainty_tier):
    """Update canonical axes when the RDB has migrated; remain safe on old DB copies."""
    validate_event_state_axes(current_event_state, date_certainty_tier)
    if not event_state_axes_columns_present(conn):
        return False
    conn.execute(
        """
        UPDATE event_occurrences
        SET current_event_state = ?, date_certainty_tier = ?
        WHERE occurrence_id = ?
        """,
        (current_event_state, date_certainty_tier, occurrence_id),
    )
    return True
