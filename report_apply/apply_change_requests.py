#!/usr/bin/env python3
"""Apply reviewed RDB change requests through one guarded entry point.

Default mode writes only to a copied SQLite DB (dry run). Production writes
require --apply and manual_apply_guards.CHANGE_REQUESTS_CONFIRMATION.

This is the steady-state replacement for new event-specific one-off apply
scripts. The input is a small JSON file with a finite list of change_type
values. Each type has its own validation so current-year confirmations,
historical references, venue fixes, and song evidence do not collapse into a
free-form patch language.
"""

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import operation_safety.manual_apply_guards as manual_apply_guards
from report_apply.event_report_helpers import (
    confirm_occurrence_schedule_venue,
    ensure_venue,
    link_occurrence_evidence,
    upsert_evidence_item,
    upsert_occurrence_song,
)
from master_rdb.master_db import MASTER_DB, normalize_text, refresh_manifest_database_state, stable_id, table_counts
from report_apply.rdb_apply_support import audit_db, backup_db, copy_db, has_high_issue, issue_summary, rows, scalar, write_json


DATA = Path("data")
OUT_DB = DATA / "change_requests_apply_dry_run.sqlite"
OUT_JSON = DATA / "change_requests_apply_report.json"
OUT_MD = DATA / "change_requests_apply_report.md"
BACKUP_DIR = DATA / "backups"
PREFLIGHT_DB = DATA / "change_requests_apply_preflight.sqlite"
SCRIPT_NAME = "apply_change_requests.py"
JST = ZoneInfo("Asia/Tokyo")

CHANGE_TYPES = {
    "create_event_series",
    "create_current_year_occurrence",
    "confirm_current_year_date",
    "add_historical_reference",
    "update_venue",
    "add_song_evidence",
}
# These create their target instead of pointing at one, so they carry no occurrence_id.
TARGETLESS_CHANGE_TYPES = {"create_event_series", "create_current_year_occurrence"}
CURRENT_YEAR_SOURCE_KINDS = {"official_current_year", "organizer_current_year", "trusted_x_current_year"}
SONG_EVIDENCE_MODES = {
    "official_setlist": {
        "role": "setlist",
        "evidence_status": "announced",
        "basis": "official_setlist",
        "note": "公式・主催者系ソースで確認した告知曲目。",
        "target": "program",
        "confidence": 0.95,
    },
    "historical_youtube": {
        "role": "result",
        "evidence_status": "observed",
        "basis": "historical_youtube",
        "note": "YouTube過去実績で確認した曲目。",
        "target": "historical_program",
        "confidence": 0.85,
    },
    "firsthand_observed": {
        "role": "result",
        "evidence_status": "observed",
        "basis": "firsthand_observed",
        "note": "現地・一次情報で確認した曲目。",
        "target": "program",
        "confidence": 0.95,
    },
}


def _required(obj, field, errors, prefix):
    if not obj.get(field):
        errors.append(f"{prefix}: missing required field: {field}")


def _venue_reference(request):
    """Return the venue_id the request names, or its venue name, or None.

    A request may point at an existing venue by id. That path skips ensure_venue() entirely:
    the identity question was already answered upstream, and re-deciding it here by name is how
    the same place ends up stored twice.
    """
    venue = request.get("venue") or {}
    return venue.get("venue_id") or venue.get("name") or None


