#!/usr/bin/env python3
"""Build a July official URL gap report from public JSON and review queues."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


DATA = Path("data")
PUBLIC_EVENTS = DATA / "public/events_public.json"
OFFICIAL_SOURCE_REVIEW = DATA / "official_source_review_candidates.json"
REVIEW_CONSOLE_DECISIONS = DATA / "review_console/decisions.json"
PROMOTIONS = DATA / "july_official_source_promotions.json"
OUT_JSON = DATA / "july_official_url_gap_report.json"
OUT_MD = DATA / "july_official_url_gap_report.md"


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def month_from_iso(value: str) -> int | None:
    if not value or len(value) < 7 or value[4] != "-":
        return None
    try:
        return int(value[5:7])
    except ValueError:
        return None


def is_july_target(event: dict) -> bool:
    start_month = month_from_iso(event.get("date") or "")
    end_month = month_from_iso(event.get("date_end") or "")
    if start_month == 7 or end_month == 7:
        return True
    if event.get("date") or event.get("date_end"):
        return False
    return 7 in (event.get("months") or [])


def has_official_url(event: dict) -> bool:
    return any(
        (source.get("url") or "") and source.get("kind") == "official"
        for source in event.get("source_urls") or []
    )


def source_summary(event: dict) -> str:
    parts = []
    for source in event.get("source_urls") or []:
        parts.append(f"{source.get('kind') or 'web'}:{source.get('url') or ''}")
    return " ; ".join(parts)


def is_july_review_row(row: dict) -> bool:
    text = "\n".join(
        str(row.get(key) or "")
        for key in ("event_month", "event_date_text", "event_name", "memo")
    )
    return "7月" in text or "7/" in text or "-07-" in text


def review_item_id(row: dict) -> str:
    return "official_source:{id}|{url}|{venue}|{event}".format(
        id=row.get("id") or "",
        url=row.get("source_url") or "",
        venue=row.get("venue") or "",
        event=row.get("event_name") or "",
    )


def main() -> int:
    events = [event for event in read_json(PUBLIC_EVENTS, []) if is_july_target(event)]
    gap_events = [event for event in events if not has_official_url(event)]

    review = read_json(OFFICIAL_SOURCE_REVIEW, {"rows": []})
    review_rows = [row for row in review.get("rows") or [] if is_july_review_row(row)]
    decisions = (read_json(REVIEW_CONSOLE_DECISIONS, {"decisions": {}}).get("decisions") or {})
    reviewed_rows = []
    pending_rows = []
    for row in review_rows:
        decision = decisions.get(review_item_id(row), {})
        item = {
            "id": row.get("id"),
            "event_name": row.get("event_name"),
            "venue": row.get("venue"),
            "region": row.get("region"),
            "source_url": row.get("source_url"),
            "suggested_source_type": row.get("suggested_source_type"),
            "console_decision": decision.get("apply_value") or row.get("decision") or "pending",
        }
        if decision:
            reviewed_rows.append(item)
        else:
            pending_rows.append(item)

    promotions = read_json(PROMOTIONS, {"promotions": []})
    promoted = [
        {
            "event_name": row.get("event_name"),
            "source_url": (row.get("after") or {}).get("source_url"),
            "reason": row.get("reason"),
        }
        for row in promotions.get("promotions") or []
    ]

    result = {
        "generated_by": "build_july_official_url_gap_report.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "july_target_event_count": len(events),
            "without_official_url_count": len(gap_events),
            "with_official_url_count": len(events) - len(gap_events),
            "one_shot_promoted_count": len(promoted),
            "official_source_review_july_count": len(review_rows),
            "official_source_review_july_reviewed_count": len(reviewed_rows),
            "official_source_review_july_pending_count": len(pending_rows),
            "remaining_by_public_status": dict(Counter(event.get("public_status") or "" for event in gap_events)),
        },
        "one_shot_promoted": promoted,
        "remaining_without_official_url": [
            {
                "name": event.get("name"),
                "venue": event.get("venue"),
                "area": event.get("area"),
                "date": event.get("date"),
                "date_end": event.get("date_end"),
                "status": event.get("status"),
                "public_status": event.get("public_status"),
                "display_tier": event.get("display_tier"),
                "source_summary": source_summary(event),
            }
            for event in gap_events
        ],
        "official_source_review_july_reviewed": reviewed_rows,
        "official_source_review_july_pending": pending_rows,
    }
    write_json(OUT_JSON, result)
    OUT_MD.write_text(render_markdown(result), encoding="utf-8")
    print(
        "july official URL gap report: "
        f"targets={result['summary']['july_target_event_count']} "
        f"remaining={result['summary']['without_official_url_count']} "
        f"promoted={result['summary']['one_shot_promoted_count']} "
        f"out={OUT_JSON}"
    )
    return 0


def render_markdown(result: dict) -> str:
    summary = result["summary"]
    lines = [
        "# July official URL gap report",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- july_target_event_count: {summary['july_target_event_count']}",
        f"- with_official_url_count: {summary['with_official_url_count']}",
        f"- without_official_url_count: {summary['without_official_url_count']}",
        f"- one_shot_promoted_count: {summary['one_shot_promoted_count']}",
        f"- official_source_review_july_count: {summary['official_source_review_july_count']}",
        f"- official_source_review_july_reviewed_count: {summary['official_source_review_july_reviewed_count']}",
        f"- official_source_review_july_pending_count: {summary['official_source_review_july_pending_count']}",
        f"- remaining_by_public_status: {summary['remaining_by_public_status']}",
        "",
        "## One-shot promoted",
        "",
        "| event | source_url | reason |",
        "| --- | --- | --- |",
    ]
    for row in result["one_shot_promoted"]:
        lines.append(f"| {row['event_name']} | {row['source_url']} | {row['reason']} |")

    lines.extend(
        [
            "",
            "## Remaining without official URL",
            "",
            "| public_status | area | event | venue | date | source summary |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for event in result["remaining_without_official_url"]:
        date = event.get("date") or ""
        if event.get("date_end") and event.get("date_end") != date:
            date = f"{date} to {event['date_end']}" if date else event["date_end"]
        lines.append(
            "| {status} | {area} | {name} | {venue} | {date} | {sources} |".format(
                status=event.get("public_status") or "",
                area=event.get("area") or "",
                name=event.get("name") or "",
                venue=event.get("venue") or "",
                date=date,
                sources=(event.get("source_summary") or "").replace("|", "\\|"),
            )
        )

    lines.extend(
        [
            "",
            "## July official source review rows",
            "",
            "| state | suggested | area | event | venue | url |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for state, rows in (
        ("reviewed", result["official_source_review_july_reviewed"]),
        ("pending", result["official_source_review_july_pending"]),
    ):
        for row in rows:
            lines.append(
                "| {state} | {suggested} | {area} | {event} | {venue} | {url} |".format(
                    state=state,
                    suggested=row.get("suggested_source_type") or "",
                    area=row.get("region") or "",
                    event=(row.get("event_name") or "").replace("|", "\\|"),
                    venue=(row.get("venue") or "").replace("|", "\\|"),
                    url=row.get("source_url") or "",
                )
            )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
