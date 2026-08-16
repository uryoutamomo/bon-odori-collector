"""Source-agnostic core engine for turning a field report into master RDB rows.

Shared by firsthand_report_helpers.py (Uchida-san's own attendance) and
official_notice_report_helpers.py (flyers/notice boards/回覧板 photographed
or shared with koto). None of these functions assume a particular evidence
platform/type or occurrence_songs role/evidence_status -- callers supply
those, keeping the domain-specific vocabulary out of this module.
"""

import sqlite3
from datetime import date
from difflib import SequenceMatcher

from event_model.event_state_axes import update_occurrence_state_axes
from master_rdb.master_db import json_text, normalize_text, now_utc, stable_id


FUZZY_MATCH_MIN_SCORE = 0.45


def _rows(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def _fuzzy_score(normalized_hint, normalized_candidate):
    if not normalized_hint or not normalized_candidate:
        return 0.0
    score = SequenceMatcher(None, normalized_hint, normalized_candidate).ratio()
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
    """Reuse one exact name/address match, else create a venue.

    Returns {"status": "reused"|"created"|"ambiguous", "venue_id": str|None, "candidates": [...]}.
    Multiple exact rows are ambiguous (possible for duplicate NULL addresses in SQLite).
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

    # Venue identity must be exact.  Similar names are common (e.g. parks with
    # a district prefix); automatically reusing a fuzzy candidate can attach an
    # occurrence to a different physical place.

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
    series_id_override=None,
    now=None,
):
    """Create (or reuse) an event_series + event_occurrences row for a confirmed new event."""
    now = now or now_utc()
    normalized_series = normalize_text(series_name)
    series_key = normalized_series
    if series_id_override:
        existing_series = _rows(conn, "SELECT series_id FROM event_series WHERE series_id = ?", (series_id_override,))
        if not existing_series:
            raise ValueError(f"series_id_override not found: {series_id_override}")
        series_id = series_id_override
        series_created = False
    else:
        existing_series = _rows(conn, "SELECT series_id FROM event_series WHERE series_key = ?", (series_key,))
        if existing_series:
            series_id = existing_series[0]["series_id"]
            series_created = False
        else:
            series_id = stable_id("series", series_key)
            series_created = True
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
    return {"series_id": series_id, "series_created": series_created, "occurrence_id": occurrence_id, "occurrence_created": created}


# 開催回の確からしさの順位。下げること自体は正しい場合がある（根拠が覆った、疑わしいと分かった）
# ので禁じない。禁じるのは「呼び出し側が何も指定しなかったときの既定値」で静かに下がることだけ。
# 実データでは confirmed 253 / unknown 59 / high 49 なので、既定の "high" が確定済みの開催回を
# 上書きすると理由のない格下げになる（2026-08-15 の E2 実地試行で9件すべてに発生した）。
CONFIDENCE_RANK = {"unknown": 0, "medium": 1, "high": 2, "confirmed": 3}


def _kept_confidence(prior, incoming):
    """既定値での上書きから既存を守る。順位表に無い値（superseded など）は勝手に触らない。"""
    if incoming is None:
        return prior
    if prior is None:
        return incoming
    prior_rank = CONFIDENCE_RANK.get(prior)
    incoming_rank = CONFIDENCE_RANK.get(incoming)
    if prior_rank is None or incoming_rank is None:
        return prior
    return incoming if incoming_rank >= prior_rank else prior


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
    confidence_is_explicit=False,
    source_kind=None,
    detail_addendum=None,
    detail_replacement=None,
    date_basis_note=None,
    as_of_date=None,
    now=None,
):
    """Confirm venue/date for an existing occurrence, or just edit the detail note.

    venue_id and date_start are independently optional -- pass neither to only
    edit the detail (the "already confirmed, just fix the wording" case),
    pass either to also confirm date_status/lifecycle_status/confidence/source_kind
    and (if date_start is given) upsert an occurrence_dates row.

    detail は2通りの編集ができる。
    - detail_addendum: 既存の detail の末尾へ改行区切りで足す。同じ文が既にあれば
      何もしない（冪等）。事実を「付け足す」ためのもの。
    - detail_replacement: 既存の detail を丸ごと置き換える。公開文面の書き直しや、
      載せてはいけない記述の削除に使う。既に同じ文面なら何もしない（冪等）。

    両方を同時に渡すことはできない（どちらが最終形か決まらないため）。
    """
    if detail_addendum and detail_replacement:
        raise ValueError("detail_addendum と detail_replacement は同時に指定できない")
    now = now or now_utc()
    row = _rows(
        conn,
        "SELECT detail, current_event_state, date_start, date_end, confidence FROM event_occurrences WHERE occurrence_id = ?",
        (occurrence_id,),
    )
    if not row:
        raise ValueError(f"occurrence not found: {occurrence_id}")
    prior_detail = row[0]["detail"] or ""
    # 呼び出し側が確からしさを名指ししたなら、下げる指定もそのまま通す（下げる理由があるということ）。
    # 名指ししていないときだけ、既定値が既存を上書きしないように守る。
    if not confidence_is_explicit:
        confidence = _kept_confidence(row[0]["confidence"], confidence)

    new_detail = prior_detail
    if detail_addendum and detail_addendum not in prior_detail:
        new_detail = f"{prior_detail}\n{detail_addendum}".strip() if prior_detail else detail_addendum
    elif detail_replacement is not None:
        new_detail = detail_replacement.strip()

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
        # A confirmed schedule that has already ended must not stay in the
        # public "upcoming" category. Keep this decision at the shared
        # report helper so report authors only provide factual dates.
        schedule_end = effective_date_end if date_start is not None else (row[0]["date_end"] or row[0]["date_start"])
        if schedule_end:
            reference_date = date.fromisoformat(as_of_date) if as_of_date else date.today()
            current_event_state = "ended" if date.fromisoformat(schedule_end) < reference_date else "confirmed"
            update_occurrence_state_axes(conn, occurrence_id, current_event_state, "confirmed")
            if row[0]["current_event_state"] != current_event_state:
                changed_fields.append("current_event_state")
        if venue_id is not None:
            changed_fields.append("venue_id")
        if date_start is not None:
            changed_fields.append("date_start")
            effective_date_end = date_end or date_start
            # confirmed/ended are two lifecycle states of the one current-year
            # schedule cache. Reuse an exact legacy row so an ended transition
            # does not duplicate it, and remove only stale current-year rows.
            # Historical references intentionally use another date_type and
            # must survive schedule corrections.
            existing_date = conn.execute(
                """
                SELECT occurrence_date_id
                FROM occurrence_dates
                WHERE occurrence_id = ?
                  AND date_start = ?
                  AND date_end = ?
                  AND date_type IN ('confirmed', 'ended')
                ORDER BY occurrence_date_id
                LIMIT 1
                """,
                (occurrence_id, date_start, effective_date_end),
            ).fetchone()
            date_id = (
                existing_date[0]
                if existing_date
                else stable_id("date", occurrence_id, date_start, effective_date_end)
            )
            conn.execute(
                """
                DELETE FROM occurrence_dates
                WHERE occurrence_id = ?
                  AND date_type IN ('confirmed', 'ended')
                  AND occurrence_date_id <> ?
                """,
                (occurrence_id, date_id),
            )
            conn.execute(
                """
                INSERT INTO occurrence_dates (
                  occurrence_date_id, occurrence_id, date_start, date_end, date_type,
                  confidence, basis, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(occurrence_date_id) DO UPDATE SET
                  date_start=excluded.date_start,
                  date_end=excluded.date_end,
                  date_type=excluded.date_type,
                  confidence=excluded.confidence,
                  basis=excluded.basis
                """,
                (date_id, occurrence_id, date_start, effective_date_end, date_status, confidence, date_basis_note or "", now),
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


def link_resolved_occurrence_song(
    conn,
    occurrence_id,
    song_id,
    song_title,
    evidence_id,
    *,
    role,
    evidence_status,
    evidence_note,
    now=None,
):
    """Attach an already-resolved X claim without creating or rematching a song.

    An existing fact may be shared, but its identity and provenance are never
    overwritten. A collision therefore fails closed instead of borrowing the
    destructive ON CONFLICT behavior of the older report helper.
    """
    if (role, evidence_status) not in {
        ("setlist", "announced"),
        ("result", "observed"),
    }:
        raise ValueError("invalid X claim role/evidence_status mapping")
    now = now or now_utc()
    normalized = normalize_text(song_title)
    if not normalized:
        raise ValueError("song title is required")
    song = _rows(
        conn,
        "SELECT canonical_title, normalized_title, status FROM songs WHERE song_id = ?",
        (song_id,),
    )
    if not song:
        raise ValueError("resolved song does not exist")
    if song[0]["status"] not in {"active", "有効"}:
        raise ValueError("resolved song is not active")
    if song[0]["normalized_title"] != normalized:
        raise ValueError("resolved song title does not match the selected song")

    existing = _rows(
        conn,
        """
        SELECT occurrence_song_id, origin, song_id, song_title_raw, evidence_status
        FROM occurrence_songs
        WHERE occurrence_id = ? AND normalized_title = ? AND role = ?
        """,
        (occurrence_id, normalized, role),
    )
    created = not existing
    if existing:
        row = existing[0]
        if (
            row["song_id"] != song_id
            or normalize_text(row["song_title_raw"]) != normalized
            or row["evidence_status"] != evidence_status
        ):
            raise ValueError("existing occurrence song conflicts with resolved identity")
        occurrence_song_id = row["occurrence_song_id"]
    else:
        occurrence_song_id = stable_id("osong", occurrence_id, normalized, role)
        conn.execute(
            """
            INSERT INTO occurrence_songs (
              occurrence_song_id, origin, occurrence_id, song_id, song_title_raw,
              normalized_title, role, evidence_status, probability, confidence,
              source_count, evidence_count, inherited_from_year,
              first_observed_at, last_observed_at, notes, created_at, updated_at
            ) VALUES (?, 'observed_x_post', ?, ?, ?, ?, ?, ?, NULL, 'high',
                      1, 1, NULL, ?, ?, ?, ?, ?)
            """,
            (
                occurrence_song_id,
                occurrence_id,
                song_id,
                song_title,
                normalized,
                role,
                evidence_status,
                now,
                now,
                json_text({"source_kind": "x_song_claim", "evidence_id": evidence_id}),
                now,
                now,
            ),
        )
    conn.execute(
        """
        INSERT INTO occurrence_song_evidence_links (
          occurrence_song_id, evidence_id, link_status, confidence, notes
        ) VALUES (?, ?, 'accepted', 0.95, ?)
        ON CONFLICT(occurrence_song_id, evidence_id) DO UPDATE SET
          link_status='accepted', confidence=excluded.confidence, notes=excluded.notes
        """,
        (occurrence_song_id, evidence_id, evidence_note),
    )
    return {"occurrence_song_id": occurrence_song_id, "created": created}
