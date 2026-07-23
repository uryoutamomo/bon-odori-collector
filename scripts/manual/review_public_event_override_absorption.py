"""Review whether public event overrides have been absorbed upstream.

This is read-only. It compares data/public_event_overrides.json with the
master RDB, the current Notion snapshot, and the current public JSON. The goal
is to make explicit which overrides can be removed and which still protect the
current Notion-based export path.
"""

import argparse
import json
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from master_rdb.master_db import MASTER_DB, connect_existing


DATA = Path("data")
OVERRIDES_JSON = DATA / "public_event_overrides.json"
PUBLIC_EVENTS_JSON = DATA / "public" / "events_public.json"
NOTION_SNAPSHOT = DATA / "notion_snapshot.sqlite"
OUT_JSON = DATA / "public_event_override_absorption_review.json"
OUT_MD = DATA / "public_event_override_absorption_review.md"


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rows(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def find_public_event(public_events, match):
    name_match = {}
    for event in public_events:
        if event.get("name") != match.get("name"):
            continue
        if not name_match:
            name_match = event
        if match.get("venue") is not None and event.get("venue") != match.get("venue"):
            continue
        if match.get("venues") is not None and event.get("venue") not in match.get("venues"):
            continue
        return event
    return name_match


def rdb_occurrence(conn, name):
    result = rows(
        conn,
        """
        SELECT o.occurrence_id, o.display_name, o.event_year, o.date_start,
               o.date_end, o.date_status, o.confidence, o.source_url,
               o.public_intro_override, s.public_intro AS series_intro,
               v.canonical_name AS venue, v.address
        FROM event_occurrences o
        JOIN event_series s ON s.series_id = o.series_id
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE o.display_name = ?
          AND o.event_year = 2026
        ORDER BY o.updated_at DESC
        LIMIT 1
        """,
        (name,),
    )
    return result[0] if result else {}


def notion_event(snapshot_db, name):
    if not Path(snapshot_db).exists():
        return {}
    with closing(sqlite3.connect(snapshot_db)) as conn:
        result = rows(
            conn,
            """
            SELECT e.page_id, e.event_name, e.start_date, e.end_date, e.status,
                   e.public_intro,
                   e.source_url, e.venue_ids_json, p.last_edited_time
            FROM notion_events e
            JOIN notion_pages p ON p.page_id = e.page_id
            WHERE e.event_name = ?
            LIMIT 1
            """,
            (name,),
        )
        if not result:
            return {}
        item = result[0]
        venue_ids = json.loads(item.pop("venue_ids_json") or "[]")
        item["venue_ids"] = venue_ids
        if venue_ids:
            venue_rows = rows(
                conn,
                f"SELECT page_id, venue_name, address FROM notion_venues WHERE page_id IN ({','.join('?' for _ in venue_ids)})",
                venue_ids,
            )
            item["venues"] = venue_rows
        else:
            item["venues"] = []
        return item


def expected_matches(actual, expected, field_map):
    mismatches = []
    for expected_field, actual_field in field_map.items():
        if expected_field not in expected:
            continue
        if (actual.get(actual_field) or "") != expected.get(expected_field):
            mismatches.append(
                {
                    "field": expected_field,
                    "expected": expected.get(expected_field),
                    "actual": actual.get(actual_field) or "",
                }
            )
    return mismatches


def classify(rule, rdb, notion, public_event):
    expected = rule.get("set") or {}
    rdb_mismatches = expected_matches(
        rdb,
        expected,
        {
            "venue": "venue",
            "date": "date_start",
            "date_end": "date_end",
            "status": "date_status",
            "address": "address",
            "description": "public_intro_override",
        },
    )
    notion_mismatches = expected_matches(
        {
            "venue": ", ".join(venue.get("venue_name") or "" for venue in notion.get("venues") or []),
            "date_start": notion.get("start_date") or "",
            "date_end": notion.get("end_date") or "",
            "status": notion.get("status") or "",
        },
        expected,
        {
            "venue": "venue",
            "date": "date_start",
            "date_end": "date_end",
            "status": "status",
            "description": "public_intro",
        },
    )
    public_mismatches = expected_matches(
        public_event,
        expected,
        {
            "venue": "venue",
            "date": "date",
            "date_end": "date_end",
            "status": "status",
            "description": "description",
            "detail": "detail",
            "address": "address",
        },
    )

    rdb_core_absorbed = not [
        row for row in rdb_mismatches if row["field"] in {"venue", "date", "date_end", "address"}
    ]
    notion_core_absorbed = not [
        row for row in notion_mismatches if row["field"] in {"venue", "date", "date_end"}
    ]
    public_absorbed = not public_mismatches
    text_absorbed = not [
        row for row in rdb_mismatches + notion_mismatches if row["field"] in {"description", "detail"}
    ]

    if rdb_core_absorbed and not text_absorbed:
        action = "keep_override_text_not_absorbed_upstream"
    elif rdb_core_absorbed and not notion_core_absorbed:
        action = "keep_override_until_notion_or_rdb_export_catches_up"
    elif rdb_core_absorbed and notion_core_absorbed and public_absorbed:
        action = "override_removal_candidate_after_next_export_check"
    else:
        action = "keep_override_source_not_fully_absorbed"

    return {
        "override_id": rule.get("id") or "",
        "match": rule.get("match") or {},
        "expected_fields": expected,
        "rdb": rdb,
        "notion_snapshot": notion,
        "public_event": public_event,
        "rdb_mismatches": rdb_mismatches,
        "notion_mismatches": notion_mismatches,
        "public_mismatches": public_mismatches,
        "rdb_core_absorbed": rdb_core_absorbed,
        "notion_core_absorbed": notion_core_absorbed,
        "text_absorbed": text_absorbed,
        "public_absorbed": public_absorbed,
        "review_action": action,
    }


def build(args):
    overrides = load_json(args.overrides_json, {})
    public_events = load_json(args.public_events_json, [])
    review = []
    with connect_existing(args.master_db) as conn:
        for rule in overrides.get("overrides") or []:
            match = rule.get("match") or {}
            name = match.get("name") or ""
            review.append(
                classify(
                    rule,
                    rdb_occurrence(conn, name),
                    notion_event(args.notion_snapshot_db, name),
                    find_public_event(public_events, match),
                )
            )
    result = {
        "generated_by": "review_public_event_override_absorption.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "read_only_public_override_absorption_review",
        "sources": {
            "overrides_json": str(args.overrides_json),
            "master_db": str(args.master_db),
            "notion_snapshot_db": str(args.notion_snapshot_db),
            "public_events_json": str(args.public_events_json),
        },
        "summary": {
            "override_count": len(review),
            "actions": dict(Counter(row["review_action"] for row in review)),
        },
        "review": review,
    }
    write_json(args.out_json, result)
    Path(args.out_md).write_text(render_markdown(result), encoding="utf-8")
    return result


def render_markdown(result):
    lines = [
        "# Public event override absorption review",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- scope: {result['scope']}",
        f"- override_count: {result['summary']['override_count']}",
        f"- actions: {result['summary']['actions']}",
        "",
        "| action | override | event | RDB core | Notion core | text absorbed | public absorbed | note |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in result["review"]:
        note = ""
        if item["review_action"] == "keep_override_until_notion_or_rdb_export_catches_up":
            note = "RDB is updated, but current Notion snapshot still differs."
        elif item["review_action"] == "keep_override_text_not_absorbed_upstream":
            note = "Core fields are updated, but upstream public text still differs."
        elif item["review_action"] == "override_removal_candidate_after_next_export_check":
            note = "Core source and public row match; remove only after regenerated export diff stays clean."
        else:
            note = "Source still has mismatches."
        lines.append(
            f"| {item['review_action']} | {item['override_id']} | {item['match'].get('name') or ''} | "
            f"{item['rdb_core_absorbed']} | {item['notion_core_absorbed']} | "
            f"{item['text_absorbed']} | {item['public_absorbed']} | {note} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-db", type=Path, default=MASTER_DB)
    parser.add_argument("--notion-snapshot-db", type=Path, default=NOTION_SNAPSHOT)
    parser.add_argument("--overrides-json", type=Path, default=OVERRIDES_JSON)
    parser.add_argument("--public-events-json", type=Path, default=PUBLIC_EVENTS_JSON)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    args = parser.parse_args()
    result = build(args)
    print(f"public override absorption review: actions={result['summary']['actions']}")


if __name__ == "__main__":
    main()
