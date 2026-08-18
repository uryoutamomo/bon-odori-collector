"""Finite Master RDB actions for frozen review-backlog decisions.

Raw observations are preserved.  Song identity decisions only change the
canonical link/projection state, while rejected titles remain in the observed
layer with an explicit rejection status.  YouTube judgments are recorded as
reviewed evidence records but never invent an occurrence or song link.
"""

from __future__ import annotations

import json

from master_rdb.master_db import json_text, normalize_text, stable_id


CHANGE_TYPES = {
    "merge_song_identity",
    "retract_song_identity",
    "register_song_candidate",
    "record_youtube_review_decision",
}
SONG_STATUSES = {"active", "candidate"}
YOUTUBE_DECISIONS = {"accepted", "rejected"}


def _required(request, field, errors, prefix):
    if not request.get(field):
        errors.append(f"{prefix}: missing required field: {field}")


def validate_request(request, errors, prefix):
    change_type = request.get("change_type")
    if change_type == "merge_song_identity":
        _required(request, "raw_song_name", errors, prefix)
        _required(request, "target_song_name", errors, prefix)
        if request.get("target_status") not in SONG_STATUSES:
            errors.append(f"{prefix}: target_status must be one of {sorted(SONG_STATUSES)}")
    elif change_type == "retract_song_identity":
        _required(request, "raw_song_name", errors, prefix)
    elif change_type == "register_song_candidate":
        _required(request, "raw_song_name", errors, prefix)
        _required(request, "target_song_name", errors, prefix)
    elif change_type == "record_youtube_review_decision":
        _required(request, "source_key", errors, prefix)
        _required(request, "inbox_id", errors, prefix)
        _required(request, "source_payload_hash", errors, prefix)
        _required(request, "video_id", errors, prefix)
        _required(request, "video_url", errors, prefix)
        if request.get("decision") not in YOUTUBE_DECISIONS:
            errors.append(f"{prefix}: decision must be one of {sorted(YOUTUBE_DECISIONS)}")


def _song_by_identity(conn, song_id, normalized_title):
    if song_id:
        row = conn.execute(
            "SELECT song_id, canonical_title, normalized_title, status FROM songs WHERE song_id = ?",
            (song_id,),
        ).fetchone()
        if row:
            return row
    return conn.execute(
        "SELECT song_id, canonical_title, normalized_title, status FROM songs WHERE normalized_title = ?",
        (normalized_title,),
    ).fetchone()


