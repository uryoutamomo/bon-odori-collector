"""Pure adapters for normalizing song evidence before any RDB write.

P3 gives the existing X, YouTube, OCR, and human-report entrances one
Candidate/Evidence contract. This module never opens a database and never
writes files. Callers inject the read-only ``SongCatalog`` and an optional
occurrence resolver, then decide what to do with the resulting finite route.

``auto_link`` is deliberately narrow: the song must resolve to a verified
canonical/alias, the target occurrence must be a unique strong match, and the
source must be structured or human-confirmed. Prose extraction, unknown song
identity, and ambiguous event matching all fail closed to review.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any, Callable, Iterable, Mapping

from song_processing.song_catalog import SongCatalog, SongMatchType, SongReviewState


SCHEMA_VERSION = 1
SOURCE_KINDS = {"x_text", "youtube_setlist", "ocr_review", "human_report"}
EVIDENCE_STRENGTHS = {"prose", "structured", "human_confirmed"}
EVIDENCE_MODES = {"official_setlist", "historical_youtube", "firsthand_observed"}
ROUTES = {
    "auto_link",
    "review_song_identity",
    "review_event_match",
    "review_evidence_strength",
    "reject",
}
APPROVED_OCR_STATUSES = {"approved", "確認済み", "apply"}
STRONG_OCCURRENCE_SCORE = 0.92


OccurrenceResolver = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _year(value: Any) -> int | None:
    match = re.match(r"^(20\d{2})", _text(value))
    return int(match.group(1)) if match else None


def _stable_id(*parts: Any) -> str:
    raw = "\0".join(_text(part) for part in parts)
    return "songcand_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _source_key(source_kind: str, explicit: Any, url: Any, fallback: Any) -> str:
    key = _text(explicit) or _text(url)
    if not key:
        key = "sha256:" + hashlib.sha256(_text(fallback).encode("utf-8")).hexdigest()
    return f"{source_kind}:{key}"


def _candidate(
    *,
    source_kind: str,
    evidence_strength: str,
    source_key: str,
    raw_song_title: Any,
    source_url: Any = "",
    observed_at: Any = "",
    raw_text: Any = "",
    account: Any = "",
    event_name_hint: Any = "",
    venue_hint: Any = "",
    event_date: Any = "",
    event_year: Any = None,
    occurrence_id: Any = "",
    source_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    title = _text(raw_song_title)
    if source_kind not in SOURCE_KINDS:
        raise ValueError(f"unsupported song evidence source_kind: {source_kind}")
    if evidence_strength not in EVIDENCE_STRENGTHS:
        raise ValueError(f"unsupported song evidence strength: {evidence_strength}")
    if not source_key or not title:
        raise ValueError("song evidence candidate requires source_key and raw_song_title")
    target = {
        "occurrence_id": _text(occurrence_id),
        "event_name_hint": _text(event_name_hint),
        "venue_hint": _text(venue_hint),
        "event_date": _text(event_date),
        "event_year": int(event_year) if event_year else _year(event_date),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": _stable_id(source_key, title, target["occurrence_id"], target["event_name_hint"]),
        "source_kind": source_kind,
        "evidence_strength": evidence_strength,
        "source_key": source_key,
        "source_url": _text(source_url),
        "observed_at": _text(observed_at),
        "account": _text(account),
        "raw_text": _text(raw_text)[:1200],
        "raw_song_title": title,
        "event_target": target,
        "source_payload": dict(source_payload or {}),
    }


def adapt_x_candidates(payload: Any) -> list[dict[str, Any]]:
    """Adapt daily X song candidates and song/venue co-occurrences."""
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        raise ValueError("X candidate payload requires rows list")
    output: list[dict[str, Any]] = []
    for row in payload["rows"]:
        if not isinstance(row, dict):
            raise TypeError("X candidate rows must be objects")
        category = _text(row.get("category"))
        if category not in {"曲候補", "曲×会場共起"}:
            continue
        song_title = _text(row.get("song_name") or row.get("canonical_song_name"))
        if not song_title and category == "曲候補":
            song_title = _text(row.get("term"))
        if not song_title:
            raise ValueError("X song candidate requires song_name or term")
        event_candidates = row.get("event_candidates")
        event_name_hint = (
            _text(event_candidates[0])
            if isinstance(event_candidates, list) and len(event_candidates) == 1
            else _text(row.get("event_name"))
        )
        evidence_rows = row.get("evidence")
        if not isinstance(evidence_rows, list) or not evidence_rows:
            evidence_rows = [{
                "url": row.get("evidence_url"),
                "text": row.get("evidence_text"),
                "date": row.get("observed_at"),
                "account": row.get("account"),
            }]
        for index, evidence in enumerate(evidence_rows):
            if not isinstance(evidence, dict):
                raise TypeError("X evidence rows must be objects")
            url = _text(evidence.get("url") or row.get("evidence_url"))
            raw_text = _text(evidence.get("text") or row.get("evidence_text"))
            key = _source_key("x_text", evidence.get("tweet_id"), url, f"{index}:{raw_text}")
            output.append(_candidate(
                source_kind="x_text",
                evidence_strength="prose",
                source_key=key,
                raw_song_title=song_title,
                source_url=url,
                observed_at=evidence.get("date"),
                raw_text=raw_text,
                account=evidence.get("account"),
                event_name_hint=event_name_hint,
                venue_hint=row.get("venue"),
                event_year=row.get("event_year"),
                occurrence_id=row.get("occurrence_id"),
                source_payload={"category": category, "reason": row.get("reason") or row.get("triage_reason")},
            ))
    return output


def adapt_youtube_setlists(payload: Any) -> list[dict[str, Any]]:
    """Adapt structured per-occurrence YouTube setlists, one song per video."""
    if not isinstance(payload, dict) or not isinstance(payload.get("occurrences"), list):
        raise ValueError("YouTube setlist payload requires occurrences list")
    output: list[dict[str, Any]] = []
    for occurrence in payload["occurrences"]:
        if not isinstance(occurrence, dict):
            raise TypeError("YouTube setlist occurrences must be objects")
        setlist = occurrence.get("setlist")
        if not isinstance(setlist, list):
            raise ValueError("YouTube setlist occurrence requires setlist list")
        matched = occurrence.get("matched_public_event")
        matched = matched if isinstance(matched, dict) else {}
        videos = {
            _text(video.get("url")): video
            for video in occurrence.get("source_videos") or []
            if isinstance(video, dict) and _text(video.get("url"))
        }
        event_name = _text(
            occurrence.get("canonical_event_name")
            or matched.get("name")
            or occurrence.get("event_name_hint")
        )
        venue = _text(occurrence.get("canonical_venue") or matched.get("venue") or occurrence.get("venue"))
        event_date = _text(occurrence.get("event_date") or matched.get("date"))
        occurrence_id = _text(matched.get("occurrence_id") or matched.get("id"))
        occurrence_key = _text(occurrence.get("occurrence_key"))
        if not occurrence_key:
            raise ValueError("YouTube setlist occurrence requires occurrence_key")
        for index, song in enumerate(setlist):
            song = song if isinstance(song, dict) else {"title": song}
            title = _text(song.get("title") or song.get("song_name") or song.get("name"))
            if not title:
                raise ValueError("YouTube setlist item requires title")
            url = _text(song.get("url"))
            video = videos.get(url, {})
            key = _source_key(
                "youtube_setlist",
                f"{occurrence_key}:{song.get('number') or index + 1}:{url}",
                url,
                title,
            )
            output.append(_candidate(
                source_kind="youtube_setlist",
                evidence_strength="structured",
                source_key=key,
                raw_song_title=title,
                source_url=url,
                observed_at=video.get("published_at"),
                raw_text=video.get("title"),
                account=video.get("account"),
                event_name_hint=event_name,
                venue_hint=venue,
                event_date=event_date,
                occurrence_id=occurrence_id,
                source_payload={
                    "occurrence_key": occurrence_key,
                    "setlist_number": song.get("number"),
                    "evidence_mode": "historical_youtube",
                    "producer_confidence": occurrence.get("confidence"),
                    "role": occurrence.get("role"),
                    "reliability_key": occurrence.get("reliability_key"),
                },
            ))
    return output


def adapt_ocr_reviews(payload: Any) -> list[dict[str, Any]]:
    """Adapt only explicitly approved OCR rows with an explicit song list."""
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("OCR review payload requires items list")
    output: list[dict[str, Any]] = []
    for row in payload["items"]:
        if not isinstance(row, dict):
            raise TypeError("OCR review rows must be objects")
        if _text(row.get("status")) not in APPROVED_OCR_STATUSES:
            continue
        songs = row.get("songs")
        if not isinstance(songs, list) or not songs:
            raise ValueError("approved OCR review requires explicit songs list")
        url = _text(row.get("url"))
        review_key = _source_key("ocr_review", row.get("id"), url, row.get("ocr_text"))
        for song in songs:
            title = _text(song.get("title") if isinstance(song, dict) else song)
            output.append(_candidate(
                source_kind="ocr_review",
                evidence_strength="structured",
                source_key=f"{review_key}:song:{title}",
                raw_song_title=title,
                source_url=url,
                observed_at=row.get("observed_at") or row.get("date"),
                raw_text=row.get("ocr_text") or row.get("tweet_text"),
                account=row.get("account") or row.get("speaker"),
                event_name_hint=row.get("event_name"),
                venue_hint=row.get("venue"),
                event_date=row.get("event_date"),
                occurrence_id=row.get("occurrence_id"),
                source_payload={
                    "kind": row.get("kind"),
                    "reliability": row.get("reliability"),
                    "evidence_mode": row.get("evidence_mode"),
                },
            ))
    return output


def adapt_human_change_requests(payload: Any) -> list[dict[str, Any]]:
    """Adapt reviewed finite ``add_song_evidence`` requests as human reports."""
    if not isinstance(payload, dict) or not isinstance(payload.get("requests"), list):
        raise ValueError("human change-request payload requires requests list")
    output: list[dict[str, Any]] = []
    for request in payload["requests"]:
        if not isinstance(request, dict):
            raise TypeError("human change requests must be objects")
        if request.get("change_type") != "add_song_evidence":
            continue
        request_id = _text(request.get("request_id"))
        source = request.get("source")
        source = source if isinstance(source, dict) else {}
        songs = request.get("songs")
        if not request_id or not isinstance(songs, list) or not songs:
            raise ValueError("add_song_evidence request requires request_id and songs")
        source_key = _source_key(
            "human_report", source.get("source_key") or request_id, source.get("url"), request.get("note")
        )
        match_hint = request.get("match_hint")
        match_hint = match_hint if isinstance(match_hint, dict) else {}
        for song in songs:
            song = song if isinstance(song, dict) else {"title": song}
            title = _text(song.get("title"))
            output.append(_candidate(
                source_kind="human_report",
                evidence_strength="human_confirmed",
                source_key=f"{source_key}:song:{title}",
                raw_song_title=title,
                source_url=source.get("url"),
                raw_text=source.get("text_excerpt") or request.get("note"),
                account=source.get("account_key"),
                event_name_hint=match_hint.get("event_name_hint"),
                venue_hint=match_hint.get("venue_name_hint"),
                event_year=match_hint.get("event_year"),
                occurrence_id=request.get("occurrence_id"),
                source_payload={
                    "request_id": request_id,
                    "evidence_mode": request.get("evidence_mode"),
                    "song_note": song.get("note"),
                },
            ))
    return output


def _default_target_resolution(target: Mapping[str, Any]) -> dict[str, Any]:
    occurrence_id = _text(target.get("occurrence_id"))
    if occurrence_id:
        return {"match_state": "strong", "occurrence_id": occurrence_id, "match_score": 1.0}
    if target.get("event_name_hint"):
        return {"match_state": "unresolved", "occurrence_id": "", "match_score": None}
    return {"match_state": "none", "occurrence_id": "", "match_score": None}


def route_candidate(
    candidate: Mapping[str, Any],
    catalog: SongCatalog,
    occurrence_resolver: OccurrenceResolver | None = None,
) -> dict[str, Any]:
    """Resolve song identity + event target and assign one finite safe route."""
    resolution = catalog.resolve(_text(candidate.get("raw_song_title")))
    target = dict(candidate.get("event_target") or {})
    target_resolution = dict(
        occurrence_resolver(target) if occurrence_resolver else _default_target_resolution(target)
    )
    match_state = _text(target_resolution.get("match_state")) or "none"
    target_resolution.setdefault("occurrence_id", "")
    target_resolution.setdefault("match_score", None)

    if resolution.review_state == SongReviewState.REJECTED:
        route, reason = "reject", "catalog_rejected"
    elif resolution.match_type == SongMatchType.AMBIGUOUS_ALIAS:
        route, reason = "review_song_identity", "catalog_ambiguous_alias"
    elif resolution.review_state == SongReviewState.CANDIDATE:
        route, reason = "review_song_identity", "catalog_candidate"
    elif resolution.review_state != SongReviewState.VERIFIED:
        route, reason = "review_song_identity", "catalog_unresolved_or_unknown"
    elif match_state != "strong" or not target_resolution.get("occurrence_id"):
        route, reason = "review_event_match", f"event_match_{match_state}"
    elif candidate.get("evidence_strength") == "prose":
        route, reason = "review_evidence_strength", "prose_requires_review"
    elif (candidate.get("source_payload") or {}).get("evidence_mode") not in EVIDENCE_MODES:
        route, reason = "review_evidence_strength", "evidence_mode_required"
    else:
        route, reason = "auto_link", "verified_song_strong_event_structured_evidence"

    if route not in ROUTES:
        raise AssertionError(f"unbounded song evidence route: {route}")
    output = dict(candidate)
    output["catalog_resolution"] = {
        "match_type": resolution.match_type.value,
        "review_state": resolution.review_state.value,
        "song_id": resolution.song_id,
        "canonical_title": resolution.canonical_title,
        "stored_status": resolution.stored_status,
    }
    output["event_resolution"] = target_resolution
    output["route"] = route
    output["reason_code"] = reason
    return output


def resolve_occurrence_target(conn: Any, target: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve one target against an injected read-only master connection."""
    occurrence_id = _text(target.get("occurrence_id"))
    if occurrence_id:
        found = conn.execute(
            "SELECT occurrence_id FROM event_occurrences WHERE occurrence_id = ?", (occurrence_id,)
        ).fetchone()
        return {
            "match_state": "strong" if found else "missing",
            "occurrence_id": occurrence_id if found else "",
            "match_score": 1.0 if found else None,
        }

    event_name = _text(target.get("event_name_hint"))
    if not event_name:
        return {"match_state": "none", "occurrence_id": "", "match_score": None}
    from report_apply.event_report_helpers import find_occurrence_candidates

    event_year = target.get("event_year") or _year(target.get("event_date"))
    candidates = find_occurrence_candidates(
        conn, event_name, _text(target.get("venue_hint")) or None, event_year
    )
    strong = [row for row in candidates if float(row.get("match_score") or 0) >= STRONG_OCCURRENCE_SCORE]
    if len(strong) == 1:
        row = strong[0]
        return {
            "match_state": "strong",
            "occurrence_id": row["occurrence_id"],
            "match_score": row["match_score"],
            "matched_event_name": row.get("display_name") or row.get("series_name"),
            "matched_venue": row.get("venue_name"),
        }
    if len(strong) > 1:
        return {
            "match_state": "ambiguous",
            "occurrence_id": "",
            "match_score": strong[0]["match_score"],
            "candidate_occurrence_ids": [row["occurrence_id"] for row in strong],
        }
    if candidates:
        return {
            "match_state": "weak",
            "occurrence_id": "",
            "match_score": candidates[0]["match_score"],
            "candidate_occurrence_ids": [row["occurrence_id"] for row in candidates[:3]],
        }
    return {"match_state": "none", "occurrence_id": "", "match_score": None}


def build_snapshot(
    candidates: Iterable[Mapping[str, Any]],
    catalog: SongCatalog,
    occurrence_resolver: OccurrenceResolver | None = None,
) -> dict[str, Any]:
    routed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        candidate_id = _text(candidate.get("candidate_id"))
        if not candidate_id:
            raise ValueError("adapted song evidence requires candidate_id")
        if candidate_id in seen:
            continue
        seen.add(candidate_id)
        routed.append(route_candidate(candidate, catalog, occurrence_resolver))
    routed.sort(key=lambda row: (row["source_kind"], row["route"], row["candidate_id"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_by": "song_evidence_adapters.build_snapshot",
        "write_mode": "shadow_read_only",
        "candidate_count": len(routed),
        "source_counts": dict(sorted(Counter(row["source_kind"] for row in routed).items())),
        "route_counts": dict(sorted(Counter(row["route"] for row in routed).items())),
        "catalog_state_counts": dict(sorted(Counter(
            row["catalog_resolution"]["review_state"] for row in routed
        ).items())),
        "items": routed,
    }
