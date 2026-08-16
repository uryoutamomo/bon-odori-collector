"""Deterministic E2-S identity candidates and packet contracts.

The LLM answers only two identity questions.  Candidate construction,
ordering, freezing, and eligibility remain machine-owned so the answer can be
validated again immediately before any RDB write.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import unicodedata
from datetime import datetime, timezone
from typing import Any

from build_x_extraction_packets import normalized_text
from master_rdb.master_db import stable_id


NONE = "none"
PACKET_VERSION = 1
PACKET_CALCULATION_VERSION = "x-song-identity-packet/v1"
MAX_CANDIDATES = 20


def material_text(value: str | None) -> str:
    """Use the E0X-S normalization contract for identity retrieval."""
    folded = unicodedata.normalize("NFKC", str(value or ""))
    return normalized_text(folded).replace("・", "").replace("ー", "")


def candidate_ids_sha256(candidate_ids: list[str]) -> str:
    """Hash only the ordered IDs; display metadata must never cause stale."""
    payload = json.dumps(candidate_ids, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _match_rank(hint: str, candidate: str) -> int | None:
    if not hint or not candidate:
        return None
    if hint == candidate:
        return 0
    if candidate.startswith(hint) or hint.startswith(candidate):
        return 1
    if candidate in hint or hint in candidate:
        return 2
    return None


def song_candidates(conn: sqlite3.Connection, song_name: str, limit: int = MAX_CANDIDATES) -> list[dict[str, Any]]:
    hint = material_text(song_name)
    if not hint:
        return []
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT s.song_id, s.canonical_title, s.status,
               s.canonical_title AS matched_text, NULL AS matched_alias,
               'canonical' AS matched_by
        FROM songs s
        UNION ALL
        SELECT s.song_id, s.canonical_title, s.status,
               a.alias AS matched_text, a.alias AS matched_alias,
               'alias' AS matched_by
        FROM song_aliases a
        JOIN songs s ON s.song_id = a.song_id
        """
    ).fetchall()
    best: dict[str, tuple[tuple[Any, ...], dict[str, Any]]] = {}
    for raw in rows:
        row = dict(raw)
        normalized = material_text(row["matched_text"])
        rank = _match_rank(hint, normalized)
        if rank is None:
            continue
        candidate = {
            "song_id": row["song_id"],
            "canonical_title": row["canonical_title"],
            "status": row["status"],
            "matched_by": row["matched_by"],
            "matched_text": row["matched_text"],
            "matched_alias": row["matched_alias"],
            "match_type": ("exact", "prefix", "substring")[rank],
        }
        # Prefer the strongest hit.  For an exact tie, show an exact alias over
        # the canonical spelling because it explains the observed variation.
        choice = (rank, 0 if row["matched_by"] == "alias" else 1, normalized, row["matched_text"])
        if row["song_id"] not in best or choice < best[row["song_id"]][0]:
            best[row["song_id"]] = (choice, candidate)
    ordered = sorted(best.values(), key=lambda item: (item[0][0], item[1]["song_id"]))
    return [candidate for _choice, candidate in ordered[:limit]]


def _date_sort_value(value: str | None) -> int:
    if not value:
        return 0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).toordinal()
    except ValueError:
        try:
            return datetime.fromisoformat(f"{value}T00:00:00+00:00").toordinal()
        except ValueError:
            return 0


def occurrence_candidates(
    conn: sqlite3.Connection, event_name: str | None, limit: int = MAX_CANDIDATES
) -> list[dict[str, Any]]:
    hint = material_text(event_name)
    if not hint:
        return []
    conn.row_factory = sqlite3.Row
    occurrences = conn.execute(
        """
        SELECT o.occurrence_id, o.series_id, o.display_name, o.date_start,
               o.date_end, o.lifecycle_status, s.canonical_name AS series_name
        FROM event_occurrences o
        JOIN event_series s ON s.series_id = o.series_id
        WHERE o.lifecycle_status != 'merged'
        """
    ).fetchall()
    aliases: dict[str, list[str]] = {}
    for row in conn.execute("SELECT series_id, alias FROM event_series_aliases"):
        aliases.setdefault(row["series_id"], []).append(row["alias"])

    ranked: list[tuple[int, int, str, dict[str, Any]]] = []
    for raw in occurrences:
        row = dict(raw)
        names = [
            ("series", row["series_name"], None),
            ("occurrence", row["display_name"], None),
            *(("alias", alias, alias) for alias in aliases.get(row["series_id"], [])),
        ]
        hits: list[tuple[tuple[Any, ...], tuple[str, str, str | None]]] = []
        for matched_by, matched_text, matched_alias in names:
            normalized = material_text(matched_text)
            rank = _match_rank(hint, normalized)
            if rank is not None:
                hits.append(((rank, 0 if matched_by == "alias" else 1, normalized, matched_text),
                             (matched_by, matched_text, matched_alias)))
        if not hits:
            continue
        choice, match = min(hits, key=lambda item: item[0])
        rank = choice[0]
        candidate = {
            **row,
            "matched_by": match[0],
            "matched_text": match[1],
            "matched_alias": match[2],
            "match_type": ("exact", "prefix", "substring")[rank],
        }
        ranked.append((rank, -_date_sort_value(row["date_start"]), row["occurrence_id"], candidate))
    ranked.sort(key=lambda item: item[:3])
    return [candidate for *_rank, candidate in ranked[:limit]]


def candidate_hashes(song_rows: list[dict[str, Any]], occurrence_rows: list[dict[str, Any]]) -> dict[str, str]:
    return {
        "song_candidate_set_sha256": candidate_ids_sha256([row["song_id"] for row in song_rows]),
        "occurrence_candidate_set_sha256": candidate_ids_sha256(
            [row["occurrence_id"] for row in occurrence_rows]
        ),
    }


def observation_sha256(observation: dict[str, Any]) -> str:
    payload = json.dumps(observation, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def packet_id(observation_id: str, song_hash: str, occurrence_hash: str) -> str:
    return stable_id(
        "xspacket", observation_id, song_hash, occurrence_hash, PACKET_CALCULATION_VERSION
    )


def state_rows(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(state, dict):
        return {}
    rows = state.get("observations")
    # Accept a wrapper used by early local prototypes, but the v1 sidecar is a
    # direct observation_id -> state-row mapping.
    return rows if isinstance(rows, dict) else state


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def is_eligible(state_row: dict[str, Any] | None, when: datetime) -> bool:
    if not state_row:
        return True
    outcome = state_row.get("outcome")
    if outcome == "applied":
        return False
    if outcome == "deferred":
        next_at = parse_timestamp(state_row.get("next_eligible_at"))
        return next_at is None or next_at <= when
    # stale is intentionally immediate.  issue is also re-issued so a corrected
    # answer does not require hand-editing the observation ledger.
    return True