def validate_payload(payload):
    errors = []
    if payload.get("request_type") != "rdb_change_requests":
        errors.append(f"invalid request_type: {payload.get('request_type')!r}")
    requests = payload.get("requests")
    if not isinstance(requests, list) or not requests:
        errors.append("requests must be a non-empty list")
        requests = []
    seen = set()
    for index, request in enumerate(requests):
        prefix = f"requests[{index}]"
        _required(request, "request_id", errors, prefix)
        if request.get("request_id") in seen:
            errors.append(f"{prefix}: duplicate request_id: {request.get('request_id')!r}")
        seen.add(request.get("request_id"))
        change_type = request.get("change_type")
        if change_type not in CHANGE_TYPES:
            errors.append(f"{prefix}: invalid change_type: {change_type!r}")
            continue
        if change_type not in TARGETLESS_CHANGE_TYPES and not request.get("occurrence_id"):
            errors.append(f"{prefix}: requires occurrence_id")
        source = request.get("source") or {}
        if change_type == "create_event_series":
            _required(request, "series_name", errors, prefix)
            _required(request, "display_name", errors, prefix)
            _required(request, "date_start", errors, prefix)
            _required(request, "event_year", errors, prefix)
            _required(source, "url", errors, f"{prefix}.source")
            if source.get("kind") not in CURRENT_YEAR_SOURCE_KINDS:
                errors.append(
                    f"{prefix}.source: create_event_series requires kind in {sorted(CURRENT_YEAR_SOURCE_KINDS)}"
                )
            if request.get("date_start") and request.get("event_year"):
                if not str(request["date_start"]).startswith(str(request["event_year"])):
                    errors.append(f"{prefix}: date_start must be in event_year")
            if not _venue_reference(request):
                errors.append(f"{prefix}.venue: requires venue_id or name")
            if request.get("series_id"):
                errors.append(f"{prefix}: create_event_series must not carry series_id")
        elif change_type == "create_current_year_occurrence":
            _required(request, "series_id", errors, prefix)
            _required(request, "display_name", errors, prefix)
            _required(request, "date_start", errors, prefix)
            _required(request, "event_year", errors, prefix)
            if not _venue_reference(request):
                errors.append(f"{prefix}.venue: requires venue_id or name")
            _required(source, "url", errors, f"{prefix}.source")
            if source.get("kind") not in CURRENT_YEAR_SOURCE_KINDS:
                errors.append(
                    f"{prefix}.source: create_current_year_occurrence requires kind in {sorted(CURRENT_YEAR_SOURCE_KINDS)}"
                )
            if request.get("date_start") and request.get("event_year"):
                if not str(request["date_start"]).startswith(str(request["event_year"])):
                    errors.append(f"{prefix}: date_start must be in event_year")
            sequence = request.get("occurrence_sequence", 1)
            if sequence != 1:
                errors.append(f"{prefix}: occurrence_sequence must be 1")
        elif change_type == "confirm_current_year_date":
            _required(request, "date_start", errors, prefix)
            _required(request, "event_year", errors, prefix)
            _required(source, "url", errors, f"{prefix}.source")
            if source.get("kind") not in CURRENT_YEAR_SOURCE_KINDS:
                errors.append(
                    f"{prefix}.source: confirm_current_year_date requires kind in {sorted(CURRENT_YEAR_SOURCE_KINDS)}"
                )
            if request.get("date_start") and request.get("event_year"):
                if not str(request["date_start"]).startswith(str(request["event_year"])):
                    errors.append(f"{prefix}: date_start must be in event_year")
        elif change_type == "add_historical_reference":
            _required(source, "url", errors, f"{prefix}.source")
            if source.get("platform") == "youtube" and source.get("kind") != "historical_occurrence_video":
                errors.append(f"{prefix}.source: youtube historical reference must use kind='historical_occurrence_video'")
            if request.get("historical_year") and request.get("event_year"):
                if int(request["historical_year"]) >= int(request["event_year"]):
                    errors.append(f"{prefix}: historical_year must be before target event_year")
        elif change_type == "update_venue":
            if not _venue_reference(request):
                errors.append(f"{prefix}.venue: requires venue_id or name")
            _required(source, "url", errors, f"{prefix}.source")
        elif change_type == "add_song_evidence":
            mode = request.get("evidence_mode")
            if mode not in SONG_EVIDENCE_MODES:
                errors.append(f"{prefix}: evidence_mode must be one of {sorted(SONG_EVIDENCE_MODES)}")
            songs = request.get("songs")
            if not isinstance(songs, list) or not songs:
                errors.append(f"{prefix}: songs must be a non-empty list")
            elif any(not isinstance(song, dict) or not song.get("title") for song in songs):
                errors.append(f"{prefix}: songs must be a list of {title: str, uncertain?: bool}")
            if mode == "firsthand_observed":
                _required(source, "source_key", errors, f"{prefix}.source")
            else:
                _required(source, "url", errors, f"{prefix}.source")
    if errors:
        raise ValueError("invalid change request payload: " + "; ".join(errors))


