"""Helpers for turning Uchida-san's firsthand attendance reports into master RDB rows.

Domain logic only (no CLI, no argparse). apply_firsthand_field_report.py is the
entry point that wires these functions into the standard preflight/backup/audit
apply flow shared with apply_ph2_ebara_fifth_rdb.py.

Thin wrappers around event_report_helpers.py's source-agnostic core engine,
fixed to the firsthand vocabulary (platform/evidence_type/role/evidence_status).
Public signatures, constants, return values, and generated ids are unchanged
from before this module was split out -- apply_firsthand_field_report.py and
its tests do not need to change.
"""

from event_report_helpers import (
    confirm_occurrence_schedule_venue,  # noqa: F401 (re-exported for callers that want it)
    ensure_series_and_occurrence as _ensure_series_and_occurrence,
    ensure_venue,  # noqa: F401
    find_occurrence_candidates,  # noqa: F401
    find_venue_candidates,  # noqa: F401
    link_occurrence_evidence as _link_occurrence_evidence,
    upsert_evidence_item as _upsert_evidence_item,
    upsert_occurrence_song as _upsert_occurrence_song,
)
from master_db import now_utc, stable_id


PLATFORM_PERSONAL_FIRSTHAND = "personal_firsthand"
EVIDENCE_TYPE_FIRSTHAND_ATTENDANCE = "firsthand_attendance"
SOURCE_KIND_PERSONAL_FIRSTHAND_CURRENT_YEAR = "personal_firsthand_current_year"
EVIDENCE_LINK_TARGET_FIRSTHAND_REPORT = "firsthand_report"
EVIDENCE_SOURCE_KEY = "uchida_firsthand"


def ensure_series_and_occurrence(
    conn,
    series_name,
    venue_id,
    event_year,
    date_start,
    date_end=None,
    *,
    source_url=None,
    detail=None,
    now=None,
):
    """Create (or reuse) an event_series + event_occurrences row for a firsthand new-event report."""
    return _ensure_series_and_occurrence(
        conn,
        series_name,
        venue_id,
        event_year,
        date_start,
        date_end,
        source_kind=SOURCE_KIND_PERSONAL_FIRSTHAND_CURRENT_YEAR,
        source_url=source_url,
        detail=detail,
        date_basis_note="内田さん本人の現地参加による確認。",
        now=now,
    )


def add_firsthand_evidence(conn, occurrence_id, raw_note, *, url=None, event_date=None, uncertain=False, now=None):
    """Create one evidence_items row for Uchida-san's firsthand note and link it to the occurrence."""
    now = now or now_utc()
    evidence_id = stable_id("ev", "firsthand", occurrence_id, raw_note, event_date or "")
    _upsert_evidence_item(
        conn,
        evidence_id,
        platform=PLATFORM_PERSONAL_FIRSTHAND,
        evidence_type=EVIDENCE_TYPE_FIRSTHAND_ATTENDANCE,
        source_key=EVIDENCE_SOURCE_KEY,
        account_key=EVIDENCE_SOURCE_KEY,
        title="内田さん現地レポート",
        text_excerpt=raw_note,
        url=url,
        event_date=event_date,
        raw_json_extra={"uncertain": uncertain},
        now=now,
    )
    _link_occurrence_evidence(
        conn,
        occurrence_id,
        evidence_id,
        EVIDENCE_LINK_TARGET_FIRSTHAND_REPORT,
        confidence=0.7 if uncertain else 0.95,
        notes="内田さん本人の現地参加レポートを一次証拠として採用。",
    )
    return evidence_id


def upsert_occurrence_song(conn, occurrence_id, song_title_raw, evidence_id, *, uncertain=False, now=None):
    """Name-match song_title_raw against songs, then idempotently upsert occurrence_songs."""
    return _upsert_occurrence_song(
        conn,
        occurrence_id,
        song_title_raw,
        evidence_id,
        role="result",
        evidence_status="observed",
        basis_key="personal_firsthand",
        evidence_note="内田さん本人が現地で聴いた曲目。",
        uncertain=uncertain,
        now=now,
    )
