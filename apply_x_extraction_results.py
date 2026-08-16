#!/usr/bin/env python3
"""Validate untrusted X extraction answers and persist deterministic observations."""
from __future__ import annotations

import argparse
import json
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

from build_x_extraction_packets import normalized_text
from master_rdb.master_db import normalize_text, stable_id


CLAIM_TYPES = {"announced", "observed", "mentioned", "unknown"}
SONG_ISSUE_TYPES = {
    "malformed_observation",
    "empty_song_name",
    "song_not_in_text",
    "invalid_claim_type",
    "malformed_claim_quote",
    "empty_claim_quote",
    "claim_quote_not_in_text",
    "song_not_in_claim_quote",
    "event_quote_not_in_text",
    "event_date_invalid",
    "event_date_not_in_text",
    "event_date_range_invalid",
    "event_venue_not_in_text",
    "event_ward_not_in_text",
    "malformed_event_context",
    "claim_type_conflict",
}
GLOSSARY_ISSUE_TYPES = {"malformed_glossary", "malformed_term", "empty_term", "term_not_in_text"}


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _issue(issues, kind, **extra):
    issues.append({"issue_type": kind, **extra})


def _add_url(detail: str, url: str) -> str:
    line = f"- 出典URL: {url}"
    return detail if line in detail else detail.rstrip() + "\n" + line


def _detail(note: str, packet: dict) -> str:
    if packet.get("officiality") == "registered_official_social":
        who = packet.get("account_name") or packet.get("account") or "公式アカウント"
        prefix = f"出典：{who}のX投稿。"
    else:
        prefix = "現地の告知投稿で開催を確認。"
    return _add_url((prefix + (note if note else "")).strip(), packet.get("url") or "")


def _material_text(value: str) -> str:
    """Normalize only the variants allowed by E0X-S v1.1.

    NFKC folds full-width ASCII. Middle dots, prolonged sound marks, URLs and
    whitespace are ignored. Hiragana and katakana intentionally stay distinct.
    """
    value = unicodedata.normalize("NFKC", str(value or ""))
    return normalized_text(value).replace("・", "").replace("ー", "")


def _appears_in_text(value: str, text: str) -> bool:
    needle = _material_text(value)
    return bool(needle) and needle in _material_text(text)


def _event_report_id(event: dict) -> str:
    """Return the one report ID used by both E0 output and song lineage."""
    return "x_event_" + stable_id(
        "xevent",
        normalize_text(event.get("event_name") or ""),
        event.get("date_start") or "",
        normalize_text(event.get("venue_name") or ""),
    )


def _report_event_id(report_id: str) -> str:
    """Identify one event element inside a report, not merely the report file."""
    # E0X currently emits exactly one event element per report. Keep this key
    # stable when a later bundled post adds detail such as date_end.
    return stable_id("xrevent", report_id, "0")


def _legacy_report_event_id(entry: dict) -> str:
    """Preserve the family key E0 used before reports carried entry_id."""
    venue = entry.get("venue") if isinstance(entry.get("venue"), dict) else {}
    return stable_id(
        "entry",
        normalize_text(entry.get("event_name_hint") or ""),
        str(entry.get("event_year") or ""),
        venue.get("name") or "",
        length=12,
    )


def _reusable_x_event_report(report: dict, report_id: str) -> tuple[dict | None, str | None]:
    """Validate the minimum E0 contract before reusing report lineage."""
    if report.get("report_type") != "official_notice":
        return None, "report_type"
    source = report.get("source") if isinstance(report.get("source"), dict) else {}
    if source.get("report_id") != report_id:
        return None, "report_id"
    if not source.get("raw_text") or not source.get("url"):
        return None, "source"
    events = report.get("events")
    if not isinstance(events, list) or not events or not isinstance(events[0], dict):
        return None, "events"
    entry = events[0]
    venue = entry.get("venue") if isinstance(entry.get("venue"), dict) else {}
    has_identity = bool(entry.get("entry_id")) or bool(
        entry.get("event_name_hint") and entry.get("event_year") and venue.get("name")
    )
    if entry.get("action") != "register_new" or not has_identity:
        return None, "event_identity"
    return entry, None