def validate_apply_allowed(payload):
    blocked = [
        request.get("request_id") or f"index:{index}"
        for index, request in enumerate(payload.get("requests", []))
        if request.get("dry_run_only")
    ]
    if blocked:
        raise ValueError(f"payload contains dry_run_only requests; refusing --apply: {', '.join(blocked)}")


def _resolve_occurrence(conn, request, index):
    occurrence_id = request.get("occurrence_id")
    if not occurrence_id:
        return None, [
            {
                "severity": "medium",
                "issue_type": "occurrence_id_required",
                "request_index": index,
                "request_id": request.get("request_id"),
            }
        ]

    found = rows(conn, "SELECT occurrence_id FROM event_occurrences WHERE occurrence_id = ?", (occurrence_id,))
    if found:
        return occurrence_id, []
    return None, [
        {
            "severity": "medium",
            "issue_type": "occurrence_id_not_found",
            "request_index": index,
            "request_id": request.get("request_id"),
            "occurrence_id": occurrence_id,
        }
    ]


def _source_evidence_id(request):
    source = request["source"]
    return stable_id("evid", source.get("url") or "", request["request_id"], request["change_type"])


def _upsert_source_evidence(conn, request, now, *, detected_event_date=None):
    source = request["source"]
    evidence_id = _source_evidence_id(request)
    upsert_evidence_item(
        conn,
        evidence_id,
        platform=source.get("platform") or "web",
        evidence_type=source.get("kind") or request["change_type"],
        source_key=source.get("source_key") or source.get("url"),
        account_key=source.get("account_key"),
        title=source.get("title") or request["request_id"],
        text_excerpt=source.get("text_excerpt") or request.get("note") or source.get("url"),
        url=source.get("url"),
        event_date=detected_event_date,
        raw_json_extra={"request_id": request["request_id"], "change_type": request["change_type"]},
        now=now,
    )
    return evidence_id


def _append_detail(conn, occurrence_id, addendum, now):
    if not addendum:
        return []
    result = confirm_occurrence_schedule_venue(conn, occurrence_id, detail_addendum=addendum, now=now)
    return result["changed_fields"]


def _current_year_date_status(request, now):
    """Return ended only after the event's final JST calendar day."""
    event_end = date.fromisoformat(request.get("date_end") or request["date_start"])
    applied_at = datetime.fromisoformat(str(now).replace("Z", "+00:00"))
    if applied_at.tzinfo is None:
        applied_at = applied_at.replace(tzinfo=timezone.utc)
    today_jst = applied_at.astimezone(JST).date()
    return "ended" if event_end < today_jst else "confirmed"


def _resolve_venue(conn, request, now):
    """Return (venue_id, status, issues). No venue on the request means (None, None, [])."""
    venue = request.get("venue") or {}
    venue_id = venue.get("venue_id")
    if venue_id:
        if not rows(conn, "SELECT venue_id FROM venues WHERE venue_id = ?", (venue_id,)):
            return None, None, [{"severity": "medium", "issue_type": "venue_id_not_found", "request_id": request["request_id"], "venue_id": venue_id}]
        return venue_id, "resolved", []
    if not venue.get("name"):
        return None, None, []
    result = ensure_venue(
        conn,
        venue["name"],
        area=venue.get("area"),
        address=venue.get("address"),
        access=venue.get("access"),
        source_url=(request.get("source") or {}).get("url"),
        now=now,
    )
    if result["status"] == "ambiguous":
        return None, None, [{"severity": "medium", "issue_type": "ambiguous_venue", "request_id": request["request_id"], "candidates": result["candidates"]}]
    return result["venue_id"], result["status"], []


