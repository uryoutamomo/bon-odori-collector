"""Finite Master RDB actions for frozen review-backlog decisions.

Raw observations are preserved.  Song identity decisions only change the
canonical link/projection state, while rejected titles remain in the observed
layer with an explicit rejection status.  YouTube judgments are recorded as
reviewed evidence records but never invent an occurrence or song link.
"""

from __future__ import annotations

import json
import hashlib
import sqlite3

from master_rdb.master_db import json_text, normalize_text, stable_id


CHANGE_TYPES = {
    "merge_song_identity",
    "retract_song_identity",
    "retract_occurrence_song",
    "register_song_candidate",
    "record_youtube_review_decision",
}
SONG_STATUSES = {"active", "candidate"}
YOUTUBE_DECISIONS = {"accepted", "rejected"}
SCOPED_RETRACTION_OBSERVED_MUTABLE_COLUMNS = {
    "occurrence_song_id",
    "matched_song_id",
    "match_status",
    "updated_at",
}


def _required(request, field, errors, prefix):
    if not request.get(field):
        errors.append(f"{prefix}: missing required field: {field}")


def _snapshot_sha256(value):
    """Hash a review-time snapshot without relying on SQLite row ordering."""
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _is_sha256(value):
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value.lower())


def evidence_snapshot(row):
    """Return the content-addressed fields a scoped retraction must freeze."""
    return {key: row[key] for key in row.keys()}


def observed_snapshot(row):
    """Return the row identity and state that a scoped retraction may change."""
    return {
        "observed_occurrence_song_id": row["observed_occurrence_song_id"],
        "observed_occurrence_id": row["observed_occurrence_id"],
        "occurrence_song_id": row["occurrence_song_id"],
        "raw_song_title": row["raw_song_title"],
        "normalized_title": row["normalized_title"],
        "matched_song_id": row["matched_song_id"],
        "match_status": row["match_status"],
        "role": row["role"],
        "evidence_status": row["evidence_status"],
        "source_payload_sha256": _snapshot_sha256(row["source_payload_json"]),
        "row_snapshot_sha256": _snapshot_sha256(
            {key: row[key] for key in row.keys()}
        ),
        "retained_fields_sha256": _snapshot_sha256(
            {
                key: row[key]
                for key in row.keys()
                if key not in SCOPED_RETRACTION_OBSERVED_MUTABLE_COLUMNS
            }
        ),
    }


def _validate_scoped_snapshot(entries, required_keys, errors, prefix):
    if not isinstance(entries, list) or not entries:
        errors.append(f"{prefix}: must be a non-empty list")
        return
    seen = set()
    for index, entry in enumerate(entries):
        item_prefix = f"{prefix}[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{item_prefix}: must be an object")
            continue
        for key in required_keys:
            if key not in entry:
                errors.append(f"{item_prefix}: missing required field: {key}")
        identity = entry.get(required_keys[0])
        if not identity:
            errors.append(f"{item_prefix}: {required_keys[0]} must not be empty")
        if identity in seen:
            errors.append(f"{item_prefix}: duplicate {required_keys[0]}: {identity!r}")
        seen.add(identity)
        for key in (
            "snapshot_sha256",
            "link_snapshot_sha256",
            "source_payload_sha256",
            "row_snapshot_sha256",
            "retained_fields_sha256",
        ):
            if key in entry and not _is_sha256(entry[key]):
                errors.append(f"{item_prefix}: {key} must be a SHA-256 hex digest")


def validate_request(request, errors, prefix):
    change_type = request.get("change_type")
    if change_type == "merge_song_identity":
        _required(request, "raw_song_name", errors, prefix)
        _required(request, "target_song_name", errors, prefix)
        if request.get("target_status") not in SONG_STATUSES:
            errors.append(f"{prefix}: target_status must be one of {sorted(SONG_STATUSES)}")
    elif change_type == "retract_song_identity":
        _required(request, "raw_song_name", errors, prefix)
    elif change_type == "retract_occurrence_song":
        for field in ("occurrence_id", "occurrence_song_id", "raw_song_name"):
            _required(request, field, errors, prefix)
        _validate_scoped_snapshot(
            request.get("expected_evidence"),
            ("evidence_id", "url", "snapshot_sha256", "link_snapshot_sha256"),
            errors,
            f"{prefix}.expected_evidence",
        )
        _validate_scoped_snapshot(
            request.get("expected_observed"),
            (
                "observed_occurrence_song_id",
                "observed_occurrence_id",
                "occurrence_song_id",
                "raw_song_title",
                "normalized_title",
                "match_status",
                "role",
                "evidence_status",
                "source_payload_sha256",
            "row_snapshot_sha256",
            "retained_fields_sha256",
            ),
            errors,
            f"{prefix}.expected_observed",
        )
        for index, entry in enumerate(request.get("expected_observed") or []):
            if isinstance(entry, dict) and "matched_song_id" not in entry:
                errors.append(
                    f"{prefix}.expected_observed[{index}]: missing required field: matched_song_id"
                )
        if not _is_sha256(request.get("expected_canonical_sha256")):
            errors.append(f"{prefix}: expected_canonical_sha256 must be a SHA-256 hex digest")
        review = request.get("review")
        if not isinstance(review, dict):
            errors.append(f"{prefix}.review: must be an object")
        else:
            _required(review, "reason", errors, f"{prefix}.review")
            _required(review, "source_context", errors, f"{prefix}.review")
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