def _optional_text(value, *, no, origin: str, field: str, issues: list[dict]) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        _issue(issues, "malformed_event_context", no=no, origin=origin, field=field)
        return None
    text = value.strip()
    return text or None


def _claim_type(value, *, no, origin: str, song_index: int, issues: list[dict]) -> str:
    if isinstance(value, str) and value in CLAIM_TYPES:
        return value
    _issue(issues, "invalid_claim_type", no=no, origin=origin, song_index=song_index)
    return "unknown"


def _validate_observation_event_context(
    *,
    item: dict,
    no,
    origin: str,
    event_name: str | None,
    date_start: str | None,
    date_end: str | None,
    venue_name: str | None,
    ward: str | None,
    event_quote: str | None,
    issues: list[dict],
) -> tuple[bool, bool]:
    """Return (event_name_in_text, locally_verified_context)."""
    text = str(item.get("text") or "")
    event_name_in_text = bool(event_name and _appears_in_text(event_name, text))
    valid = True

    machine_dates = item.get("machine_extracted_dates")
    machine_dates = machine_dates if isinstance(machine_dates, list) else []
    parsed_dates: list[date] = []
    for field, value in (("event_date_start", date_start), ("event_date_end", date_end)):
        if value is None:
            continue
        try:
            parsed_dates.append(date.fromisoformat(value))
        except ValueError:
            _issue(issues, "event_date_invalid", no=no, origin=origin, field=field, value=value)
            valid = False
            continue
        if value not in machine_dates:
            _issue(issues, "event_date_not_in_text", no=no, origin=origin, field=field, value=value)
            valid = False
    if date_end and not date_start:
        _issue(issues, "event_date_range_invalid", no=no, origin=origin)
        valid = False
    if len(parsed_dates) == 2 and parsed_dates[1] < parsed_dates[0]:
        _issue(issues, "event_date_range_invalid", no=no, origin=origin)
        valid = False
    if venue_name and not _appears_in_text(venue_name, text):
        _issue(issues, "event_venue_not_in_text", no=no, origin=origin)
        valid = False
    if ward and not _appears_in_text(ward, text):
        _issue(issues, "event_ward_not_in_text", no=no, origin=origin)
        valid = False
    if event_quote and not _appears_in_text(event_quote, text):
        _issue(issues, "event_quote_not_in_text", no=no, origin=origin)
        valid = False

    has_anchor = bool(date_start or venue_name or event_quote)
    return event_name_in_text, bool(valid and event_name_in_text and has_anchor)


def _song_rows(ledger: dict) -> list[dict]:
    rows = ledger.get("observations")
    if not isinstance(rows, list):
        rows = []
        ledger["observations"] = rows
    return rows


def _normalize_song_rows(rows: list[dict]) -> None:
    """Add read-time v2 defaults without changing legacy IDs or row count."""
    defaults = {
        "claim_family_id": None,
        "event_name_in_text": None,
        "event_report_verified": False,
        "claim_type": "unknown",
        "evidence_quote": None,
        "event_date_start": None,
        "event_date_end": None,
        "event_venue_name": None,
        "event_ward": None,
        "event_quote": None,
        "event_context_valid": None,
        "event_report_id": None,
        "report_event_id": None,
        "event_dependency_key": None,
        "claim_type_conflict": False,
    }
    for row in rows:
        if not isinstance(row, dict):
            continue
        row.setdefault("observation_schema_version", 1)
        for key, value in defaults.items():
            row.setdefault(key, value)


