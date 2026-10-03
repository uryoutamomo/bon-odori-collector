"""Reviewed occurrence-bound official source links for the public exporter."""

import json
from dataclasses import dataclass
from pathlib import Path


REQUIRED_FIELDS = (
    "occurrence_id",
    "event_year",
    "date_start",
    "date_end",
    "source_url",
)
SCHEMA = "public_official_source_links_v1"


@dataclass(frozen=True)
class OfficialSourceLinkRegistry:
    reviewed: frozenset
    legacy_preserved: frozenset


EMPTY_REGISTRY = OfficialSourceLinkRegistry(frozenset(), frozenset())


def _review_key(row):
    if not isinstance(row, dict):
        raise ValueError("official source link review rows must be objects")
    missing = [field for field in REQUIRED_FIELDS if field not in row]
    if missing:
        raise ValueError(f"official source link review row missing: {', '.join(missing)}")
    occurrence_id = row["occurrence_id"]
    event_year = row["event_year"]
    date_start = row["date_start"]
    date_end = row["date_end"]
    source_url = row["source_url"]
    if not isinstance(occurrence_id, str) or not occurrence_id:
        raise ValueError("official source link review occurrence_id must be a nonempty string")
    if isinstance(event_year, bool) or not isinstance(event_year, int):
        raise ValueError("official source link review event_year must be an integer")
    if not all(isinstance(value, str) for value in (date_start, date_end, source_url)):
        raise ValueError("official source link review dates and source_url must be strings")
    return occurrence_id, event_year, date_start, date_end, source_url


def load_reviewed_official_source_links(path):
    """Load exact reviewed and compatibility-preserved occurrence/date/URL tuples."""
    path = Path(path)
    if not path.exists():
        return EMPTY_REGISTRY
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ValueError(f"official source link review schema must be {SCHEMA}")
    reviewed_rows = payload.get("reviews")
    legacy_rows = payload.get("legacy_preserved", [])
    if not isinstance(reviewed_rows, list) or not isinstance(legacy_rows, list):
        raise ValueError("official source link review reviews and legacy_preserved must be lists")
    reviewed = [_review_key(row) for row in reviewed_rows]
    legacy = [_review_key(row) for row in legacy_rows]
    if len(reviewed) != len(set(reviewed)) or len(legacy) != len(set(legacy)):
        raise ValueError("official source link review contains duplicate occurrence/date/URL rows")
    if set(reviewed) & set(legacy):
        raise ValueError("official source link review cannot overlap reviewed and legacy_preserved URLs")
    return OfficialSourceLinkRegistry(frozenset(reviewed), frozenset(legacy))


def is_reviewed_official_source_link(reviews, *, occurrence_id, event_year, date_start, date_end, source_url):
    """Return whether the complete RDB identity is explicitly reviewed."""
    keys = reviews.reviewed if isinstance(reviews, OfficialSourceLinkRegistry) else reviews
    return (occurrence_id, event_year, date_start or "", date_end or "", source_url) in keys


def is_legacy_preserved_official_source_link(registry, *, occurrence_id, event_year, date_start, date_end, source_url):
    """Return whether this exact formerly-public RDB source may remain official."""
    keys = registry.legacy_preserved if isinstance(registry, OfficialSourceLinkRegistry) else registry
    return (
        occurrence_id, event_year, date_start or "", date_end or "", source_url
    ) in keys
