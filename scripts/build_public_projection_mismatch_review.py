#!/usr/bin/env python3
"""Build a review table for public projection mismatches.

The main use is C-phase historical date mismatches: show the public JSON date
and source beside the Master RDB historical date and source so a reviewer can
decide which side is correct.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_COMPARE = Path("data/public_projection_readiness/public_projection_after_historical_dry_run.json")
DEFAULT_PUBLIC_EVENTS = Path("data/public_projection_readiness/fresh_public/events_public.json")
OUT_JSON = Path("data/public_projection_mismatch_review.json")
OUT_MD = Path("data/public_projection_mismatch_review.md")


def load_json(path: Path, default: Any) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def event_lookup(public_events: list[dict]) -> dict[tuple[str, str], dict]:
    return {(event.get("name") or "", event.get("venue") or ""): event for event in public_events}


def public_sources(event: dict) -> list[dict]:
    out = []
    for source in event.get("source_urls") or []:
        if not source.get("url"):
            continue
        out.append(
            {
                "label": source.get("label") or "",
                "url": source.get("url"),
            }
        )
    return out


def build_rows(compare_report: dict, public_events: list[dict], statuses: set[str]) -> list[dict]:
    events_by_key = event_lookup(public_events)
    rows = []
    for row in compare_report.get("blocking_rows") or []:
        historical = row.get("historical_reference") or {}
        if historical.get("status") not in statuses:
            continue
        event = events_by_key.get((row.get("name") or "", row.get("venue") or ""), {})
        reference = event.get("historical_reference") or {}
        rows.append(
            {
                "issue_type": f"historical:{historical.get('status')}",
                "name": row.get("name"),
                "venue": row.get("venue"),
                "occurrence_id": row.get("occurrence_id"),
                "public": {
                    "dates": historical.get("public_dates") or reference.get("last_seen_dates") or [],
                    "last_seen_year": reference.get("last_seen_year") or event.get("last_seen_year"),
                    "label": event.get("historical_reference_label") or event.get("public_note") or "",
                    "sources": public_sources(event),
                },
                "rdb": {
                    "dates": historical.get("rdb_dates") or [],
                    "sources": historical.get("rdb_sources") or [],
                },
                "decision": "",
                "review_note": "",
            }
        )
    return rows


def render_markdown(payload: dict) -> str:
    lines = [
        "# Public Projection Mismatch Review",
        "",
        f"- generated_by: {payload['generated_by']}",
        f"- compare_report: `{payload['sources']['compare_report']}`",
        f"- public_events: `{payload['sources']['public_events']}`",
        f"- row_count: {payload['row_count']}",
        "",
        "| issue | event | public dates | public sources | RDB dates | RDB sources | decision |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in payload["rows"]:
        public_sources_text = "<br>".join(
            f"{source.get('label') or 'source'}: {source.get('url')}" for source in row["public"]["sources"]
        )
        rdb_sources_text = "<br>".join(
            f"{source.get('source_title') or source.get('source_id') or 'source'}: {source.get('source_url') or ''}"
            for source in row["rdb"]["sources"]
        )
        event = f"{row['name']} / {row['venue']}"
        lines.append(
            "| {issue} | {event} | {public_dates} | {public_sources} | {rdb_dates} | {rdb_sources} |  |".format(
                issue=row["issue_type"],
                event=event,
                public_dates=", ".join(row["public"]["dates"]),
                public_sources=public_sources_text,
                rdb_dates=", ".join(row["rdb"]["dates"]),
                rdb_sources=rdb_sources_text,
            )
        )
    lines.append("")
    return "\n".join(lines)


def parse_statuses(values: list[str]) -> set[str]:
    return {value.split(":", 1)[-1] for value in values}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a public projection mismatch review table.")
    parser.add_argument("--compare-report", type=Path, default=DEFAULT_COMPARE)
    parser.add_argument("--public-events", type=Path, default=DEFAULT_PUBLIC_EVENTS)
    parser.add_argument(
        "--status",
        action="append",
        default=["date_mismatch"],
        help="historical status to include; repeatable. Default: date_mismatch",
    )
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    compare_report = load_json(args.compare_report, {})
    public_events = load_json(args.public_events, [])
    rows = build_rows(compare_report, public_events, parse_statuses(args.status))
    payload = {
        "generated_by": "scripts/build_public_projection_mismatch_review.py",
        "sources": {
            "compare_report": str(args.compare_report),
            "public_events": str(args.public_events),
        },
        "statuses": sorted(parse_statuses(args.status)),
        "row_count": len(rows),
        "rows": rows,
    }
    write_json(args.out_json, payload)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(render_markdown(payload), encoding="utf-8")
    print(f"public projection mismatch review: rows={len(rows)} out={args.out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
