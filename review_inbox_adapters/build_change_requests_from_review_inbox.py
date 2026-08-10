#!/usr/bin/env python3
"""Bridge staged review_inbox change_request decisions to apply_change_requests.py.

Background: docs/review-inbox-decision-staging.md documents that the review
console's "change_request" staging route (confirm_current_date /
promote_historical_reference / fill_venue) only produces a packet of raw
review_inbox items plus the reviewer's chosen apply_value. It does not itself
build a report_apply/apply_change_requests.py compatible request. No other
script in this repository performed that translation, so reviewed decisions
in this route had no path to Master RDB.

This script performs that translation only. It never touches Master RDB
itself; its output is meant to be passed to
`python3 -m report_apply.apply_change_requests --requests <out>` which
already has its own dry-run/backup/confirmation safeguards.

Scope: only requests that target an existing occurrence via an explicit
occurrence_id are built. New-event registration
(create_current_year_occurrence) is intentionally out of scope -- items that
cannot be matched to an existing occurrence are left for a human to decide
new-registration separately, and are reported in the unresolved list instead
of being silently dropped.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

DEFAULT_STAGED = Path("data/review_console/staged/review_inbox_change_request_decisions.json")
DEFAULT_OUT = Path("data/review_console/staged/rdb_change_requests.json")
DEFAULT_UNRESOLVED_OUT = Path("data/review_console/staged/rdb_change_requests_unresolved.json")

# "新井町会連合会・中野通り桜まつり実行委員会「中野通り桜まつり」" -> "中野通り桜まつり"
BRACKET_NAME_RE = re.compile(r"[「『]([^」』]+)[」』]")
QUOTE_TRANSLATION = str.maketrans({"｢": "「", "｣": "」", "『": "「", "』": "」"})
SCHEDULE_FRAGMENT_RE = re.compile(
    r"\s*(?:\d{4}\s*)?(?:\d{1,2}月\d{1,2}日?|\d{1,2}月\d{1,2}\s*[（(])(?:[^\n]*)$"
)
TRAILING_PUNCT_RE = re.compile(r"[\s。．、,・／/＝=\-~]+$")

# "2026 [V1]\n5/31" or "2025 [L19]\n7/26 - 27"
EVENT_DATE_TEXT_RE = re.compile(
    r"(?P<year>\d{4})[^\n]*\n(?P<month>\d{1,2})/(?P<day>\d{1,2})"
    r"(?:\s*[-〜ｰ]\s*(?P<day2>\d{1,2}))?"
)


def clean_event_name_for_match(raw_name: str) -> str:
    """Extract the most likely event name from a raw collected string.

    Blog-sourced official_source rows often store "organizer name +
    「event name」+ schedule text" as one string. Bracketed text is usually
    the actual event name, so prefer it over the organizer prefix. Falls
    back to schedule-fragment stripping only when there is no bracket.
    """
    text = (raw_name or "").strip().translate(QUOTE_TRANSLATION)
    bracket_matches = BRACKET_NAME_RE.findall(text)
    if bracket_matches:
        candidate = max(bracket_matches, key=len).strip()
        if candidate:
            return candidate
    cleaned = SCHEDULE_FRAGMENT_RE.sub("", text)
    cleaned = TRAILING_PUNCT_RE.sub("", cleaned).strip()
    if cleaned.startswith(("「", "『")) and not cleaned.endswith(("」", "』")):
        # Unmatched opening bracket (closing bracket was cut off along with
        # a schedule fragment, or missing in the source data).
        cleaned = cleaned[1:].strip()
    return cleaned or text


def parse_event_date_text(text: str) -> tuple[str | None, str | None]:
    """Parse official_source's `event_date_text` into ISO (date_start, date_end)."""
    if not text:
        return None, None
    match = EVENT_DATE_TEXT_RE.search(text)
    if not match:
        return None, None
    year = int(match.group("year"))
    month = int(match.group("month"))
    day = int(match.group("day"))
    day2 = match.group("day2")
    try:
        date(year, month, day)
    except ValueError:
        return None, None
    date_start = f"{year:04d}-{month:02d}-{day:02d}"
    date_end = date_start
    if day2:
        try:
            day2_int = int(day2)
            date(year, month, day2_int)
        except ValueError:
            return date_start, date_start
        date_end = f"{year:04d}-{month:02d}-{day2_int:02d}"
    return date_start, date_end


def _occurrence_id_hint(source_item: dict[str, Any]) -> str | None:
    payload = source_item.get("payload") or {}
    candidate = payload.get("observed_candidate") or {}
    key = candidate.get("candidate_key") or ""
    first = key.split("|", 1)[0] if key else ""
    return first if first.startswith("occ_") else None


def _source_block(source_item: dict[str, Any], *, kind: str) -> dict[str, Any]:
    payload = source_item.get("payload") or {}
    url = source_item.get("source_url") or payload.get("source_url") or ""
    memo = (payload.get("memo") or "").strip()
    return {
        "url": url,
        "kind": kind,
        "title": source_item.get("title") or "",
        "text_excerpt": memo[:280] if memo else (source_item.get("title") or ""),
    }


