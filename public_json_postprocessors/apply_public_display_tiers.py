"""Normalize top-level display_tier for public event cards."""

from event_model.event_state_axes import (
    axes_from_legacy_public_event,
    canonicalize_legacy_current_event_state,
    legacy_public_fields_from_axes,
    validate_event_state_axes,
)


DISPLAY_TIER_ORDER = (
    "confirmed",
    "rule_predicted",
    "historical_slide",
    "season_hint",
    "historical_reference",
    "ended",
)


def display_tier_for_event(event, *, target_year=2026):
    if event.get("public_category") == "ended":
        return "ended"
    if str(event.get("date") or "").startswith(f"{target_year}-") and event.get("public_category") == "upcoming":
        return "confirmed"
    if event.get("date_prediction"):
        return "rule_predicted"
    if event.get("historical_slide"):
        return "historical_slide"
    if event.get("season_hint") or event.get("public_category") == "date_unknown":
        return "season_hint"
    if event.get("historical_reference") or event.get("public_category") == "recurring_last_year":
        return "historical_reference"
    if event.get("public_category") == "upcoming":
        return "confirmed"
    return "season_hint"


def current_event_state_for_event(event, *, target_year=2026):
    return axes_from_legacy_public_event(event, target_year=target_year)["current_event_state"]


def date_certainty_tier_for_event(event, *, target_year=2026):
    return axes_from_legacy_public_event(event, target_year=target_year)["date_certainty_tier"]


def apply_public_state_axes(events, *, target_year=2026):
    for event in events:
        event.update(axes_from_legacy_public_event(event, target_year=target_year))
    return events


def apply_legacy_public_fields_from_axes(events):
    """Project compatibility fields from canonical axes without consulting old state."""
    for event in events:
        state = canonicalize_legacy_current_event_state(event.get("current_event_state"))
        tier = event.get("date_certainty_tier")
        validate_event_state_axes(state, tier)
        event["current_event_state"] = state
        event.update(legacy_public_fields_from_axes(state, tier))
    return events


def apply_display_tiers(events, *, prefer_existing_axes=False, target_year=2026):
    if prefer_existing_axes:
        return apply_legacy_public_fields_from_axes(events)
    for event in events:
        event["display_tier"] = display_tier_for_event(event, target_year=target_year)
    apply_public_state_axes(events, target_year=target_year)
    return events