def apply_confirm_current_year_date(conn, request, occurrence_id, now):
    occurrence_before = conn.execute(
        "SELECT source_url FROM event_occurrences WHERE occurrence_id = ?",
        (occurrence_id,),
    ).fetchone()
    venue_id, venue_status, venue_issues = _resolve_venue(conn, request, now)
    if venue_issues:
        return None, venue_issues

    evidence_id = _upsert_source_evidence(conn, request, now, detected_event_date=request["date_start"])
    date_status = _current_year_date_status(request, now)
    result = confirm_occurrence_schedule_venue(
        conn,
        occurrence_id,
        venue_id=venue_id,
        date_start=request["date_start"],
        date_end=request.get("date_end"),
        date_status=date_status,
        lifecycle_status="published",
        confidence=request.get("confidence") or "high",
        source_kind=request["source"]["kind"],
        detail_addendum=request.get("note"),
        date_basis_note=f"current-year source: {request['source']['url']}",
        now=now,
    )
    source_url = request["source"]["url"]
    conn.execute(
        "UPDATE event_occurrences SET source_url = ?, updated_at = ? WHERE occurrence_id = ?",
        (source_url, now, occurrence_id),
    )
    if occurrence_before is None or occurrence_before[0] != source_url:
        result["changed_fields"].append("source_url")
    link_occurrence_evidence(
        conn,
        occurrence_id,
        evidence_id,
        "date_and_venue",
        confidence=1.0,
        notes=request.get("note") or "今年の開催日・会場の確認根拠。",
    )
    if request.get("predicted_date_id"):
        conn.execute(
            """
            UPDATE predicted_occurrence_dates
            SET target_occurrence_id = ?,
                application_status = ?,
                updated_at = ?
            WHERE predicted_date_id = ?
            """,
            (
                occurrence_id,
                request.get("prediction_resolution") or "superseded_by_current_year_confirmation",
                now,
                request["predicted_date_id"],
            ),
        )
    return {
        "request_id": request["request_id"],
        "change_type": request["change_type"],
        "occurrence_id": occurrence_id,
        "evidence_id": evidence_id,
        "changed_fields": result["changed_fields"],
        "venue_status": venue_status,
        "date_status": date_status,
    }, []


def apply_create_event_series(conn, request, index, now):
    """Create a genuinely new series, then its first occurrence.

    Unlike ensure_series_and_occurrence(), this never reuses a series whose name happens to
    normalize to the same key, and never updates an existing occurrence. If the key is taken the
    caller wanted create_current_year_occurrence: quietly merging the two is how a "new event"
    ends up overwriting the date of an unrelated one.
    """
    series_key = normalize_text(request["series_name"])
    if not series_key:
        return None, [{"severity": "medium", "issue_type": "series_name_empty", "request_index": index, "request_id": request.get("request_id")}]
    existing = rows(conn, "SELECT series_id FROM event_series WHERE series_key = ?", (series_key,))
    if existing:
        return None, [
            {
                "severity": "medium",
                "issue_type": "series_key_already_exists",
                "request_index": index,
                "request_id": request.get("request_id"),
                "series_key": series_key,
                "series_id": existing[0]["series_id"],
            }
        ]
    series_id = stable_id("series", series_key)
    savepoint = f"create_event_series_{index}"
    conn.execute(f"SAVEPOINT {savepoint}")
    conn.execute(
        """
        INSERT INTO event_series (
          series_id, origin, series_key, canonical_name, normalized_name,
          usual_venue_id, area, program_type, annual_months_json,
          schedule_rule_type, schedule_rule_detail, public_intro, source_url,
          status, created_at, updated_at
        ) VALUES (?, 'curated', ?, ?, ?, NULL, NULL, 'bon_odori', '[]', NULL, NULL, NULL, ?, 'active', ?, ?)
        """,
        (
            series_id,
            series_key,
            request["series_name"],
            series_key,
            (request.get("source") or {}).get("url"),
            now,
            now,
        ),
    )
    applied, issues = apply_create_current_year_occurrence(conn, {**request, "series_id": series_id}, index, now)
    if applied is None:
        conn.execute(f"ROLLBACK TO {savepoint}")
        conn.execute(f"RELEASE {savepoint}")
        return None, issues
    conn.execute(f"RELEASE {savepoint}")
    applied["change_type"] = request["change_type"]
    applied["series_id"] = series_id
    applied["series_created"] = True
    return applied, issues


