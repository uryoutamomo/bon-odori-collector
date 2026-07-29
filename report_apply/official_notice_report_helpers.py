"""Helpers for turning official/third-party notice-board flyers into master RDB rows.

Domain logic only (no CLI, no argparse). apply_official_notice_report.py is the
entry point. Thin wrappers around event_report_helpers.py's source-agnostic core
engine, fixed to the "public notice photographed/shared with koto" vocabulary
(platform/evidence_type/role/evidence_status distinct from firsthand_report_helpers.py).

Notice songs are announced setlists, not Uchida-san's own observation, so they
use role="setlist" / evidence_status="announced" (vs firsthand's "result"/"observed").
"""

from report_apply.event_report_helpers import (
    confirm_occurrence_schedule_venue,  # noqa: F401 (re-exported, source_kind passed through by callers)
    ensure_series_and_occurrence as _ensure_series_and_occurrence,
    ensure_venue,  # noqa: F401
    find_occurrence_candidates,  # noqa: F401
    find_venue_candidates,  # noqa: F401
    link_occurrence_evidence as _link_occurrence_evidence,
    upsert_evidence_item as _upsert_evidence_item,
    upsert_occurrence_song as _upsert_occurrence_song,
)


PLATFORM_WEB = "web"
EVIDENCE_TYPE_POSTER_POST = "poster_post"
SOURCE_KIND_OFFICIAL_CURRENT_YEAR = "official_current_year"
SOURCE_KIND_THIRD_PARTY_CURRENT_YEAR = "third_party_current_year"
EVIDENCE_LINK_TARGET_DATE_VENUE_PROGRAM = "date_venue_program"
SONG_ROLE_SETLIST = "setlist"
SONG_EVIDENCE_STATUS_ANNOUNCED = "announced"
NOTICE_BASIS_KEY = "official_notice"


def ensure_series_and_occurrence(
    conn,
    series_name,
    venue_id,
    event_year,
    date_start,
    date_end=None,
    *,
    source_kind=SOURCE_KIND_OFFICIAL_CURRENT_YEAR,
    source_url=None,
    detail=None,
    series_id_override=None,
    now=None,
):
    """Create (or reuse) an event_series + event_occurrences row for a notice-sourced new event."""
    return _ensure_series_and_occurrence(
        conn,
        series_name,
        venue_id,
        event_year,
        date_start,
        date_end,
        source_kind=source_kind,
        source_url=source_url,
        detail=detail,
        date_basis_note="公式掲示物・チラシで確認。",
        series_id_override=series_id_override,
        now=now,
    )


def upsert_notice_evidence(conn, evidence_id, *, title, text_excerpt, account_key=None, url=None, now=None):
    """Create or update the single evidence_items row shared by every event in a notice report."""
    return _upsert_evidence_item(
        conn,
        evidence_id,
        platform=PLATFORM_WEB,
        evidence_type=EVIDENCE_TYPE_POSTER_POST,
        source_key=account_key,
        account_key=account_key,
        title=title,
        text_excerpt=text_excerpt,
        url=url,
        event_date=None,
        now=now,
    )


def link_notice_evidence(conn, occurrence_id, evidence_id, *, confidence=0.95, notes=None):
    """Link the shared evidence to one occurrence. Call once per event in the report."""
    _link_occurrence_evidence(
        conn,
        occurrence_id,
        evidence_id,
        EVIDENCE_LINK_TARGET_DATE_VENUE_PROGRAM,
        confidence=confidence,
        notes=notes,
    )


def upsert_announced_song(conn, occurrence_id, song_title_raw, evidence_id, *, uncertain=False, now=None):
    """Name-match song_title_raw against songs, then idempotently upsert as an announced setlist entry."""
    return _upsert_occurrence_song(
        conn,
        occurrence_id,
        song_title_raw,
        evidence_id,
        role=SONG_ROLE_SETLIST,
        evidence_status=SONG_EVIDENCE_STATUS_ANNOUNCED,
        basis_key=NOTICE_BASIS_KEY,
        evidence_note="公式掲示物の告知曲目。",
        uncertain=uncertain,
        now=now,
    )