def _claim_counts(rows: list[dict]) -> dict[str, int]:
    counts = {claim_type: 0 for claim_type in sorted(CLAIM_TYPES)}
    for row in rows:
        if not isinstance(row, dict):
            continue
        claim_type = row.get("claim_type")
        if claim_type not in CLAIM_TYPES:
            claim_type = "unknown"
        counts[claim_type] += 1
    return counts


def _claim_route_key(tweet_id, event_name, song_name, evidence_quote, claim_type) -> str:
    """Deduplicate the same v2 claim repeated across answer routes."""
    return stable_id(
        "xsroute",
        tweet_id or "",
        _material_text(event_name or ""),
        _material_text(song_name or ""),
        _material_text(evidence_quote or ""),
        claim_type or "unknown",
    )


def _claim_conflict_families(rows: list[dict]) -> set[str]:
    families: dict[str, list[dict]] = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("claim_family_id"), str):
            families.setdefault(row["claim_family_id"], []).append(row)
    return {
        family_id
        for family_id, family_rows in families.items()
        if len({row.get("claim_type") for row in family_rows}) > 1
    }


def _mark_claim_conflicts(
    rows: list[dict], issues: list[dict], *, initial_conflicts: set[str]
) -> set[str]:
    conflicts = _claim_conflict_families(rows)
    families: dict[str, list[dict]] = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("claim_family_id"), str):
            families.setdefault(row["claim_family_id"], []).append(row)
    for family_id, family_rows in families.items():
        claim_types = {row.get("claim_type") for row in family_rows}
        conflict = family_id in conflicts
        for row in family_rows:
            row["claim_type_conflict"] = conflict
        if conflict and family_id not in initial_conflicts:
            _issue(
                issues,
                "claim_type_conflict",
                claim_family_id=family_id,
                claim_types=sorted(str(value) for value in claim_types),
            )
    return conflicts


def _glossary_rows(ledger: dict) -> list[dict]:
    rows = ledger.get("terms")
    if not isinstance(rows, list):
        rows = []
        ledger["terms"] = rows
    return rows


