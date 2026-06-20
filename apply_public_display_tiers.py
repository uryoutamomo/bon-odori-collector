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


def apply_display_tiers(events):
    for event in events:
        event["display_tier"] = display_tier_for_event(event)
    return events
