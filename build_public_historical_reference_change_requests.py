#!/usr/bin/env python3
"""Build dry-run change requests from public historical-reference fields.

This is a C-phase bridge from legacy public JSON postprocessor output back to
Master RDB. It only writes a JSON request file and a Markdown report; the
Master RDB is changed later through apply_change_requests.py.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

from event_report_helpers import find_occurrence_candidates
from master_db import MASTER_DB, connect_existing, normalize_text, stable_id


DATA = Path("data")
PUBLIC_EVENTS = DATA / "public" / "events_public.json"
PUBLIC_EVENT_SOURCE_MAP = DATA / "public_event_source_map.json"
OUT_REQUESTS = DATA / "change_requests" / "public_historical_references_20260716.json"
OUT_REPORT = DATA / "public_historical_reference_change_requests.md"
TARGET_YEAR = 2026
STRONG_MATCH_SCORE = 0.92
VENUE_EXACT_MATCH_SCORE = 0.75


def load_json(path: Path, default):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def public_event_sidecar_key(event: dict) -> str:
    return "|".join(str(event.get(key) or "") for key in ("name", "venue", "date", "date_end"))


def load_source_map(path: Path) -> dict[str, dict]:
    payload = load_json(path, {})
    rows = payload.get("rows") or []
    return {
        row.get("public_event_key"): row
        for row in rows
        if row.get("public_event_key") and row.get("occurrence_id")
    }


def candidate_source(event: dict) -> dict | None:
    for source in event.get("source_urls") or []:
        url = source.get("url")
        if not url:
            continue
        return {
            "platform": "web",
            "kind": "historical_occurrence_source",
            "url": url,
            "title": source.get("label") or event.get("name") or url,
            "source_key": url,
        }
    return None


def candidate_source_from_rdb(conn, occurrence_id: str) -> dict | None:
    row = conn.execute(
        """
        SELECT
          occurrence.source_url AS occurrence_source_url,
          series.source_url AS series_source_url,
          occurrence.display_name AS occurrence_name,
          series.canonical_name AS series_name
        FROM event_occurrences AS occurrence
        JOIN event_series AS series ON series.series_id = occurrence.series_id
        WHERE occurrence.occurrence_id = ?
        """,
        (occurrence_id,),
    ).fetchone()
    if not row:
        return None
    for provenance, url, title in (
        ("rdb_occurrence", row["occurrence_source_url"], row["occurrence_name"]),
        ("rdb_series", row["series_source_url"], row["series_name"]),
    ):
        if url:
            return {
                "platform": "web",
                "kind": f"historical_occurrence_{provenance}",
                "url": url,
                "title": title or url,
                "source_key": url,
                "provenance": provenance,
            }
    evidence = conn.execute(
        """
        SELECT evidence.url, evidence.title
        FROM occurrence_evidence_links AS link
        JOIN evidence_items AS evidence ON evidence.evidence_id = link.evidence_id
        WHERE link.occurrence_id = ?
          AND COALESCE(evidence.url, '') <> ''
        ORDER BY link.confidence DESC, evidence.evidence_id
        LIMIT 1
        """,
        (occurrence_id,),
    ).fetchone()
    if not evidence:
        return None
    return {
        "platform": "web",
        "kind": "historical_occurrence_rdb_evidence",
        "url": evidence["url"],
        "title": evidence["title"] or row["occurrence_name"] or evidence["url"],
        "source_key": evidence["url"],
        "provenance": "rdb_evidence",
    }


def historical_dates(event: dict) -> tuple[str | None, str | None, int | None]:
    reference = event.get("historical_reference") or {}
    dates = reference.get("last_seen_dates") or event.get("last_seen_dates") or []
    dates = [value for value in dates if value]
    if not dates:
        return None, None, None
    start = dates[0]
    end = dates[-1] if dates[-1] != start else ""
    year = reference.get("last_seen_year") or event.get("last_seen_year")
    if not year and len(start) >= 4 and start[:4].isdigit():
        year = int(start[:4])
    return start, end, int(year) if year else None


def existing_historical_date(conn, occurrence_id: str, date_start: str, date_end: str) -> bool:
    normalized_end = date_end or date_start
    row = conn.execute(
        """
        SELECT 1
        FROM occurrence_dates
        WHERE occurrence_id = ?
          AND date_type = 'historical_reference'
          AND date_start = ?
          AND COALESCE(date_end, date_start) = ?
        LIMIT 1
        """,
        (occurrence_id, date_start, normalized_end),
    ).fetchone()
    return bool(row)


def occurrence_exists(conn, occurrence_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM event_occurrences WHERE occurrence_id = ? LIMIT 1",
        (occurrence_id,),
    ).fetchone()
    return bool(row)


def resolve_occurrence(conn, event: dict, source_map_occurrence_id: str | None = None) -> tuple[str | None, list[dict], str]:
    if source_map_occurrence_id:
        if occurrence_exists(conn, source_map_occurrence_id):
            return source_map_occurrence_id, [], "source_map"
        return None, [], "source_map_occurrence_missing"
    candidates = find_occurrence_candidates(
        conn,
        event.get("name"),
        event.get("venue"),
        TARGET_YEAR,
    )
    strong = [candidate for candidate in candidates if candidate["match_score"] >= STRONG_MATCH_SCORE]
    if len(strong) == 1:
        return strong[0]["occurrence_id"], candidates, "strong_unique"
    venue_key = normalize_text(event.get("venue"))
    venue_exact = [
        candidate
        for candidate in candidates
        if normalize_text(candidate.get("venue_name")) == venue_key
        and candidate["match_score"] >= VENUE_EXACT_MATCH_SCORE
    ]
    if len(venue_exact) == 1:
        return venue_exact[0]["occurrence_id"], candidates, "venue_exact_unique"
    if not candidates:
        return None, [], "no_candidate"
    if strong:
        return None, candidates, "ambiguous_strong"
    return None, candidates, "weak_candidate"


def build_request(event: dict, occurrence_id: str | None, source: dict, date_start: str, date_end: str, year: int) -> dict:
    request = {
        "request_id": stable_id("chrq", event.get("name"), event.get("venue"), date_start, date_end),
        "change_type": "add_historical_reference",
        "event_year": TARGET_YEAR,
        "historical_year": year,
        "historical_date": date_start,
        "historical_date_end": date_end,
        "confidence": (event.get("historical_reference") or {}).get("confidence") or "medium",
        "source": source,
        "basis": "公開JSONの historical_reference からRDB投影元へ戻す候補。現在年の開催確定には使わない。",
        "note": f"public historical_reference import candidate: {event.get('historical_reference_label') or event.get('public_note') or ''}",
        "dry_run_only": True,
    }
    if occurrence_id:
        request["occurrence_id"] = occurrence_id
    else:
        request["match_hint"] = {
            "event_name_hint": event.get("name"),
            "venue_name_hint": event.get("venue"),
            "event_year": TARGET_YEAR,
        }
    return request


def build_payload(public_events: list[dict], master_db: Path, source_map: dict[str, dict] | None = None) -> tuple[dict, dict]:
    source_map = source_map or {}
    requests = []
    issues = []
    counters = Counter()
    with connect_existing(master_db) as conn:
        conn.row_factory = sqlite3.Row
        for event in public_events:
            if not event.get("historical_reference"):
                counters["skipped:no_historical_reference"] += 1
                continue
            date_start, date_end, historical_year = historical_dates(event)
            if not date_start or not historical_year:
                counters["skipped:missing_historical_date"] += 1
                issues.append({"issue_type": "missing_historical_date", "name": event.get("name"), "venue": event.get("venue")})
                continue
            if historical_year >= TARGET_YEAR:
                counters["skipped:not_historical_year"] += 1
                issues.append({"issue_type": "not_historical_year", "name": event.get("name"), "venue": event.get("venue"), "historical_year": historical_year})
                continue
            sidecar = source_map.get(public_event_sidecar_key(event)) or {}
            occurrence_id, candidates, resolution = resolve_occurrence(
                conn,
                event,
                sidecar.get("occurrence_id"),
            )
            counters[f"resolution:{resolution}"] += 1
            if occurrence_id and existing_historical_date(conn, occurrence_id, date_start, date_end or ""):
                counters["skipped:already_recorded"] += 1
                continue
            source = candidate_source(event)
            source_provenance = "public_source_urls"
            if not source and occurrence_id:
                source = candidate_source_from_rdb(conn, occurrence_id)
                source_provenance = (source or {}).get("provenance") or "rdb_missing"
            if not source:
                counters["skipped:missing_source_url"] += 1
                issues.append({"issue_type": "missing_source_url", "name": event.get("name"), "venue": event.get("venue")})
                continue
            counters[f"source:{source_provenance}"] += 1
            request = build_request(event, occurrence_id, source, date_start, date_end or "", historical_year)
            if not occurrence_id:
                issues.append(
                    {
                        "issue_type": resolution,
                        "name": event.get("name"),
                        "venue": event.get("venue"),
                        "candidate_count": len(candidates),
                        "candidates": candidates[:5],
                        "request_id": request["request_id"],
                    }
                )
                counters["skipped:unresolved_occurrence"] += 1
                continue
            requests.append(request)
            counters["requests"] += 1

    payload = {
        "request_type": "rdb_change_requests",
        "generated_by": "build_public_historical_reference_change_requests.py",
        "scope": "public_historical_reference_backfill_candidates",
        "target_year": TARGET_YEAR,
        "requests": requests,
    }
    report = {
        "generated_by": payload["generated_by"],
        "target_year": TARGET_YEAR,
        "public_event_count": len(public_events),
        "request_count": len(requests),
        "issue_count": len(issues),
        "summary": dict(sorted(counters.items())),
        "issues": issues[:200],
    }
    return payload, report


def render_markdown(report: dict) -> str:
    lines = [
        "# Public Historical Reference Change Requests",
        "",
        f"- generated_by: {report['generated_by']}",
        f"- target_year: {report['target_year']}",
        f"- public_event_count: {report['public_event_count']}",
        f"- request_count: {report['request_count']}",
        f"- issue_count: {report['issue_count']}",
        "",
        "## Summary",
        "",
    ]
    for key, value in report["summary"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Issues", ""])
    if not report["issues"]:
        lines.append("- none")
    for issue in report["issues"][:50]:
        lines.append(
            f"- {issue['issue_type']}: {issue.get('name')} / {issue.get('venue')} "
            f"(candidates={issue.get('candidate_count', '-')})"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-events", default=str(PUBLIC_EVENTS))
    parser.add_argument("--source-map", default=str(PUBLIC_EVENT_SOURCE_MAP))
    parser.add_argument("--master-db", default=str(MASTER_DB))
    parser.add_argument("--out-requests", default=str(OUT_REQUESTS))
    parser.add_argument("--out-report", default=str(OUT_REPORT))
    args = parser.parse_args()

    events = load_json(Path(args.public_events), [])
    source_map = load_source_map(Path(args.source_map))
    payload, report = build_payload(events, Path(args.master_db), source_map=source_map)
    write_json(Path(args.out_requests), payload)
    Path(args.out_report).write_text(render_markdown(report), encoding="utf-8")
    print(
        "public historical reference change requests: "
        f"requests={report['request_count']} issues={report['issue_count']} "
        f"out={args.out_requests}"
    )


if __name__ == "__main__":
    main()