def apply_create_current_year_occurrence(conn, request, index, now):
    series_id = request["series_id"]
    series = rows(
        conn,
        "SELECT series_id, status FROM event_series WHERE series_id = ?",
        (series_id,),
    )
    if not series:
        return None, [
            {
                "severity": "medium",
                "issue_type": "series_id_not_found",
                "request_index": index,
                "request_id": request.get("request_id"),
                "series_id": series_id,
            }
        ]
    if series[0]["status"] != "active":
        return None, [
            {
                "severity": "medium",
                "issue_type": "series_not_active",
                "request_index": index,
                "request_id": request.get("request_id"),
                "series_id": series_id,
                "series_status": series[0]["status"],
            }
        ]

    event_year = int(request["event_year"])
    sequence = 1
    existing = rows(
        conn,
        """
        SELECT occurrence_id
        FROM event_occurrences
        WHERE series_id = ? AND event_year = ? AND occurrence_sequence = ?
        """,
        (series_id, event_year, sequence),
    )
    occurrence_created = not existing
    occurrence_id = (
        existing[0]["occurrence_id"]
        if existing
        else stable_id("occ", series_id, event_year, sequence)
    )
    savepoint = f"create_current_year_occurrence_{index}"
    conn.execute(f"SAVEPOINT {savepoint}")
    if occurrence_created:
        conn.execute(
            """
            INSERT INTO event_occurrences (
              occurrence_id, origin, series_id, event_year, occurrence_sequence,
              display_name, venue_id, date_start, date_end, date_status,
              lifecycle_status, confidence, source_kind, source_url, detail,
              created_at, updated_at
            ) VALUES (?, 'curated', ?, ?, ?, ?, NULL, NULL, NULL, 'unknown',
                      'draft', 'unknown', NULL, NULL, NULL, ?, ?)
            """,
            (
                occurrence_id,
                series_id,
                event_year,
                sequence,
                request["display_name"],
                now,
                now,
            ),
        )

    applied, issues = apply_confirm_current_year_date(
        conn,
        request,
        occurrence_id,
        now,
    )
    if applied is None:
        conn.execute(f"ROLLBACK TO {savepoint}")
        conn.execute(f"RELEASE {savepoint}")
        return None, issues
    conn.execute(f"RELEASE {savepoint}")
    if applied is not None:
        applied["change_type"] = request["change_type"]
        applied["series_id"] = series_id
        applied["occurrence_created"] = occurrence_created
    return applied, issues


def apply_add_historical_reference(conn, request, occurrence_id, now):
    occurrence_before = conn.execute(
        "SELECT * FROM event_occurrences WHERE occurrence_id = ?",
        (occurrence_id,),
    ).fetchone()
    evidence_id = _upsert_source_evidence(conn, request, now, detected_event_date=request.get("historical_date"))
    link_occurrence_evidence(
        conn,
        occurrence_id,
        evidence_id,
        "historical_reference",
        confidence=float(request.get("link_confidence") or 0.85),
        notes=request.get("note") or "過去実績の参考根拠。未来開催日の確定根拠にはしない。",
    )
    date_inserted = False
    if request.get("historical_date"):
        date_end = request.get("historical_date_end") or request["historical_date"]
        existing_date = rows(
            conn,
            """
            SELECT occurrence_date_id
            FROM occurrence_dates
            WHERE occurrence_id = ?
              AND date_start = ?
              AND COALESCE(date_end, date_start) = ?
              AND date_type = 'historical_reference'
            ORDER BY occurrence_date_id
            LIMIT 1
            """,
            (occurrence_id, request["historical_date"], date_end),
        )
        date_id = (
            existing_date[0]["occurrence_date_id"]
            if existing_date
            else stable_id("date", occurrence_id, request["historical_date"], date_end, "historical_reference")
        )
        conn.execute(
            """
            INSERT INTO occurrence_dates (
              occurrence_date_id, occurrence_id, date_start, date_end, date_type,
              confidence, source_evidence_id, basis, created_at
            ) VALUES (?, ?, ?, ?, 'historical_reference', ?, ?, ?, ?)
            ON CONFLICT(occurrence_date_id) DO UPDATE SET
              source_evidence_id=excluded.source_evidence_id,
              basis=excluded.basis
            """,
            (
                date_id,
                occurrence_id,
                request["historical_date"],
                date_end,
                request.get("confidence") or "medium",
                evidence_id,
                request.get("basis") or "過去実績の参考日付。現在年の開催確定には使わない。",
                now,
            ),
        )
        date_inserted = True
    occurrence_after = conn.execute(
        "SELECT * FROM event_occurrences WHERE occurrence_id = ?",
        (occurrence_id,),
    ).fetchone()
    issues = []
    if occurrence_after != occurrence_before:
        issues.append(
            {
                "severity": "high",
                "issue_type": "historical_reference_mutated_occurrence",
                "request_id": request["request_id"],
                "occurrence_id": occurrence_id,
            }
        )
    return {
        "request_id": request["request_id"],
        "change_type": request["change_type"],
        "occurrence_id": occurrence_id,
        "evidence_id": evidence_id,
        "changed_fields": [],
        "historical_date_inserted": date_inserted,
    }, issues