def _scoped_evidence(conn, occurrence_song_id):
    rows = conn.execute(
        """
        SELECT e.*, link.occurrence_song_id AS link_occurrence_song_id,
               link.evidence_id AS link_evidence_id, link.link_status AS link_status,
               link.confidence AS link_confidence, link.notes AS link_notes
        FROM occurrence_song_evidence_links AS link
        JOIN evidence_items AS e ON e.evidence_id = link.evidence_id
        WHERE link.occurrence_song_id = ?
        ORDER BY e.evidence_id
        """,
        (occurrence_song_id,),
    ).fetchall()
    return [
        {
            "evidence_id": evidence["evidence_id"],
            "url": evidence["url"],
            "snapshot_sha256": _snapshot_sha256(evidence),
            "link_snapshot_sha256": _snapshot_sha256(
                {
                    "occurrence_song_id": row["link_occurrence_song_id"],
                    "evidence_id": row["link_evidence_id"],
                    "link_status": row["link_status"],
                    "confidence": row["link_confidence"],
                    "notes": row["link_notes"],
                }
            ),
        }
        for row in rows
        for evidence in (evidence_snapshot({
            key: row[key] for key in row.keys() if not key.startswith("link_")
        }),)
    ]


def _scoped_observed(conn, occurrence_song_id):
    rows = conn.execute(
        """
        SELECT * FROM observed_occurrence_songs
        WHERE occurrence_song_id = ?
        ORDER BY observed_occurrence_song_id
        """,
        (occurrence_song_id,),
    ).fetchall()
    return [observed_snapshot(row) for row in rows]


def _require_exact_snapshot(name, expected, actual):
    if expected != actual:
        raise ValueError(
            f"scoped retraction refused: {name} changed since review "
            f"(expected {len(expected)}, actual {len(actual)})"
        )


def apply_retract_occurrence_song(conn, request, now):
    """Retract one reviewed canonical row, never a title across every occurrence.

    Every linked evidence item and observed row is supplied by the review request.
    Comparing whole sets before deleting makes newly collected evidence, changed source
    content, and partial selections fail closed.
    """
    # Lock before reading: snapshot comparison and the destructive DML must see
    # one write-serialized database state.  Do not commit a caller transaction.
    if conn.in_transaction:
        # A caller may have opened a read-only explicit transaction.  This no-op
        # DML upgrades it to a writer without changing a row.
        conn.execute("UPDATE occurrence_songs SET updated_at = updated_at WHERE 0")
    else:
        conn.execute("BEGIN IMMEDIATE")

    previous_row_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        canonical = conn.execute(
            """
            SELECT * FROM occurrence_songs
            WHERE occurrence_song_id = ? AND occurrence_id = ?
            """,
            (request["occurrence_song_id"], request["occurrence_id"]),
        ).fetchone()
        if not canonical:
            raise ValueError("scoped retraction refused: occurrence_song_id does not belong to occurrence_id")
        if canonical["song_title_raw"] != request["raw_song_name"]:
            raise ValueError("scoped retraction refused: raw_song_name does not exactly match canonical row")
        if canonical["normalized_title"] != normalize_text(request["raw_song_name"]):
            raise ValueError("scoped retraction refused: raw_song_name normalization mismatch")
        if _snapshot_sha256({key: canonical[key] for key in canonical.keys()}) != request["expected_canonical_sha256"]:
            raise ValueError("scoped retraction refused: canonical row changed since review")

        _require_exact_snapshot(
            "evidence links",
            sorted(request["expected_evidence"], key=lambda item: item["evidence_id"]),
            _scoped_evidence(conn, canonical["occurrence_song_id"]),
        )
        _require_exact_snapshot(
            "observed rows",
            sorted(request["expected_observed"], key=lambda item: item["observed_occurrence_song_id"]),
            _scoped_observed(conn, canonical["occurrence_song_id"]),
        )
        occurrence_song_id = canonical["occurrence_song_id"]
        occurrence_id = canonical["occurrence_id"]
    finally:
        conn.row_factory = previous_row_factory

    observed_updated = conn.execute(
        """
        UPDATE observed_occurrence_songs
        SET matched_song_id = NULL,
            occurrence_song_id = NULL,
            match_status = 'rejected_llm_review',
            updated_at = ?
        WHERE occurrence_song_id = ?
        """,
        (now, occurrence_song_id),
    ).rowcount
    evidence_deleted = conn.execute(
        "DELETE FROM occurrence_song_evidence_links WHERE occurrence_song_id = ?",
        (occurrence_song_id,),
    ).rowcount
    canonical_deleted = conn.execute(
        "DELETE FROM occurrence_songs WHERE occurrence_song_id = ? AND occurrence_id = ?",
        (occurrence_song_id, occurrence_id),
    ).rowcount
    if canonical_deleted != 1:
        raise AssertionError("scoped retraction deleted an unexpected number of canonical rows")
    return {
        "request_id": request["request_id"],
        "change_type": request["change_type"],
        "occurrence_id": occurrence_id,
        "occurrence_song_id": occurrence_song_id,
        "observed_rows_marked_rejected": observed_updated,
        "evidence_links_retracted": evidence_deleted,
        "canonical_rows_retracted": canonical_deleted,
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
    "retract_occurrence_song": apply_retract_occurrence_song,
    "register_song_candidate": apply_register_song_candidate,
    "record_youtube_review_decision": apply_record_youtube_review_decision,
}


def apply_request(conn, request, now):
    return APPLIERS[request["change_type"]](conn, request, now)