def _record_song_group(
    *,
    item: dict,
    no,
    event_name,
    claims,
    origin: str,
    event_context: dict,
    dependency: dict | None,
    score: int | None,
    batch_id,
    stamp: str,
    issues: list[dict],
    rows: list[dict],
    existing_ids: set[str],
    event_claim_keys: set[str],
) -> int:
    if event_name is not None and not isinstance(event_name, str):
        _issue(issues, "malformed_observation", no=no, origin=origin)
        return 0
    if not isinstance(claims, list):
        _issue(issues, "malformed_observation", no=no, origin=origin)
        return 0

    event_value = event_name.strip() if isinstance(event_name, str) else None
    text = str(item.get("text") or "")
    issue_start = len(issues)
    event_date_start = _optional_text(
        event_context.get("date_start"), no=no, origin=origin, field="event_date_start", issues=issues
    )
    event_date_end = _optional_text(
        event_context.get("date_end"), no=no, origin=origin, field="event_date_end", issues=issues
    )
    event_venue_name = _optional_text(
        event_context.get("venue_name"), no=no, origin=origin, field="event_venue_name", issues=issues
    )
    event_ward = _optional_text(
        event_context.get("ward"), no=no, origin=origin, field="event_ward", issues=issues
    )
    event_quote = _optional_text(
        event_context.get("event_quote"), no=no, origin=origin, field="event_quote", issues=issues
    )
    event_context_well_typed = not any(
        row.get("issue_type") == "malformed_event_context" for row in issues[issue_start:]
    )
    dependency = dependency if isinstance(dependency, dict) else {}
    event_name_in_text, event_context_valid = _validate_observation_event_context(
        item=item,
        no=no,
        origin=origin,
        event_name=event_value,
        date_start=event_date_start,
        date_end=event_date_end,
        venue_name=event_venue_name,
        ward=event_ward,
        event_quote=event_quote,
        issues=issues,
    )
    event_context_valid = bool(event_context_well_typed and event_context_valid)
    added = 0
    for song_index, raw_claim in enumerate(claims):
        legacy = isinstance(raw_claim, str)
        if legacy:
            raw_song = raw_claim
            claim_type = "unknown"
            evidence_quote = None
        elif isinstance(raw_claim, dict):
            raw_song = raw_claim.get("song_name")
            claim_type = _claim_type(
                raw_claim.get("claim_type"),
                no=no,
                origin=origin,
                song_index=song_index,
                issues=issues,
            )
            raw_quote = raw_claim.get("evidence_quote")
            if not isinstance(raw_quote, str):
                _issue(issues, "malformed_claim_quote", no=no, origin=origin, song_index=song_index)
                continue
            evidence_quote = raw_quote.strip()
            if not evidence_quote:
                _issue(issues, "empty_claim_quote", no=no, origin=origin, song_index=song_index)
                continue
        else:
            raw_song = None
            claim_type = "unknown"
            evidence_quote = None

        if not isinstance(raw_song, str) or not raw_song.strip():
            _issue(issues, "empty_song_name", no=no, origin=origin, song_index=song_index)
            continue
        song_name = raw_song.strip()
        if not _appears_in_text(song_name, text):
            _issue(issues, "song_not_in_text", no=no, origin=origin, song_name=song_name)
            continue
        if not legacy:
            if not _appears_in_text(evidence_quote or "", text):
                _issue(
                    issues,
                    "claim_quote_not_in_text",
                    no=no,
                    origin=origin,
                    song_index=song_index,
                    song_name=song_name,
                )
                continue

            if not _appears_in_text(song_name, evidence_quote or ""):
                _issue(
                    issues,
                    "song_not_in_claim_quote",
                    no=no,
                    origin=origin,
                    song_index=song_index,
                    song_name=song_name,
                )
                continue
            route_key = _claim_route_key(
                item.get("tweet_id"), event_value, song_name, evidence_quote, claim_type
            )
            if origin == "observations" and route_key in event_claim_keys:
                continue
            if origin == "events":
                event_claim_keys.add(route_key)

        if legacy:
            # Preserve the v1 identity so the existing observations are not duplicated.
            claim_family_id = None
            observation_id = stable_id(
                "xsong",
                item.get("tweet_id") or "",
                _material_text(event_value or ""),
                _material_text(song_name),
            )
        else:
            claim_family_id = stable_id(
                "xsclaim",
                item.get("tweet_id") or "",
                _material_text(event_value or ""),
                event_date_start or "",
                event_date_end or "",
                _material_text(event_venue_name or ""),
                _material_text(event_ward or ""),
                _material_text(song_name),
            )
            observation_id = stable_id("xsong2", claim_family_id, claim_type)
        if observation_id in existing_ids:
            continue
        rows.append({
            "observation_schema_version": 1 if legacy else 2,
            "observation_id": observation_id,
            "claim_family_id": claim_family_id,
            "tweet_id": item.get("tweet_id") or "",
            "url": item.get("url") or "",
            "posted_at": item.get("posted_at") or "",
            "account": item.get("account") or "",
            "officiality": item.get("officiality") or "",
            "event_name": event_value,
            "event_name_in_text": event_name_in_text,
            "event_report_verified": bool(dependency),
            "song_name": song_name,
            "claim_type": claim_type,
            "evidence_quote": evidence_quote,
            "origin": origin,
            "event_date_start": event_date_start,
            "event_date_end": event_date_end,
            "event_venue_name": event_venue_name,
            "event_ward": event_ward,
            "event_quote": event_quote,
            "event_context_valid": event_context_valid,
            "event_report_id": dependency.get("event_report_id"),
            "report_event_id": dependency.get("report_event_id"),
            "event_dependency_key": dependency.get("event_dependency_key"),
            "claim_type_conflict": False,
            "batch_id": batch_id,
            "score": score,
            "text": text,
            "first_seen_at": stamp,
        })
        existing_ids.add(observation_id)
        added += 1
    return added


