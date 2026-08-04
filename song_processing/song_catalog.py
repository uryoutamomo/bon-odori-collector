"""Read-only resolver for song names against the master RDB.

This is the P1 foundation for replacing the static-JSON "known song" lookup
(song_processing/bon_odori_songs.py: master_song_names(), which currently
treats all 743 unreviewed rows of data/rdb_song_review_source.json as known)
with a resolver backed by the accumulated ``songs`` / ``song_aliases`` tables.

SongCatalog never opens a database connection itself and never writes. The
caller is responsible for connecting (typically to a fetched snapshot of
data/bon_odori_master.sqlite) and passing the connection in.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum

from master_rdb.master_db import normalize_text

# Status values as they currently exist in the songs table (see
# data/bon_odori_master.sqlite). Anything not listed here maps to UNKNOWN
# rather than being folded into VERIFIED or REJECTED -- an unrecognized
# status string must never be silently treated as trustworthy.
_VERIFIED_STATUSES = {"active", "有効"}
_CANDIDATE_STATUSES = {"候補"}
_REJECTED_STATUSES = {"無効"}


class SongReviewState(str, Enum):
    VERIFIED = "verified"
    CANDIDATE = "candidate"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class SongMatchType(str, Enum):
    CANONICAL = "canonical"
    ALIAS = "alias"
    AMBIGUOUS_ALIAS = "ambiguous_alias"
    NONE = "none"


def _review_state_for_status(status: str | None) -> SongReviewState:
    value = str(status or "")
    if value in _VERIFIED_STATUSES:
        return SongReviewState.VERIFIED
    if value in _CANDIDATE_STATUSES:
        return SongReviewState.CANDIDATE
    if value in _REJECTED_STATUSES:
        return SongReviewState.REJECTED
    return SongReviewState.UNKNOWN


@dataclass(frozen=True)
class SongResolution:
    query: str
    normalized_query: str
    match_type: SongMatchType
    review_state: SongReviewState
    song_id: str | None
    canonical_title: str | None
    stored_status: str | None


class SongCatalog:
    """In-memory index over songs/song_aliases, built once from a connection.

    Construction reads the two tables exactly once (SELECT only) and never
    touches the connection again, so the resolver is safe to reuse across
    many resolve() calls without re-querying.
    """

    def __init__(
        self,
        canonical_by_norm: dict[str, tuple[str, str, str | None]],
        alias_index: dict[str, list[tuple[str, str, str | None]]],
    ) -> None:
        # canonical_by_norm: normalized_title -> (song_id, canonical_title, status)
        self._canonical_by_norm = canonical_by_norm
        # alias_index: normalized_alias -> [(song_id, canonical_title, status), ...]
        # kept as a list (not collapsed) so ambiguity is visible at resolve time.
        deduped: dict[str, list[tuple[str, str, str | None]]] = {}
        for norm, rows in alias_index.items():
            # Dedupe by song_id: the same song can register the same alias
            # more than once (e.g. via different sources), which must not
            # manufacture a false ambiguity.
            seen: dict[str, tuple[str, str, str | None]] = {}
            for song_id, canonical_title, status in rows:
                seen[song_id] = (song_id, canonical_title, status)
            deduped[norm] = list(seen.values())
        self._alias_index = deduped

    @classmethod
    def from_connection(cls, conn: sqlite3.Connection) -> "SongCatalog":
        canonical_by_norm: dict[str, tuple[str, str, str | None]] = {}
        for song_id, canonical_title, status in conn.execute(
            "SELECT song_id, canonical_title, status FROM songs ORDER BY song_id"
        ):
            norm = normalize_text(canonical_title)
            if not norm:
                continue
            # If two songs somehow normalize to the same canonical form,
            # keep the first seen deterministically (query is ORDER BY
            # song_id) rather than silently overwriting with the last one.
            canonical_by_norm.setdefault(norm, (song_id, canonical_title, status))

        alias_rows: dict[str, list[tuple[str, str, str | None]]] = {}
        for song_id, alias, canonical_title, status in conn.execute(
            """
            SELECT song_aliases.song_id, song_aliases.alias,
                   songs.canonical_title, songs.status
            FROM song_aliases
            JOIN songs ON songs.song_id = song_aliases.song_id
            ORDER BY song_aliases.normalized_alias, song_aliases.song_id
            """
        ):
            norm = normalize_text(alias)
            if not norm:
                continue
            alias_rows.setdefault(norm, []).append((song_id, canonical_title, status))

        return cls(canonical_by_norm, alias_rows)

    def resolve(self, value: str) -> SongResolution:
        query = str(value or "")
        normalized = normalize_text(query)
        if not normalized:
            return SongResolution(
                query=query,
                normalized_query=normalized,
                match_type=SongMatchType.NONE,
                review_state=SongReviewState.UNKNOWN,
                song_id=None,
                canonical_title=None,
                stored_status=None,
            )

        # Canonical exact match always wins over alias, even if the same
        # normalized string also happens to be registered as someone else's
        # alias (self-registration of a song's own title as its alias is
        # common in this dataset and must not create false ambiguity here).
        canonical_hit = self._canonical_by_norm.get(normalized)
        if canonical_hit is not None:
            song_id, canonical_title, status = canonical_hit
            return SongResolution(
                query=query,
                normalized_query=normalized,
                match_type=SongMatchType.CANONICAL,
                review_state=_review_state_for_status(status),
                song_id=song_id,
                canonical_title=canonical_title,
                stored_status=status,
            )

        alias_hits = self._alias_index.get(normalized)
        if alias_hits:
            if len(alias_hits) > 1:
                # Multiple distinct songs register this alias. Do not pick
                # one arbitrarily -- surface the ambiguity so a caller (or a
                # human reviewer) resolves it explicitly.
                return SongResolution(
                    query=query,
                    normalized_query=normalized,
                    match_type=SongMatchType.AMBIGUOUS_ALIAS,
                    review_state=SongReviewState.UNKNOWN,
                    song_id=None,
                    canonical_title=None,
                    stored_status=None,
                )
            song_id, canonical_title, status = alias_hits[0]
            return SongResolution(
                query=query,
                normalized_query=normalized,
                match_type=SongMatchType.ALIAS,
                review_state=_review_state_for_status(status),
                song_id=song_id,
                canonical_title=canonical_title,
                stored_status=status,
            )

        return SongResolution(
            query=query,
            normalized_query=normalized,
            match_type=SongMatchType.NONE,
            review_state=SongReviewState.UNKNOWN,
            song_id=None,
            canonical_title=None,
            stored_status=None,
        )

    def is_verified(self, value: str) -> bool:
        return self.resolve(value).review_state == SongReviewState.VERIFIED