def build_confirm_current_year_date_request(
    staged_row: dict[str, Any], *, current_year: int
) -> tuple[dict[str, Any] | None, str | None]:
    source_item = staged_row["source_item"]
    payload = source_item.get("payload") or {}
    date_start, date_end = parse_event_date_text(payload.get("event_date_text") or "")
    if not date_start:
        return None, "date_parse_failed"
    if not date_start.startswith(str(current_year)):
        return None, f"event_date_not_in_current_year:{date_start}"
    request: dict[str, Any] = {
        "request_id": source_item["inbox_id"],
        "change_type": "confirm_current_year_date",
        "event_year": current_year,
        "date_start": date_start,
        # venue is intentionally omitted here: passing it triggers
        # ensure_venue(), which can silently create a duplicate venue row
        # when the raw venue text does not exactly match an existing one.
        # Venue changes should only happen through the explicit
        # "fill_venue"/update_venue route where a human chose that action.
        "source": _source_block(source_item, kind="official_current_year"),
    }
    # Always set date_end explicitly, even for single-day events. Omitting it
    # leaves event_occurrences.date_end defaulted to date_start while
    # occurrence_dates.date_end stays blank, which the RDB audit flags as
    # date_cache_mismatch.
    request["date_end"] = date_end or date_start
    note = staged_row.get("note") or ""
    if note:
        request["note"] = note
    return request, None


def build_add_historical_reference_request(
    staged_row: dict[str, Any], *, current_year: int
) -> tuple[dict[str, Any] | None, str | None]:
    source_item = staged_row["source_item"]
    payload = source_item.get("payload") or {}
    historical_year = source_item.get("event_year")
    if not historical_year:
        return None, "missing_historical_year"
    if int(historical_year) >= current_year:
        return None, f"historical_year_not_before_current_year:{historical_year}"
    historical_date, _ = parse_event_date_text(payload.get("event_date_text") or "")
    request: dict[str, Any] = {
        "request_id": source_item["inbox_id"],
        "change_type": "add_historical_reference",
        "event_year": current_year,
        "historical_year": int(historical_year),
        "source": _source_block(source_item, kind="official_historical_reference"),
    }
    if historical_date:
        request["historical_date"] = historical_date
    note = staged_row.get("note") or ""
    if note:
        request["note"] = note
    return request, None


def build_update_venue_request(
    staged_row: dict[str, Any], *, current_year: int
) -> tuple[dict[str, Any] | None, str | None]:
    source_item = staged_row["source_item"]
    venue = (source_item.get("venue") or "").strip()
    if not venue:
        return None, "missing_venue"
    request: dict[str, Any] = {
        "request_id": source_item["inbox_id"],
        "change_type": "update_venue",
        "venue": {"name": venue},
        "source": _source_block(source_item, kind="official_current_year"),
    }
    note = staged_row.get("note") or ""
    if note:
        request["note"] = note
    return request, None


BUILDERS = {
    "confirm_current_year_date": build_confirm_current_year_date_request,
    "add_historical_reference": build_add_historical_reference_request,
    "update_venue": build_update_venue_request,
}


def build_requests(
    staged_rows: list[dict[str, Any]], *, current_year: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    requests: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for staged_row in staged_rows:
        source_item = staged_row.get("source_item") or {}
        inbox_id = source_item.get("inbox_id")
        change_type = staged_row.get("change_type")
        builder = BUILDERS.get(change_type)
        if builder is None:
            unresolved.append(
                {
                    "inbox_id": inbox_id,
                    "event_name": source_item.get("event_name"),
                    "reason": f"unsupported_change_type:{change_type}",
                }
            )
            continue
        occurrence_id = _occurrence_id_hint(source_item)
        if not occurrence_id:
            unresolved.append(
                {
                    "inbox_id": inbox_id,
                    "event_name": source_item.get("event_name"),
                    "reason": "missing_occurrence_id",
                }
            )
            continue
        request, reason = builder(staged_row, current_year=current_year)
        if request is None:
            unresolved.append(
                {
                    "inbox_id": inbox_id,
                    "event_name": source_item.get("event_name"),
                    "reason": reason,
                }
            )
            continue
        if request["request_id"] in seen_ids:
            unresolved.append(
                {
                    "inbox_id": inbox_id,
                    "event_name": source_item.get("event_name"),
                    "reason": "duplicate_request_id",
                }
            )
            continue
        seen_ids.add(request["request_id"])
        request["occurrence_id"] = occurrence_id
        requests.append(request)
    return requests, unresolved


def load_staged_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"staged file has no 'rows' list: {path}")
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", type=Path, default=DEFAULT_STAGED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--unresolved-out", type=Path, default=DEFAULT_UNRESOLVED_OUT)
    parser.add_argument("--current-year", type=int, default=2026)
    args = parser.parse_args()

    staged_rows = load_staged_rows(args.staged)
    requests, unresolved = build_requests(staged_rows, current_year=args.current_year)

    if requests:
        write_json(args.out, {"request_type": "rdb_change_requests", "requests": requests})
    if unresolved:
        write_json(args.unresolved_out, {"unresolved_count": len(unresolved), "items": unresolved})

    print(
        "build change requests: "
        f"staged_rows={len(staged_rows)} "
        f"requests_built={len(requests)} "
        f"unresolved={len(unresolved)} "
        f"out={args.out if requests else '(not written, no requests)'} "
        f"unresolved_out={args.unresolved_out if unresolved else '(not written, none unresolved)'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