def _record_glossary(
    *,
    item: dict,
    no,
    glossary,
    stamp: str,
    issues: list[dict],
    rows: list[dict],
) -> set[str]:
    if not isinstance(glossary, list):
        _issue(issues, "malformed_glossary", no=no)
        return set()

    by_term = {
        row.get("term"): row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("term"), str)
    }
    accepted: set[str] = set()
    tweet_id = str(item.get("tweet_id") or "")
    text = str(item.get("text") or "")
    for term_index, raw_term in enumerate(glossary):
        if not isinstance(raw_term, str):
            _issue(issues, "malformed_term", no=no, term_index=term_index)
            continue
        term = raw_term.strip()
        if not term:
            _issue(issues, "empty_term", no=no, term_index=term_index)
            continue
        if not _appears_in_text(term, text):
            _issue(issues, "term_not_in_text", no=no, term=term)
            continue
        accepted.add(term)
        row = by_term.get(term)
        if row is None:
            row = {
                "term": term,
                "source_tweet_ids": [],
                "count": 0,
                "first_seen_at": stamp,
                "last_seen_at": stamp,
                "examples": [],
            }
            rows.append(row)
            by_term[term] = row

        source_ids = row.get("source_tweet_ids")
        if not isinstance(source_ids, list):
            source_ids = []
            row["source_tweet_ids"] = source_ids
        if tweet_id not in source_ids:
            source_ids.append(tweet_id)
            row["last_seen_at"] = stamp
            examples = row.get("examples")
            if not isinstance(examples, list):
                examples = []
                row["examples"] = examples
            if len(examples) < 5:
                examples.append({"tweet_id": tweet_id, "url": item.get("url") or "", "text": text})
        # count is deliberately derived; it must never drift from source_tweet_ids.
        row["count"] = len(source_ids)
    return accepted


def _record_materials(
    result: dict,
    item: dict,
    no,
    score: int | None,
    batch_id,
    stamp: str,
    issues: list[dict],
    song_ledger: dict,
    glossary_ledger: dict,
    event_dependencies: dict[int, dict],
) -> tuple[int, set[str]]:
    song_rows = _song_rows(song_ledger)
    existing_ids = {
        row.get("observation_id")
        for row in song_rows
        if isinstance(row, dict) and row.get("observation_id")
    }
    event_claim_keys = {
        _claim_route_key(
            row.get("tweet_id"),
            row.get("event_name"),
            row.get("song_name"),
            row.get("evidence_quote"),
            row.get("claim_type"),
        )
        for row in song_rows
        if isinstance(row, dict)
        and row.get("observation_schema_version") == 2
        and row.get("origin") == "events"
    }
    new_songs = 0

    # `origin` records the answer route only. Meaning lives in each claim_type.
    events = result.get("events")
    if isinstance(events, list):
        for event_index, event in enumerate(events):
            if isinstance(event, dict) and ("song_claims" in event or "songs" in event):
                new_songs += _record_song_group(
                    item=item,
                    no=no,
                    event_name=event.get("event_name"),
                    claims=event.get("song_claims", event.get("songs")),
                    origin="events",
                    event_context={
                        "date_start": event.get("date_start"),
                        "date_end": event.get("date_end") or event.get("date_start"),
                        "venue_name": event.get("venue_name"),
                        "ward": event.get("ward"),
                        "event_quote": event.get("quote"),
                    },
                    dependency=event_dependencies.get(event_index),
                    score=score,
                    batch_id=batch_id,
                    stamp=stamp,
                    issues=issues,
                    rows=song_rows,
                    existing_ids=existing_ids,
                    event_claim_keys=event_claim_keys,
                )

    if "observations" in result:
        observations = result.get("observations")
        if not isinstance(observations, list):
            _issue(issues, "malformed_observation", no=no, origin="observations")
        else:
            for observation in observations:
                if not isinstance(observation, dict):
                    _issue(issues, "malformed_observation", no=no, origin="observations")
                    continue
                new_songs += _record_song_group(
                    item=item,
                    no=no,
                    event_name=observation.get("event_name"),
                    claims=observation.get("song_claims", observation.get("songs")),
                    origin="observations",
                    event_context={
                        "date_start": observation.get("event_date_start"),
                        "date_end": observation.get("event_date_end") or observation.get("event_date_start"),
                        "venue_name": observation.get("venue_name"),
                        "ward": observation.get("ward"),
                        "event_quote": observation.get("event_quote"),
                    },
                    dependency=None,
                    score=score,
                    batch_id=batch_id,
                    stamp=stamp,
                    issues=issues,
                    rows=song_rows,
                    existing_ids=existing_ids,
                    event_claim_keys=event_claim_keys,
                )

    accepted_terms: set[str] = set()
    if "glossary" in result:
        accepted_terms = _record_glossary(
            item=item,
            no=no,
            glossary=result.get("glossary"),
            stamp=stamp,
            issues=issues,
            rows=_glossary_rows(glossary_ledger),
        )
    return new_songs, accepted_terms


