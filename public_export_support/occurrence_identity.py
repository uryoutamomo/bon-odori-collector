"""Occurrence identity shared by public projection and synchronization.

Names are a display value. Legacy aliases are usable only when unambiguous.
"""
from collections import Counter
import re


_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


def legacy_event_key(row):
    return f"{row.get('name') or ''}||{row.get('venue') or ''}"


def occurrence_id(row, include_internal=False):
    if not isinstance(row, dict):
        raise ValueError("event must be an object")
    field = "occurrence_id"
    if field not in row:
        if not include_internal or "_occurrence_id" not in row:
            return None
        field = "_occurrence_id"
    value = row[field]
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"invalid {field}: {value!r}")
    return value


def event_year(row, include_internal=False, required=False):
    field = "event_year"
    if field not in row and include_internal and "_event_year" in row:
        field = "_event_year"
    if field not in row:
        if required:
            raise ValueError("event_year is required with occurrence identity")
        return None
    value = row[field]
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 9999:
        raise ValueError(f"invalid {field}: {value!r}")
    return value


def identity_key(row, include_internal=False):
    identifier = occurrence_id(row, include_internal=include_internal)
    return f"occurrence:{identifier}" if identifier else legacy_event_key(row)


def index_events(rows, include_internal=False, require_identity=False):
    indexed = {}
    for row in rows:
        identifier = occurrence_id(row, include_internal=include_internal)
        if require_identity and identifier is None:
            raise ValueError("occurrence_id is required")
        event_year(row, include_internal=include_internal, required=require_identity)
        key = identity_key(row, include_internal=include_internal)
        if key in indexed:
            raise ValueError(f"duplicate event identity: {key}")
        indexed[key] = row
    return indexed


def paired_indexes(left_rows, right_rows):
    """Bridge identified/legacy rows only for an alias unique on both sides.

    Two existing, different occurrence IDs are never bridged by their names.
    Ambiguous legacy migration refuses instead of choosing a year silently.
    """
    left, right = index_events(left_rows), index_events(right_rows)
    left_counts = Counter(legacy_event_key(row) for row in left_rows)
    right_counts = Counter(legacy_event_key(row) for row in right_rows)
    left_aliases = {legacy_event_key(row): key for key, row in left.items()
                    if left_counts[legacy_event_key(row)] == 1}
    right_aliases = {legacy_event_key(row): key for key, row in right.items()
                     if right_counts[legacy_event_key(row)] == 1}
    for own, other, own_counts, other_counts, other_aliases in (
        (left, right, left_counts, right_counts, right_aliases),
        (right, left, right_counts, left_counts, left_aliases),
    ):
        for key, row in list(own.items()):
            if occurrence_id(row) is not None:
                continue
            alias = legacy_event_key(row)
            if not other_counts[alias]:
                continue
            if own_counts[alias] != 1 or other_counts[alias] != 1:
                raise ValueError(f"ambiguous legacy event identity: {alias}")
            other_key = other_aliases[alias]
            if occurrence_id(other[other_key]) is not None:
                if other_key in own:
                    raise ValueError(f"legacy bridge would overwrite occurrence identity: {other_key}")
                own[other_key] = own.pop(key)
    return left, right