def apply_update_venue(conn, request, occurrence_id, now):
    venue_id, venue_status, venue_issues = _resolve_venue(conn, request, now)
    if venue_issues:
        return None, venue_issues
    evidence_id = _upsert_source_evidence(conn, request, now)
    result = confirm_occurrence_schedule_venue(
        conn,
        occurrence_id,
        venue_id=venue_id,
        source_kind=request["source"].get("kind"),
        detail_addendum=request.get("note"),
        date_basis_note=None,
        now=now,
    )
    link_occurrence_evidence(
        conn,
        occurrence_id,
        evidence_id,
        "venue",
        confidence=float(request.get("link_confidence") or 0.95),
        notes=request.get("note") or "会場情報の更新根拠。",
    )
    return {
        "request_id": request["request_id"],
        "change_type": request["change_type"],
        "occurrence_id": occurrence_id,
        "venue_id": venue_id,
        "venue_status": venue_status,
        "evidence_id": evidence_id,
        "changed_fields": result["changed_fields"],
    }, []


def apply_add_song_evidence(conn, request, occurrence_id, now):
    mode = SONG_EVIDENCE_MODES[request["evidence_mode"]]
    evidence_id = _upsert_source_evidence(conn, request, now, detected_event_date=request.get("event_date"))
    link_occurrence_evidence(
        conn,
        occurrence_id,
        evidence_id,
        mode["target"],
        confidence=mode["confidence"],
        notes=request.get("note") or mode["note"],
    )
    songs_applied = []
    for song in request["songs"]:
        songs_applied.append(
            upsert_occurrence_song(
                conn,
                occurrence_id,
                song["title"],
                evidence_id,
                role=mode["role"],
                evidence_status=mode["evidence_status"],
                basis_key=mode["basis"],
                evidence_note=song.get("note") or mode["note"],
                uncertain=bool(song.get("uncertain", False)),
                now=now,
            )
        )
    changed_fields = _append_detail(conn, occurrence_id, request.get("note"), now)
    return {
        "request_id": request["request_id"],
        "change_type": request["change_type"],
        "occurrence_id": occurrence_id,
        "evidence_id": evidence_id,
        "songs_applied": songs_applied,
        "changed_fields": changed_fields,
    }, []


APPLIERS = {
    "confirm_current_year_date": apply_confirm_current_year_date,
    "add_historical_reference": apply_add_historical_reference,
    "update_venue": apply_update_venue,
    "add_song_evidence": apply_add_song_evidence,
}


def apply_one_request(conn, request, index, now):
    if request["change_type"] == "create_event_series":
        return apply_create_event_series(conn, request, index, now)
    if request["change_type"] == "create_current_year_occurrence":
        return apply_create_current_year_occurrence(conn, request, index, now)
    occurrence_id, issues = _resolve_occurrence(conn, request, index)
    if occurrence_id is None:
        return None, issues
    return APPLIERS[request["change_type"]](conn, request, occurrence_id, now)


