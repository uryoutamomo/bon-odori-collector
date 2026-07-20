"""Source-agnostic core engine for turning a field report into master RDB rows.

Shared by firsthand_report_helpers.py (Uchida-san's own attendance) and
official_notice_report_helpers.py (flyers/notice boards/回覧板 photographed
or shared with koto). None of these functions assume a particular evidence
platform/type or occurrence_songs role/evidence_status -- callers supply
those, keeping the domain-specific vocabulary out of this module.
"""

import sqlite3
from difflib import SequenceMatcher

from event_state_axes import axes_from_legacy_occurrence, update_occurrence_state_axes
from master_db import json_text, normalize_text, now_utc, stable_id


FUZZY_MATCH_MIN_SCORE = 0.45
FUZZY_SUBSTRING_SCORE_FLOOR = 0.92


def _rows(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def _fuzzy_score(normalized_hint, normalized_candidate):
    if not normalized_hint or not normalized_candidate:
        return 0.0
    score = SequenceMatcher(None, normalized_hint, normalized_candidate).ratio()
    if normalized_hint in normalized_candidate or normalized_candidate in normalized_hint:
        score = max(score, FUZZY_SUBSTRING_SCORE_FLOOR)
    return score


def find_venue_candidates(conn, venue_name_hint, area_hint=None, limit=8):
    """Fuzzy-match venue_name_hint against venues + venue_aliases."""
    normalized_hint = normalize_text(venue_name_hint)
    if not normalized_hint:
        return []
    canonical_rows = _rows(
        conn,
        """
        SELECT venue_id, canonical_name, normalized_name, area, address, latitude, longitude,
               'canonical' AS matched_by, '' AS matched_alias
        FROM venues
        WHERE review_status = 'active'
        """,
    )
    alias_rows = _rows(
        conn,
        """
        SELECT v.venue_id, v.canonical_name, v.normalized_name, v.area, v.address,
               v.latitude, v.longitude, 'alias' AS matched_by, a.alias AS matched_alias
        FROM venue_aliases a
        JOIN venues v ON v.venue_id = a.venue_id
        WHERE v.review_status = 'active'
        """,
    )
    candidates = []
    for row in canonical_rows + alias_rows:
        candidate_key = row["matched_alias"] and normalize_text(row["matched_alias"]) or row["normalized_name"]
        score = _fuzzy_score(normalized_hint, candidate_key)
        if score < FUZZY_MATCH_MIN_SCORE:
            continue
        if area_hint and row["area"] and area_hint not in row["area"]:
            score *= 0.9
        candidates.append({**row, "match_score": round(score, 3)})
    deduped = {}
    for row in sorted(candidates, key=lambda r: -r["match_score"]):
        deduped.setdefault(row["venue_id"], row)
    ordered = sorted(deduped.values(), key=lambda r: (-r["match_score"], r["canonical_name"]))
    return ordered[:limit]


def find_occurrence_candidates(conn, event_name_hint, venue_name_hint=None, event_year=None, limit=8):
    """Fuzzy-match event_name_hint (+ optional venue/year) against event_occurrences."""
    normalized_hint = normalize_text(event_name_hint)
    if not normalized_hint:
        return []
    query = """
        SELECT o.occurrence_id, o.series_id, o.event_year, o.display_name,
               o.venue_id, o.date_start, o.date_end, o.date_status,
               o.lifecycle_status, o.confidence, o.source_kind,
               v.canonical_name AS venue_name, v.normalized_name AS venue_normalized_name,
               s.canonical_name AS series_name, s.normalized_name AS series_normalized_name
        FROM event_occurrences o
        JOIN event_series s ON s.series_id = o.series_id
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE o.lifecycle_status != 'merged'
    """
    params = []
    if event_year is not None:
        query += " AND o.event_year = ?"
        params.append(event_year)
    candidates = []
    for row in _rows(conn, query, params):
        name_score = max(
            _fuzzy_score(normalized_hint, row["series_normalized_name"] or ""),
            _fuzzy_score(normalized_hint, normalize_text(row["display_name"] or "")),
        )
        if name_score < FUZZY_MATCH_MIN_SCORE:
            continue
        score = name_score
        if venue_name_hint:
            venue_score = _fuzzy_score(normalize_text(venue_name_hint), row["venue_normalized_name"] or "")
            score = (name_score + venue_score) / 2 if venue_score >= FUZZY_MATCH_MIN_SCORE else name_score * 0.7
        candidates.append({**row, "match_score": round(score, 3)})
    candidates.sort(key=lambda r: (-r["match_score"], r["display_name"]))
    return candidates[:limit]


def ensure_venue(conn, name, *, area=None, address=None, access=None, source_url=None, now=None):
    """Reuse an exact-match venue, refuse to guess on ambiguous matches, else create one.

    Returns {"status": "reused"|"created"|"ambiguous", "venue_id": str|None, "candidates": [...]}.
    Never auto-creates a venue when multiple fuzzy candidates exist, to avoid duplicate venues.
    """
    now = now or now_utc()
    normalized = normalize_text(name)
    exact = _rows(
        conn,
        "SELECT venue_id, canonical_name FROM venues WHERE normalized_name = ? AND COALESCE(address, '') = ?",
        (normalized, address or ""),
    )
    if len(exact) == 1:
        return {"status": "reused", "venue_id": exact[0]["venue_id"], "candidates": []}
    if len(exact) > 1:
        return {"status": "ambiguous", "venue_id": None, "candidates": exact}

    candidates = find_venue_candidates(conn, name, area_hint=area)
    high_confidence = [c for c in candidates if c["match_score"] >= FUZZY_SUBSTRING_SCORE_FLOOR]
    if len(high_confidence) > 1:
        return {"status": "ambiguous", "venue_id": None, "candidates": high_confidence}
    if len(high_confidence) == 1:
        return {"status": "reused", "venue_id": high_confidence[0]["venue_id"], "candidates": []}

    venue_id = stable_id("venue", name, address or "")
    conn.execute(
        """
        INSERT INTO venues (
          venue_id, origin, canonical_name, normalized_name, area, address,
          access, scale, public_intro, past_memo, source_url, latitude, longitude,
          review_status, created_at, updated_at
        ) VALUES (?, 'curated', ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, NULL, NULL, 'active', ?, ?)
        ON CONFLICT(normalized_name, address) DO UPDATE SET
          canonical_name=excluded.canonical_name,
          area=COALESCE(venues.area, excluded.area),
          access=COALESCE(venues.access, excluded.access),
          source_url=COALESCE(venues.source_url, excluded.source_url),
          review_status='active',
          updated_at=excluded.updated_at
        """,
        (venue_id, name, normalized, area, address, access, source_url, now, now),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO venue_aliases (venue_id, alias, normalized_alias, source, confidence)
        VALUES (?, ?, ?, 'canonical', 'manual')
        """,
        (venue_id, name, normalized),
    )
    return {"status": "created", "venue_id": venue_id, "candidates": []}


def ensure_series_and_occurrence(
    conn,
    series_name,
    venue_id,
    event_year,
    date_start,
    date_end=None,
    *,
    source_kind,
    source_url=None,
    detail=None,
    date_basis_note=None,
    now=None,
):
    """Create (or reuse) an event_series + event_occurrences row for a confirmed new event."""
    now = now or now_utc()
    normalized_series = normalize_text(series_name)
    series_key = normalized_series
    existing_series = _rows(conn, "SELECT series_id FROM event_series WHERE series_key = ?", (series_key,))
    if existing_series:
        series_id = existing_series[0]["series_id"]
    else:
        series_id = stable_id("series", series_key)
        conn.execute(
            """
            INSERT INTO event_series (
              series_id, origin, series_key, canonical_name, normalized_name,
              usual_venue_id, area, program_type, annual_months_json,
              schedule_rule_type, schedule_rule_detail, public_intro, source_url,
              status, created_at, updated_at
            ) VALUES (?, 'curated', ?, ?, ?, ?, NULL, 'bon_odori', '[]', NULL, NULL, NULL, ?, 'active', ?, ?)
            ON CONFLICT(series_id) DO NOTHING
            """,
            (series_id, series_key, series_name, normalized_series, venue_id, source_url, now, now),
        )

    existing_occurrence = _rows(
        conn,
        "SELECT occurrence_id, occurrence_sequence FROM event_occurrences WHERE series_id = ? AND event_year = ?",
        (series_id, event_year),
    )
    if existing_occurrence:
        occurrence_id = existing_occurrence[0]["occurrence_id"]
        sequence = existing_occurrence[0]["occurrence_sequence"]
        created = False
    else:
        sequence = 1
        occurrence_id = stable_id("occ", series_id, event_year, sequence)
        created = True

    conn.execute(
        """
        INSERT INTO event_occurrences (
          occurrence_id, origin, series_id, event_year, occurrence_sequence,
          display_name, venue_id, date_start, date_end, date_status,
          lifecycle_status, confidence, source_kind, source_url, detail,
          created_at, updated_at
        ) VALUES (?, 'curated', ?, ?, ?, ?, ?, ?, ?, 'confirmed', 'published', 'confirmed', ?, ?, ?, ?, ?)
        ON CONFLICT(series_id, event_year, occurrence_sequence) DO UPDATE SET
          venue_id=excluded.venue_id,
          date_start=excluded.date_start,
          date_end=excluded.date_end,
          date_status='confirmed',
          source_kind=excluded.source_kind,
          source_url=COALESCE(event_occurrences.source_url, excluded.source_url),
          detail=COALESCE(event_occurrences.detail, excluded.detail),
          updated_at=excluded.updated_at
        """,
        (
            occurrence_id,
            series_id,
            event_year,
            sequence,
            series_name,
            venue_id,
            date_start,
            date_end or date_start,
            source_kind,
            source_url,
            detail,
            now,
            now,
        ),
    )
    update_occurrence_state_axes(conn, occurrence_id, "confirmed", "confirmed")
    date_id = stable_id("date", occurrence_id, date_start, date_end or date_start)
    conn.execute(
        """
        INSERT INTO occurrence_dates (
          occurrence_date_id, occurrence_id, date_start, date_end, date_type,
          confidence, basis, created_at
        ) VALUES (?, ?, ?, ?, 'confirmed', 'confirmed', ?, ?)
        ON CONFLICT(occurrence_date_id) DO UPDATE SET
          date_start=excluded.date_start,
          date_end=excluded.date_end
        """,
        (date_id, occurrence_id, date_start, date_end or date_start, date_basis_note or "", now),
    )
    return {"series_id": series_id, "occurrence_id": occurrence_id, "occurrence_created": created}


def confirm_occurrence_schedule_venue(
    conn,
    occurrence_id,
    *,
    venue_id=None,
    date_start=None,
    date_end=None,
    date_status="confirmed",
    lifecycle_status="published",
    confidence="high",
    source_kind=None,
    detail_addendum=None,
    date_basis_note=None,
    now=None,
):
    """Confirm venue/date for an existing occurrence, or just append a detail note.

    venue_id and date_start are independently optional -- pass neither to only
    append detail_addendum (the "already confirmed, just add a note" case),
    pass either to also confirm date_status/lifecycle_status/confidence/source_kind
    and (if date_start is given) upsert an occurrence_dates row.
    detail_addendum is appended to the existing detail with a newline, idempotently
    (skipped if the exact text is already present).
    """
    now = now or now_utc()
    row = _rows(conn, "SELECT detail FROM event_occurrences WHERE occurrence_id = ?", (occurrence_id,))
    if not row:
        raise ValueError(f"occurrence not found: {occurrence_id}")
    prior_detail = row[0]["detail"] or ""

    new_detail = prior_detail
    if detail_addendum and detail_addendum not in prior_detail:
        new_detail = f"{prior_detail}\n{detail_addendum}".strip() if prior_detail else detail_addendum

    changed_fields = []
    if venue_id is not None or date_start is not None:
        # If date_start is being set, date_end must land in event_occurrences the
        # same way it lands in occurrence_dates below (date_end or date_start) --
        # otherwise audit_master_rdb's date_cache_mismatch check flags a false
        # positive (event_occurrences.date_end=NULL vs occurrence_dates.date_end=date_start).
        effective_date_end = (date_end or date_start) if date_start is not None else date_end
        conn.execute(
            """
            UPDATE event_occurrences
            SET venue_id = COALESCE(?, venue_id),
                date_start = COALESCE(?, date_start),
                date_end = COALESCE(?, date_end),
                date_status = ?,
                lifecycle_status = ?,
                confidence = ?,
                source_kind = COALESCE(?, source_kind),
                detail = ?,
                updated_at = ?
            WHERE occurrence_id = ?
            """,
            (venue_id, date_start, effective_date_end, date_status, lifecycle_status, confidence, source_kind, new_detail, now, occurrence_id),
        )
        axes = axes_from_legacy_occurrence(
            {
                "event_year": str(date_start or "")[:4],
                "date_start": date_start,
                "date_status": date_status,
                "lifecycle_status": lifecycle_status,
                "source_kind": source_kind,
                "source_url": "",
            }
        )
        update_occurrence_state_axes(
            conn,
            occurrence_id,
            axes["current_event_state"],
            axes["date_certainty_tier"],
        )
        if venue_id is not None:
            changed_fields.append("venue_id")
        if date_start is not None:
            changed_fields.append("date_start")
            date_id = stable_id("date", occurrence_id, date_start, date_end or date_start)
            conn.execute(
                """
                INSERT INTO occurrence_dates (
                  occurrence_date_id, occurrence_id, date_start, date_end, date_type,
                  confidence, basis, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(occurrence_date_id) DO UPDATE SET
                  date_start=excluded.date_start,
                  date_end=excluded.date_end
                """,
                (date_id, occurrence_id, date_start, date_end or date_start, date_status, confidence, date_basis_note or "", now),
            )
        if new_detail != prior_detail:
            changed_fields.append("detail")
    elif new_detail != prior_detail:
        conn.execute(
            "UPDATE event_occurrences SET detail = ?, updated_at = ? WHERE occurrence_id = ?",
            (new_detail, now, occurrence_id),
        )
        changed_fields.append("detail")

    return {"occurrence_id": occurrence_id, "changed_fields": changed_fields}


def upsert_evidence_item(
    conn,
    evidence_id,
    *,
    platform,
    evidence_type,
    source_key,
    account_key=None,
    title=None,
    text_excerpt,
    url=None,
    event_date=None,
    raw_json_extra=None,
    now=None,
):
    """Create or update one evidence_items row. Does not link it to any occurrence."""
    now = now or now_utc()
    conn.execute(
        """
        INSERT INTO evidence_items (
          evidence_id, platform, evidence_type, source_key, source_id, account_key,
          title, text_excerpt, url, published_at, observed_at, detected_event_date,
          raw_status, raw_json
        ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, 'reviewed', ?)
        ON CONFLICT(evidence_id) DO UPDATE SET
          text_excerpt=excluded.text_excerpt,
          url=COALESCE(evidence_items.url, excluded.url),
          observed_at=excluded.observed_at,
          detected_event_date=excluded.detected_event_date
        """,
        (
            evidence_id,
            platform,
            evidence_type,
            source_key,
            account_key,
            title,
            text_excerpt,
            url,
            now,
            now,
            event_date,
            json_text(raw_json_extra or {}),
        ),
    )
    return evidence_id


def link_occurrence_evidence(conn, occurrence_id, evidence_id, target, *, confidence=0.95, notes=None):
    """Link one evidence_items row to one occurrence. Safe to call multiple times for
    the same evidence_id against different occurrence_ids (shared-evidence case)."""
    conn.execute(
        """
        INSERT INTO occurrence_evidence_links (
          occurrence_id, evidence_id, target, link_status, confidence, notes
        ) VALUES (?, ?, ?, 'accepted', ?, ?)
        ON CONFLICT(occurrence_id, evidence_id, target) DO UPDATE SET
          confidence=excluded.confidence,
          notes=excluded.notes
        """,
        (occurrence_id, evidence_id, target, confidence, notes),
    )


def upsert_occurrence_song(
    conn,
    occurrence_id,
    song_title_raw,
    evidence_id,
    *,
    role,
    evidence_status,
    basis_key,
    evidence_note,
    uncertain=False,
    now=None,
):
    """Name-match song_title_raw against songs, then idempotently upsert occurrence_songs."""
    now = now or now_utc()
    normalized = normalize_text(song_title_raw)
    existing_song = _rows(conn, "SELECT song_id FROM songs WHERE normalized_title = ?", (normalized,))
    song_id = existing_song[0]["song_id"] if existing_song else stable_id("song", song_title_raw)
    if not existing_song:
        conn.execute(
            """
            INSERT INTO songs (
              song_id, canonical_title, normalized_title, category, status,
              prior_tier, target_area, evidence_count, source_url, memo,
              created_at, updated_at
            ) VALUES (?, ?, ?, NULL, 'active', NULL, NULL, 1, NULL, NULL, ?, ?)
            ON CONFLICT(normalized_title) DO NOTHING
            """,
            (song_id, song_title_raw, normalized, now, now),
        )
        refetch = _rows(conn, "SELECT song_id FROM songs WHERE normalized_title = ?", (normalized,))
        song_id = refetch[0]["song_id"]

    confidence = "medium" if uncertain else "high"
    occurrence_song_id = stable_id("osong", occurrence_id, normalized, role)
    conn.execute(
        """
        INSERT INTO occurrence_songs (
          occurrence_song_id, origin, occurrence_id, song_id, song_title_raw,
          normalized_title, role, evidence_status, probability, confidence,
          source_count, evidence_count, inherited_from_year,
          first_observed_at, last_observed_at, notes, created_at, updated_at
        ) VALUES (?, 'curated', ?, ?, ?, ?, ?, ?, NULL, ?, 1, 1, NULL, ?, ?, ?, ?, ?)
        ON CONFLICT(occurrence_id, normalized_title, role) DO UPDATE SET
          song_id=excluded.song_id,
          song_title_raw=excluded.song_title_raw,
          confidence=excluded.confidence,
          last_observed_at=excluded.last_observed_at,
          updated_at=excluded.updated_at
        """,
        (
            occurrence_song_id,
            occurrence_id,
            song_id,
            song_title_raw,
            normalized,
            role,
            evidence_status,
            confidence,
            now,
            now,
            json_text({"basis": basis_key, "evidence_id": evidence_id}),
            now,
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO occurrence_song_evidence_links (
          occurrence_song_id, evidence_id, link_status, confidence, notes
        ) VALUES (?, ?, 'accepted', ?, ?)
        ON CONFLICT(occurrence_song_id, evidence_id) DO UPDATE SET
          confidence=excluded.confidence
        """,
        (occurrence_song_id, evidence_id, 0.7 if uncertain else 0.95, evidence_note),
    )
    return {"song_id": song_id, "occurrence_song_id": occurrence_song_id}
