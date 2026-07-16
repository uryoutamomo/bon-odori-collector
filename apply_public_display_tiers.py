"""Normalize top-level display_tier for public event cards."""


DISPLAY_TIER_ORDER = (
    "confirmed",
    "rule_predicted",
    "historical_slide",
    "season_hint",
    "historical_reference",
    "ended",
)


def display_tier_for_event(event):
    if event.get("public_category") == "ended":
        return "ended"
    if str(event.get("date") or "").startswith("2026-") and event.get("public_category") == "upcoming":
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


def current_event_state_for_event(event):
    lifecycle = str(event.get("lifecycle_status") or "").lower()
    if lifecycle == "cancelled" or event.get("public_category") == "cancelled":
        return "cancelled"
    if event.get("public_category") == "ended":
        return "ended"
    if str(event.get("date") or "").startswith("2026-") and event.get("public_category") == "upcoming":
        return "confirmed"
    if event.get("date_prediction") or event.get("historical_slide") or event.get("season_hint"):
        return "predicted"
    return "unconfirmed"


def date_certainty_tier_for_event(event):
    if event.get("public_category") == "ended":
        return "confirmed"
    if str(event.get("date") or "").startswith("2026-") and event.get("public_category") == "upcoming":
        return "confirmed"
    if event.get("date_prediction"):
        return "rule_predicted"
    if event.get("historical_slide"):
        return "historical_slide"
    if event.get("season_hint") or event.get("public_category") == "date_unknown":
        return "season_hint"
    if event.get("historical_reference") or event.get("public_category") == "recurring_last_year":
        return "historical_reference"
    return "unknown"


def apply_public_state_axes(events):
    for event in events:
        event["current_event_state"] = current_event_state_for_event(event)
        event["date_certainty_tier"] = date_certainty_tier_for_event(event)
    return events


def apply_display_tiers(events):
    for event in events:
        event["display_tier"] = display_tier_for_event(event)
    apply_public_state_axes(events)
    return events