def apply_payload(conn, payload, now):
    applied = []
    unresolved = []
    all_issues = []
    for index, request in enumerate(payload["requests"]):
        applied_request, issues = apply_one_request(conn, request, index, now)
        all_issues.extend(issues)
        if applied_request is None:
            unresolved.append(request.get("request_id") or f"index:{index}")
        else:
            applied.append(applied_request)
    return {"resolved": bool(applied), "requests_applied": applied, "requests_unresolved": unresolved}, all_issues


def consistency_checks(conn, applied):
    issues = []
    fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_rows:
        issues.append(
            {"severity": "high", "issue_type": "foreign_key_check_failed", "count": len(fk_rows), "sample": [tuple(row) for row in fk_rows[:10]]}
        )
    for entry in applied.get("requests_applied", []):
        occurrence_id = entry["occurrence_id"]
        occ_count = scalar(conn, "SELECT COUNT(*) FROM event_occurrences WHERE occurrence_id = ?", (occurrence_id,))
        if occ_count != 1:
            issues.append({"severity": "high", "issue_type": "occurrence_missing_after_apply", "occurrence_id": occurrence_id})
        evidence_id = entry.get("evidence_id")
        if evidence_id:
            evidence_count = scalar(conn, "SELECT COUNT(*) FROM evidence_items WHERE evidence_id = ?", (evidence_id,))
            if evidence_count != 1:
                issues.append({"severity": "high", "issue_type": "evidence_missing_after_apply", "evidence_id": evidence_id})
        for song in entry.get("songs_applied", []):
            song_count = scalar(
                conn,
                "SELECT COUNT(*) FROM occurrence_songs WHERE occurrence_song_id = ?",
                (song["occurrence_song_id"],),
            )
            if song_count != 1:
                issues.append(
                    {"severity": "high", "issue_type": "occurrence_song_missing_after_apply", "occurrence_song_id": song["occurrence_song_id"]}
                )
    return issues


def render_markdown(result):
    applied = result["applied"]
    lines = [
        "# Change requests apply result",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- requests_applied: {len(applied.get('requests_applied', []))}",
        f"- requests_unresolved: {len(applied.get('requests_unresolved', []))}",
        f"- target_db: `{result['outputs']['target_db']}`",
        f"- dry_run_db: `{result['outputs']['dry_run_db']}`",
        f"- backup_db: `{result['outputs']['backup_db']}`",
        f"- db_committed: {result['write_guard']['db_committed']}",
        f"- rolled_back: {result['write_guard']['rolled_back']}",
        f"- issues_by_severity: {result['summary']['issues_by_severity']}",
        f"- audit_issues_by_severity: {result['summary']['audit_issues_by_severity']}",
        "",
        "## Applied requests",
        "",
    ]
    for entry in applied.get("requests_applied", []):
        lines.append(f"- {entry['request_id']} `{entry['change_type']}` occurrence={entry['occurrence_id']}")
    if applied.get("requests_unresolved"):
        lines += ["", "## Unresolved requests", ""]
        for request_id in applied["requests_unresolved"]:
            lines.append(f"- {request_id}")
    if result["issues"]:
        lines += ["", "## Issues", ""]
        for issue in result["issues"]:
            lines.append(f"- {issue['severity']} {issue['issue_type']}: {issue}")
    lines += [
        "",
        "## Next step",
        "",
        "- Medium issues mean those requests were skipped; fix the JSON and re-run.",
        "- High issues roll back the whole transaction.",
        "- Public JSON and site deploy remain separate and follow the one-a-day publish rule.",
        "",
    ]
    return "\n".join(lines)