def ensure_song(conn, request, now, *, force_candidate=False):
    title = request["target_song_name"]
    normalized = normalize_text(title)
    requested_id = request.get("target_song_id")
    row = _song_by_identity(conn, requested_id, normalized)
    if row:
        if normalize_text(row[1]) != normalized:
            raise ValueError(
                f"target song id {row[0]} points to {row[1]!r}, not {title!r}"
            )
        return {
            "song_id": row[0],
            "canonical_title": row[1],
            "normalized_title": row[2],
            "status": row[3],
            "created": False,
        }

    status = "candidate" if force_candidate else request.get("target_status", "active")
    prefix = "song_cand" if status == "candidate" else "song"
    song_id = requested_id or stable_id(prefix, normalized)
    conn.execute(
        """
        INSERT INTO songs(
          song_id, canonical_title, normalized_title, status, memo, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            song_id,
            title,
            normalized,
            status,
            "registered from frozen LLM review backlog decision",
            now,
            now,
        ),
    )
    return {
        "song_id": song_id,
        "canonical_title": title,
        "normalized_title": normalized,
        "status": status,
        "created": True,
    }


def add_alias(conn, song_id, alias, now):
    normalized = normalize_text(alias)
    canonical = conn.execute(
        "SELECT normalized_title FROM songs WHERE song_id = ?", (song_id,)
    ).fetchone()
    if not normalized or (canonical and canonical[0] == normalized):
        return False
    before = conn.total_changes
    conn.execute(
        """
        INSERT INTO song_aliases(song_id, alias, normalized_alias, source, confidence)
        VALUES (?, ?, ?, 'llm_review_backlog', 'reviewed')
        ON CONFLICT(song_id, normalized_alias) DO UPDATE SET
          alias=excluded.alias,
          source=excluded.source,
          confidence=excluded.confidence
        """,
        (song_id, alias, normalized),
    )
    return conn.total_changes > before


def _merge_occurrence_song_rows(conn, raw_normalized, target, now):
    source_rows = conn.execute(
        """
        SELECT occurrence_song_id, occurrence_id, role, song_id
        FROM occurrence_songs
        WHERE normalized_title = ?
        ORDER BY occurrence_song_id
        """,
        (raw_normalized,),
    ).fetchall()
    relinked = 0
    merged = 0
    for source in source_rows:
        source_id, occurrence_id, role, source_song_id = source
        if source_song_id == target["song_id"]:
            continue
        existing = conn.execute(
            """
            SELECT occurrence_song_id
            FROM occurrence_songs
            WHERE occurrence_id = ? AND role = ? AND occurrence_song_id != ?
              AND (song_id = ? OR normalized_title = ?)
            ORDER BY occurrence_song_id
            LIMIT 1
            """,
            (
                occurrence_id,
                role,
                source_id,
                target["song_id"],
                target["normalized_title"],
            ),
        ).fetchone()
        if existing:
            target_occurrence_song_id = existing[0]
            conn.execute(
                """
                INSERT INTO occurrence_song_evidence_links(
                  occurrence_song_id, evidence_id, link_status, confidence, notes
                )
                SELECT ?, evidence_id, link_status, confidence, notes
                FROM occurrence_song_evidence_links
                WHERE occurrence_song_id = ?
                ON CONFLICT(occurrence_song_id, evidence_id) DO UPDATE SET
                  confidence = MAX(confidence, excluded.confidence),
                  notes = COALESCE(notes, excluded.notes)
                """,
                (target_occurrence_song_id, source_id),
            )
            conn.execute(
                """
                UPDATE occurrence_songs
                SET source_count = source_count + COALESCE((
                      SELECT source_count FROM occurrence_songs WHERE occurrence_song_id = ?
                    ), 0),
                    evidence_count = (
                      SELECT COUNT(*) FROM occurrence_song_evidence_links
                      WHERE occurrence_song_id = ?
                    ),
                    updated_at = ?
                WHERE occurrence_song_id = ?
                """,
                (source_id, target_occurrence_song_id, now, target_occurrence_song_id),
            )
            conn.execute(
                "UPDATE observed_occurrence_songs SET occurrence_song_id = ?, updated_at = ? WHERE occurrence_song_id = ?",
                (target_occurrence_song_id, now, source_id),
            )
            conn.execute(
                "DELETE FROM occurrence_song_evidence_links WHERE occurrence_song_id = ?",
                (source_id,),
            )
            conn.execute(
                "DELETE FROM occurrence_songs WHERE occurrence_song_id = ?", (source_id,)
            )
            merged += 1
        else:
            conn.execute(
                """
                UPDATE occurrence_songs
                SET song_id = ?, song_title_raw = ?, normalized_title = ?, updated_at = ?
                WHERE occurrence_song_id = ?
                """,
                (
                    target["song_id"],
                    target["canonical_title"],
                    target["normalized_title"],
                    now,
                    source_id,
                ),
            )
            relinked += 1
    return len(source_rows), relinked, merged


def apply_merge_song_identity(conn, request, now):
    target = ensure_song(conn, request, now)
    raw_normalized = normalize_text(request["raw_song_name"])
    observed_updated = conn.execute(
        """
        UPDATE observed_occurrence_songs
        SET matched_song_id = ?, match_status = 'matched_song_llm_review', updated_at = ?
        WHERE normalized_title = ?
        """,
        (target["song_id"], now, raw_normalized),
    ).rowcount
    source_count, relinked, merged = _merge_occurrence_song_rows(
        conn, raw_normalized, target, now
    )
    alias_added = add_alias(conn, target["song_id"], request["raw_song_name"], now)
    return {
        "request_id": request["request_id"],
        "change_type": request["change_type"],
        "song_id": target["song_id"],
        "song_created": target["created"],
        "alias_added": alias_added,
        "observed_rows_updated": observed_updated,
        "occurrence_source_rows": source_count,
        "occurrence_rows_relinked": relinked,
        "occurrence_rows_merged": merged,
    }, []


def apply_retract_song_identity(conn, request, now):
    normalized = normalize_text(request["raw_song_name"])
    canonical_ids = [
        row[0]
        for row in conn.execute(
            "SELECT occurrence_song_id FROM occurrence_songs WHERE normalized_title = ?",
            (normalized,),
        )
    ]
    observed_updated = conn.execute(
        """
        UPDATE observed_occurrence_songs
        SET matched_song_id = NULL,
            occurrence_song_id = NULL,
            match_status = 'rejected_llm_review',
            updated_at = ?
        WHERE normalized_title = ?
        """,
        (now, normalized),
    ).rowcount
    for occurrence_song_id in canonical_ids:
        conn.execute(
            "UPDATE observed_occurrence_songs SET occurrence_song_id = NULL, updated_at = ? WHERE occurrence_song_id = ?",
            (now, occurrence_song_id),
        )
        conn.execute(
            "DELETE FROM occurrence_song_evidence_links WHERE occurrence_song_id = ?",
            (occurrence_song_id,),
        )
        conn.execute(
            "DELETE FROM occurrence_songs WHERE occurrence_song_id = ?",
            (occurrence_song_id,),
        )
    return {
        "request_id": request["request_id"],
        "change_type": request["change_type"],
        "observed_rows_marked_rejected": observed_updated,
        "canonical_rows_retracted": len(canonical_ids),
    }, []


def apply_register_song_candidate(conn, request, now):
    candidate_request = dict(request, target_status="candidate")
    target = ensure_song(conn, candidate_request, now, force_candidate=True)
    raw_normalized = normalize_text(request["raw_song_name"])
    observed_updated = conn.execute(
        """
        UPDATE observed_occurrence_songs
        SET matched_song_id = ?, match_status = 'candidate_song_llm_review', updated_at = ?
        WHERE normalized_title = ?
        """,
        (target["song_id"], now, raw_normalized),
    ).rowcount
    source_count, relinked, merged = _merge_occurrence_song_rows(
        conn, raw_normalized, target, now
    )
    alias_added = add_alias(conn, target["song_id"], request["raw_song_name"], now)
    return {
        "request_id": request["request_id"],
        "change_type": request["change_type"],
        "song_id": target["song_id"],
        "song_created": target["created"],
        "alias_added": alias_added,
        "observed_rows_updated": observed_updated,
        "occurrence_source_rows": source_count,
        "occurrence_rows_relinked": relinked,
        "occurrence_rows_merged": merged,
    }, []


def apply_record_youtube_review_decision(conn, request, now):
    evidence_id = stable_id(
        "evid", "review_backlog_youtube", request["source_key"]
    )
    payload = {
        "review_inbox_id": request["inbox_id"],
        "source_payload_hash": request["source_payload_hash"],
        "decision": request["decision"],
        "reason_detail": request.get("reason_detail") or "",
        "review_payload": request.get("review_payload") or {},
    }
    source = request.get("source") or {}
    conn.execute(
        """
        INSERT INTO evidence_items(
          evidence_id, platform, evidence_type, source_key, source_id, account_key,
          title, text_excerpt, url, published_at, observed_at, detected_event_date,
          raw_status, raw_json
        ) VALUES (?, 'youtube', 'reviewed_video_evidence', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(evidence_id) DO UPDATE SET
          source_key=excluded.source_key,
          source_id=excluded.source_id,
          account_key=excluded.account_key,
          title=excluded.title,
          text_excerpt=excluded.text_excerpt,
          url=excluded.url,
          published_at=excluded.published_at,
          observed_at=excluded.observed_at,
          detected_event_date=excluded.detected_event_date,
          raw_status=excluded.raw_status,
          raw_json=excluded.raw_json
        """,
        (
            evidence_id,
            request["source_key"],
            request["video_id"],
            source.get("channel_id"),
            source.get("title") or request["video_id"],
            request.get("reason_detail") or "",
            request["video_url"],
            source.get("published_at"),
            request.get("decided_at") or now,
            source.get("detected_event_date"),
            f"reviewed_{request['decision']}",
            json_text(payload),
        ),
    )
    return {
        "request_id": request["request_id"],
        "change_type": request["change_type"],
        "evidence_id": evidence_id,
        "review_decision": request["decision"],
        "canonical_fact_links_created": 0,
    }, []


APPLIERS = {
    "merge_song_identity": apply_merge_song_identity,
    "retract_song_identity": apply_retract_song_identity,
    "register_song_candidate": apply_register_song_candidate,
    "record_youtube_review_decision": apply_record_youtube_review_decision,
}


def apply_request(conn, request, now):
    return APPLIERS[request["change_type"]](conn, request, now)
