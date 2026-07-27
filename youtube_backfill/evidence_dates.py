"""Rules for deciding when a public event date may stand in for a video's date.

Most YouTube evidence carries its own date, read from the title or the
description.  When it does not, the matched public event still has one, and it
is tempting to reuse it.  That is only sound when the public date could
actually be the date the video depicts.

A video cannot show an event that had not happened yet when the video was
posted.  A 2025 recording matched to a series whose public occurrence is now
the 2026 edition would otherwise be filed as evidence for a date in the future.
"""

from __future__ import annotations


def _day(value: object) -> str:
    return str(value or "").strip()[:10]


def public_date_is_evidence_for_video(public_date: object, published_at: object) -> bool:
    """Return True when a public event date may be borrowed for this video."""

    public_day = _day(public_date)
    if not public_day:
        return False
    published_day = _day(published_at)
    if not published_day:
        # Without a publication date there is nothing to contradict, so the
        # match itself remains the only evidence.
        return True
    return public_day <= published_day


def borrowed_public_date(public_date: object, published_at: object) -> str:
    """Return the borrowable public date, or an empty string when unusable."""

    return _day(public_date) if public_date_is_evidence_for_video(public_date, published_at) else ""