def run(args):
    if args.apply:
        manual_apply_guards.require_confirmation(
            args.apply,
            args.confirm,
            manual_apply_guards.CHANGE_REQUESTS_CONFIRMATION,
            "apply_change_requests.py --apply",
        )
        if Path(args.out_db) == Path(args.master_db):
            raise ValueError("--out-db must not equal --master-db")

    payload = json.loads(Path(args.requests).read_text(encoding="utf-8"))
    validate_payload(payload)
    if args.apply:
        validate_apply_allowed(payload)
    now = datetime.now(timezone.utc).isoformat()
    target_db = Path(args.master_db if args.apply else args.out_db)
    backup_path = ""

    if args.apply:
        copy_db(args.master_db, PREFLIGHT_DB)
        with sqlite_connect(PREFLIGHT_DB) as conn:
            preflight_applied, preflight_change_issues = apply_payload(conn, payload, now)
            preflight_issues = preflight_change_issues + consistency_checks(conn, preflight_applied)
            conn.commit()
        preflight_audit = audit_db(PREFLIGHT_DB, PREFLIGHT_DB.with_suffix(".audit.json"), PREFLIGHT_DB.with_suffix(".audit.md"))
        if has_high_issue(preflight_issues, preflight_audit["issues"]):
            raise ValueError(
                f"preflight refused high severity issues: checks={issue_summary(preflight_issues)} audit={preflight_audit['issues_by_severity']}"
            )
        backup_path = str(backup_db(args.master_db, now, BACKUP_DIR))
    else:
        copy_db(args.master_db, args.out_db)

    committed = False
    rolled_back = False
    with sqlite_connect(target_db) as conn:
        applied, change_issues = apply_payload(conn, payload, now)
        issues = change_issues + consistency_checks(conn, applied)
        if has_high_issue(issues):
            conn.rollback()
            rolled_back = True
        else:
            conn.commit()
            committed = True
        counts = table_counts(conn)

    audit_result = audit_db(target_db, args.out_json.with_suffix(".audit.json"), args.out_md.with_suffix(".audit.md"))
    if args.apply and audit_result["issues_by_severity"].get("high"):
        raise ValueError(f"post-apply audit has high issues: {audit_result['issues_by_severity']}")
    if args.apply and committed:
        refresh_manifest_database_state(args.master_db, updated_at=now)

    result = {
        "generated_by": SCRIPT_NAME,
        "generated_at": now,
        "mode": "apply" if args.apply else "dry_run",
        "sources": {"master_db": str(args.master_db), "requests": str(args.requests)},
        "outputs": {
            "target_db": str(target_db),
            "dry_run_db": "" if args.apply else str(args.out_db),
            "backup_db": backup_path,
            "json": str(args.out_json),
            "markdown": str(args.out_md),
        },
        "options": {"apply": bool(args.apply)},
        "write_guard": {
            "db_committed": committed,
            "rolled_back": rolled_back,
            "rollback_reason": "high_severity_issue" if rolled_back else "",
        },
        "summary": {
            "issues_count": len(issues),
            "issues_by_severity": issue_summary(issues),
            "audit_issues_by_severity": audit_result["issues_by_severity"],
            "table_counts": counts,
        },
        "request_payload": payload,
        "applied": applied,
        "issues": issues,
        "audit": {
            "issue_count": audit_result["issue_count"],
            "issues_by_severity": audit_result["issues_by_severity"],
            "issues_by_type": audit_result["issues_by_type"],
        },
        "public_json_write": {
            "enabled": False,
            "policy": "Run export_public_events.py and the site deploy separately, on Uchida-san's schedule.",
        },
    }
    write_json(args.out_json, result)
    Path(args.out_md).write_text(render_markdown(result), encoding="utf-8")
    return result


def sqlite_connect(path):
    import sqlite3
    from contextlib import closing

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return closing(conn)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--master-db", type=Path, default=MASTER_DB)
    parser.add_argument("--out-db", type=Path, default=OUT_DB)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        result = run(args)
    except ValueError as exc:
        parser.error(str(exc))
    print(
        "change requests apply: "
        f"mode={result['mode']} "
        f"requests_applied={len(result['applied'].get('requests_applied', []))} "
        f"requests_unresolved={len(result['applied'].get('requests_unresolved', []))} "
        f"committed={result['write_guard']['db_committed']} "
        f"issues={result['summary']['issues_by_severity']} "
        f"audit={result['summary']['audit_issues_by_severity']} "
        f"target_db={result['outputs']['target_db']}"
    )
    return 1 if result["summary"]["issues_by_severity"].get("high") else 0


if __name__ == "__main__":
    raise SystemExit(main())