def apply(
    packet: dict,
    answer: dict,
    state: dict,
    reports_dir: Path,
    *,
    song_ledger: dict | None = None,
    glossary_ledger: dict | None = None,
    today: date | None = None,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    # Preserve the existing local-calendar cutoff for event dates. `now` is UTC
    # because it is only used for persisted timestamps.
    today = today or date.today()
    stamp = now.isoformat()
    issues: list[dict] = []
    reports: list[str] = []
    scores: list[dict] = []
    song_ledger = song_ledger if isinstance(song_ledger, dict) else {}
    glossary_ledger = glossary_ledger if isinstance(glossary_ledger, dict) else {}
    song_ledger.update({
        "schema_version": 2,
        "generated_by": "apply_x_extraction_results.py",
        "updated_at": stamp,
    })
    glossary_ledger.update({"generated_by": "apply_x_extraction_results.py", "updated_at": stamp})
    initial_song_rows = _song_rows(song_ledger)
    _normalize_song_rows(initial_song_rows)
    initial_claim_counts = _claim_counts(initial_song_rows)
    initial_claim_conflicts = _claim_conflict_families(initial_song_rows)

    if "tweets" not in state:
        state["tweets"] = {key: value for key, value in state.items() if isinstance(value, dict)}
    state_rows = state["tweets"]
    by_no = {item["no"]: item for item in packet.get("packets", [])}
    answers = {}
    if answer.get("batch_id") != packet.get("batch_id"):
        _issue(issues, "batch_id_mismatch")
    raw_results = answer.get("results", [])
    if not isinstance(raw_results, list):
        _issue(issues, "malformed_results")
        raw_results = []
    for result in raw_results:
        if not isinstance(result, dict):
            _issue(issues, "malformed_result")
            continue
        no = result.get("no")
        if no not in by_no:
            _issue(issues, "unknown_packet", no=no)
            continue
        if no not in answers:
            answers[no] = result

    song_observation_count = 0
    accepted_glossary_terms: set[str] = set()
    reports_dir.mkdir(parents=True, exist_ok=True)
    for no, item in by_no.items():
        result = answers.get(no)
        outcome = "issue"
        if not isinstance(result, dict):
            # Missing answers stay issued so they can be reissued after 24 hours.
            _issue(issues, "missing_result", no=no)
            continue

        score = result.get("s")
        if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5:
            _issue(issues, "invalid_score", no=no)
            score = None
        if score is not None:
            scores.append({
                "batch_id": packet.get("batch_id"),
                "no": no,
                "tweet_id": item["tweet_id"],
                "score": score,
                "note": result.get("n"),
            })

        event_dependencies: dict[int, dict] = {}
        if score is not None and score < 5:
            outcome = "scored_only"
        elif score == 5:
            events = result.get("events")
            if not isinstance(events, list) or not events:
                _issue(issues, "missing_events", no=no)
            else:
                for event_index, event in enumerate(events):
                    if not isinstance(event, dict):
                        _issue(issues, "malformed_event", no=no)
                        continue
                    event_ok = True
                    past = False
                    quote = str(event.get("quote") or "")
                    venue = str(event.get("venue_name") or "")
                    dates = [event.get("date_start"), event.get("date_end") or event.get("date_start")]
                    if not quote or normalized_text(quote) not in normalized_text(item.get("text", "")):
                        _issue(issues, "quote_not_in_text", no=no)
                        event_ok = False
                    if not venue or normalized_text(venue) not in normalized_text(item.get("text", "")):
                        _issue(issues, "venue_not_in_text", no=no)
                        event_ok = False
                    if not item.get("url"):
                        _issue(issues, "missing_source_url", no=no)
                        event_ok = False
                    if not all(isinstance(value, str) and value for value in dates):
                        _issue(issues, "date_not_in_text", no=no)
                        event_ok = False
                        continue
                    if any(value not in item.get("machine_extracted_dates", []) for value in dates):
                        _issue(issues, "date_not_in_text", no=no)
                        event_ok = False
                        continue
                    if dates[1] < dates[0]:
                        _issue(issues, "date_range_invalid", no=no)
                        event_ok = False
                        continue
                    if event_ok:
                        try:
                            past = date.fromisoformat(dates[1]) < today
                        except ValueError:
                            _issue(issues, "date_not_in_text", no=no)
                            event_ok = False
                        if past:
                            _issue(issues, "date_in_past", no=no)
                    if past:
                        continue
                    if event_ok:
                        report_id = _event_report_id(event)
                        event_entry_id = _report_event_id(report_id)
                        path = reports_dir / f"{report_id}.json"
                        if path.exists():
                            report = load(path, {})
                            report_source = report.get("source") if isinstance(report.get("source"), dict) else {}
                            if report_source.get("report_id") != report_id:
                                _issue(issues, "report_id_mismatch", no=no, report_id=report_id)
                                continue
                            existing, invalid_field = _reusable_x_event_report(report, report_id)
                            if existing is None:
                                _issue(
                                    issues,
                                    "malformed_existing_report",
                                    no=no,
                                    report_id=report_id,
                                    field=invalid_field,
                                )
                                continue
                            event_entry_id = existing.get("entry_id") or _legacy_report_event_id(existing)
                            existing["entry_id"] = event_entry_id
                            existing["detail_addendum"] = _add_url(existing.get("detail_addendum", ""), item["url"])
                        else:
                            report = {
                                "report_type": "official_notice",
                                "reported_at": stamp,
                                "source": {
                                    "report_id": report_id,
                                    "title": f"{event.get('event_name')}（X投稿より）",
                                    "account_key": item.get("account") or "",
                                    "url": item.get("url"),
                                    "notice_kind": "x_post",
                                    "raw_text": item.get("text") or "",
                                },
                                "events": [{
                                    "entry_id": event_entry_id,
                                    "action": "register_new",
                                    "event_name_hint": event.get("event_name"),
                                    "event_year": int(event["date_start"][:4]),
                                    "date_start": event["date_start"],
                                    "date_end": event.get("date_end") or event["date_start"],
                                    "venue": {"name": event.get("venue_name"), "area": event.get("ward") or ""},
                                    "detail_addendum": _detail(str(result.get("n") or "").strip(), item),
                                }],
                            }
                        _write(path, report)
                        outcome = "report"
                        reports.append(report_id)
                        event_dependencies[event_index] = {
                            "event_report_id": report_id,
                            "report_event_id": event_entry_id,
                            "event_dependency_key": f"official_notice:{report_id}#{event_entry_id}",
                        }

        # Materials are intentionally recorded after event validation so a
        # report dependency is attached only when that report actually exists.
        added, accepted_terms = _record_materials(
            result,
            item,
            no,
            score,
            packet.get("batch_id"),
            stamp,
            issues,
            song_ledger,
            glossary_ledger,
            event_dependencies,
        )
        song_observation_count += added
        accepted_glossary_terms.update(accepted_terms)

        if outcome != "report" and result.get("s") == 5:
            outcome = (
                "scored_only"
                if any(row.get("issue_type") == "date_in_past" and row.get("no") == no for row in issues)
                else "issue"
            )
        state_rows[item["tweet_id"]] = {
            "issued_at": state_rows.get(item["tweet_id"], {}).get("issued_at"),
            "batch_id": packet.get("batch_id"),
            "applied_at": stamp,
            "outcome": outcome,
        }

    song_rows = _song_rows(song_ledger)
    glossary_rows = _glossary_rows(glossary_ledger)
    claim_conflicts = _mark_claim_conflicts(
        song_rows, issues, initial_conflicts=initial_claim_conflicts
    )
    song_rows.sort(key=lambda row: str(row.get("observation_id") or ""))
    glossary_rows.sort(key=lambda row: str(row.get("term") or ""))
    final_claim_counts = _claim_counts(song_rows)
    added_claim_counts = {
        claim_type: final_claim_counts[claim_type] - initial_claim_counts[claim_type]
        for claim_type in sorted(CLAIM_TYPES)
    }
    song_issue_count = sum(row.get("issue_type") in SONG_ISSUE_TYPES for row in issues)
    glossary_issue_count = sum(row.get("issue_type") in GLOSSARY_ISSUE_TYPES for row in issues)
    return {
        "batch_id": packet.get("batch_id"),
        "score_count": len(scores),
        "report_count": len(set(reports)),
        "bundled_count": len(reports) - len(set(reports)),
        "song_observation_count": song_observation_count,
        "song_claim_type_added": added_claim_counts,
        "song_claim_type_total": final_claim_counts,
        "song_claim_conflict_total": len(claim_conflicts),
        "glossary_term_count": len(accepted_glossary_terms),
        "song_issue_count": song_issue_count,
        "glossary_issue_count": glossary_issue_count,
        "song_observations_total": len(song_rows),
        "glossary_terms_total": len(glossary_rows),
        "issues": issues,
        "scores": scores,
        "reports": sorted(set(reports)),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--state", type=Path, default=Path("data/x_extraction_state.json"))
    parser.add_argument("--reports-dir", type=Path, default=Path("data/x_post_reports"))
    parser.add_argument("--scores", type=Path, default=Path("data/x_post_scores.json"))
    parser.add_argument("--song-observations", type=Path, default=Path("data/x_song_observations.json"))
    parser.add_argument("--glossary-observations", type=Path, default=Path("data/x_glossary_observations.json"))
    parser.add_argument("--out", type=Path, default=Path("data/x_post_extraction_apply_report.json"))
    args = parser.parse_args()

    state = load(args.state, {"tweets": {}})
    song_ledger = load(args.song_observations, {"observations": []})
    glossary_ledger = load(args.glossary_observations, {"terms": []})
    result = apply(
        load(args.packet, {}),
        load(args.results, {}),
        state,
        args.reports_dir,
        song_ledger=song_ledger,
        glossary_ledger=glossary_ledger,
    )
    old_scores = load(args.scores, [])
    _write(args.scores, old_scores + result["scores"])
    _write(args.state, state)
    _write(args.song_observations, song_ledger)
    _write(args.glossary_observations, glossary_ledger)
    _write(args.out, result)
    print(json.dumps({
        "reports": result["report_count"],
        "song_observations": result["song_observation_count"],
        "glossary_terms": result["glossary_term_count"],
        "issues": len(result["issues"]),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
