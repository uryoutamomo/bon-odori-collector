#!/usr/bin/env python3
"""Audit retrospective event apply plans against local event and venue exports."""

import argparse
import json
import re
from pathlib import Path

from event_evidence import normalize_event_name


DEFAULT_PLAN = Path("data/retrospective_event_apply_plan.json")
DEFAULT_EVENTS = Path("data/public/events_public.json")
DEFAULT_VENUES = Path("data/venue_master.json")
DEFAULT_OUT = Path("data/retrospective_event_apply_audit.json")
DEFAULT_MD = Path("data/retrospective_event_apply_audit.md")


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def norm(value):
    value = str(value or "")
    value = re.sub(r"第?\d+回", "", value)
    value = re.sub(r"20\d{2}年?", "", value)
    value = re.sub(r"[\s　\"'“”‘’「」『』【】\[\]（）()・、。!！?？:：/／\\|｜~〜\-‐‑–—_]+", "", value)
    return value.casefold()


def month_from_date(value):
    match = re.match(r"20\d{2}-(\d{2})-", str(value or ""))
    return match.group(1) if match else ""


def month_set(event):
    months = set()
    for value in event.get("months") or []:
        try:
            months.add(f"{int(value):02d}")
        except (TypeError, ValueError):
            pass
    date_month = month_from_date(event.get("date"))
    if date_month:
        months.add(date_month)
    return months


def candidate_month(row):
    value = month_from_date(row.get("estimated_date"))
    if value:
        return value
    try:
        return f"{int(row.get('month')):02d}" if row.get("month") else ""
    except (TypeError, ValueError):
        return ""


def venue_exists(row, venues):
    candidate = norm(row.get("venue"))
    if not candidate:
        return False, []
    matches = [
        venue for venue in venues
        if candidate == norm(venue.get("venue")) or candidate in norm(venue.get("venue")) or norm(venue.get("venue")) in candidate
    ]
    return bool(matches), [venue.get("venue") for venue in matches[:5]]


def duplicate_matches(row, events):
    name = norm(row.get("event_name"))
    normalized = norm(normalize_event_name(row.get("event_name")))
    venue = norm(row.get("venue"))
    month = candidate_month(row)
    matches = []
    for event in events:
        event_name = norm(event.get("name"))
        event_normalized = norm(normalize_event_name(event.get("name")))
        event_venue = norm(event.get("venue"))
        event_months = month_set(event)
        reasons = []
        if name and name == event_name:
            reasons.append("event_name_exact")
        elif normalized and normalized == event_normalized:
            reasons.append("event_name_normalized")
        elif name and event_name and (name in event_name or event_name in name):
            reasons.append("event_name_contains")
        if venue and event_venue and (venue == event_venue or venue in event_venue or event_venue in venue):
            reasons.append("venue_overlap")
        if month and month in event_months:
            reasons.append("month_overlap")
        strong = {"event_name_exact", "event_name_normalized"} & set(reasons)
        venue_month = {"venue_overlap", "month_overlap"} <= set(reasons)
        name_month = {"event_name_contains", "month_overlap"} <= set(reasons)
        if strong or venue_month or name_month or ({"event_name_contains", "venue_overlap"} <= set(reasons)):
            matches.append({
                "name": event.get("name"),
                "venue": event.get("venue"),
                "date": event.get("date") or "",
                "status": event.get("status") or "",
                "reasons": reasons,
            })
    return matches[:8]


def suspicious_flags(row, venue_ok):
    name = row.get("event_name") or ""
    flags = []
    if not row.get("venue"):
        flags.append("missing_venue")
    elif not venue_ok:
        flags.append("venue_not_in_master")
    if not row.get("estimated_date"):
        flags.append("missing_date")
    if re.search(r"(?:最も早い|古くから伝わる|街が一体|感じながら|厳かな|伝統的|午後\d|から)", name):
        flags.append("descriptive_name")
    if re.match(r"^\d|^(?:は|と|の|ここから|たぶん)", name):
        flags.append("bad_prefix")
    return flags


def severity(row, duplicates, flags):
    if duplicates:
        return "duplicate_check"
    if "missing_venue" in flags or "venue_not_in_master" in flags or "descriptive_name" in flags:
        return "needs_fix"
    if "missing_date" in flags:
        return "needs_date"
    return "looks_ready"


def build_audit(plan, events, venues):
    rows = []
    for row in plan.get("ready_for_apply") or []:
        venue_ok, venue_matches = venue_exists(row, venues)
        duplicates = duplicate_matches(row, events)
        flags = suspicious_flags(row, venue_ok)
        rows.append({
            "candidate_key": row.get("candidate_key"),
            "event_name": row.get("event_name"),
            "venue": row.get("venue"),
            "estimated_date": row.get("estimated_date"),
            "source_url": row.get("source_url"),
            "severity": severity(row, duplicates, flags),
            "flags": flags,
            "venue_matches": venue_matches,
            "duplicate_matches": duplicates,
        })
    counts = {}
    for row in rows:
        counts[row["severity"]] = counts.get(row["severity"], 0) + 1
    return {
        "generated_by": "audit_retrospective_event_apply_plan.py",
        "source": str(DEFAULT_PLAN),
        "ready_for_apply_count": len(rows),
        "counts": dict(sorted(counts.items())),
        "rows": rows,
    }


def markdown(audit):
    lines = [
        "# Retrospective event apply audit",
        "",
        f"- ready_for_apply_count: {audit['ready_for_apply_count']}",
        "",
        "## Counts",
        "",
    ]
    for key, value in audit.get("counts", {}).items():
        lines.append(f"- {key}: {value}")
    lines += [
        "",
        "## Rows",
        "",
        "| severity | event | venue | date | flags | duplicate candidates |",
        "|---|---|---|---|---|---|",
    ]
    for row in audit.get("rows", []):
        dupes = "; ".join(
            f"{item.get('name')} / {item.get('venue')} / {item.get('date')} [{','.join(item.get('reasons') or [])}]"
            for item in row.get("duplicate_matches") or []
        )
        lines.append(
            "| {severity} | {event} | {venue} | {date} | {flags} | {dupes} |".format(
                severity=row.get("severity", ""),
                event=(row.get("event_name") or "").replace("|", " "),
                venue=(row.get("venue") or "").replace("|", " "),
                date=row.get("estimated_date") or "",
                flags=", ".join(row.get("flags") or []),
                dupes=dupes.replace("|", " "),
            )
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--venues", type=Path, default=DEFAULT_VENUES)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--md-out", type=Path, default=DEFAULT_MD)
    args = parser.parse_args()

    audit = build_audit(load_json(args.plan, {}), load_json(args.events, []), load_json(args.venues, []))
    audit["source"] = str(args.plan)
    write_json(args.out, audit)
    write_text(args.md_out, markdown(audit))
    print(f"retrospective event apply audit: ready={audit['ready_for_apply_count']} counts={audit['counts']} -> {args.out}")


if __name__ == "__main__":
    main()
