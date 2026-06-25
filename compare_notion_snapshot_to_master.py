#!/usr/bin/env python3
"""Compare the current Notion snapshot with linked master RDB rows.

This is a read-only preflight report for source snapshot drift. It intentionally
does not update the master DB or manifest because the master DB can contain
DB-only review/apply state that a snapshot rebuild would lose.
"""

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from build_master_rdb import date_status, lifecycle_status, parse_months, parse_year
from event_series_normalization import series_event_name
from master_db import MASTER_DB, connect_existing


DATA = Path("data")
NOTION_DB = DATA / "notion_snapshot.sqlite"
OUT_JSON = DATA / "notion_snapshot_master_drift.json"
OUT_MD = DATA / "notion_snapshot_master_drift.md"


def rows(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def norm(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def json_list(value):
    return json.dumps(value or [], ensure_ascii=False, sort_keys=True)


def add_diff(diffs, entity_type, entity_id, title, field, master_value, notion_value, severity="review"):
    master_value = norm(master_value)
    notion_value = norm(notion_value)
    if master_value == notion_value:
        return
    if master_value in ("", None) and notion_value not in ("", None):
        drift_kind = "notion_has_value_master_empty"
        recommendation = "review_before_copy_from_notion"
    elif master_value not in ("", None) and notion_value in ("", None):
        drift_kind = "master_has_value_notion_empty"
        recommendation = "preserve_master"
    else:
        drift_kind = "value_conflict"
        recommendation = "review_conflict"
    diffs.append(
        {
            "severity": severity,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "title": title or "",
            "field": field,
            "drift_kind": drift_kind,
            "recommendation": recommendation,
            "master_value": master_value,
            "notion_snapshot_value": notion_value,
        }
    )


def linked_notion_page_ids(master_conn, source_key, master_table):
    return {
        row["external_id"]
        for row in rows(
            master_conn,
            """
            SELECT external_id
            FROM external_record_links
            WHERE system = 'notion'
              AND source_key = ?
              AND master_table = ?
            """,
            (source_key, master_table),
        )
    }


def venue_id_by_notion_page(master_conn):
    return {
        row["external_id"]: row["master_id"]
        for row in rows(
            master_conn,
            """
            SELECT external_id, master_id
            FROM external_record_links
            WHERE system = 'notion'
              AND source_key = 'venues'
              AND master_table = 'venues'
              AND relation_kind = 'primary'
            """,
        )
    }


def compare_venues(master_conn):
    diffs = []
    source_rows = rows(
        master_conn,
        """
        SELECT n.page_id, n.venue_name, n.area, n.address, n.access, n.scale,
               n.public_intro, n.past_memo,
               v.venue_id, v.canonical_name, v.area AS master_area,
               v.address AS master_address, v.access AS master_access,
               v.scale AS master_scale, v.public_intro AS master_public_intro,
               v.past_memo AS master_past_memo
        FROM notion.notion_venues n
        JOIN external_record_links l
          ON l.system = 'notion'
         AND l.source_key = 'venues'
         AND l.master_table = 'venues'
         AND l.external_id = n.page_id
        JOIN venues v ON v.venue_id = l.master_id
        """,
    )
    for row in source_rows:
        entity_id = row["venue_id"]
        title = row["canonical_name"]
        add_diff(diffs, "venue", entity_id, title, "canonical_name", row["canonical_name"], row["venue_name"])
        add_diff(diffs, "venue", entity_id, title, "area", row["master_area"], row["area"])
        add_diff(diffs, "venue", entity_id, title, "address", row["master_address"], row["address"])
        add_diff(diffs, "venue", entity_id, title, "access", row["master_access"], row["access"])
        add_diff(diffs, "venue", entity_id, title, "scale", row["master_scale"], row["scale"])
        add_diff(diffs, "venue", entity_id, title, "public_intro", row["master_public_intro"], row["public_intro"])
        add_diff(diffs, "venue", entity_id, title, "past_memo", row["master_past_memo"], row["past_memo"])
    return diffs


def compare_songs(master_conn):
    diffs = []
    source_rows = rows(
        master_conn,
        """
        SELECT n.page_id, n.song_name, n.category, n.status, n.evidence_count,
               n.source_url, n.memo,
               s.song_id, s.canonical_title, s.category AS master_category,
               s.status AS master_status, s.evidence_count AS master_evidence_count,
               s.source_url AS master_source_url, s.memo AS master_memo
        FROM notion.notion_songs n
        JOIN external_record_links l
          ON l.system = 'notion'
         AND l.source_key = 'songs'
         AND l.master_table = 'songs'
         AND l.external_id = n.page_id
        JOIN songs s ON s.song_id = l.master_id
        """,
    )
    for row in source_rows:
        entity_id = row["song_id"]
        title = row["canonical_title"]
        add_diff(diffs, "song", entity_id, title, "canonical_title", row["canonical_title"], row["song_name"])
        add_diff(diffs, "song", entity_id, title, "category", row["master_category"], row["category"])
        add_diff(diffs, "song", entity_id, title, "status", row["master_status"], row["status"])
        add_diff(diffs, "song", entity_id, title, "evidence_count", row["master_evidence_count"], row["evidence_count"])
        add_diff(diffs, "song", entity_id, title, "source_url", row["master_source_url"], row["source_url"])
        add_diff(diffs, "song", entity_id, title, "memo", row["master_memo"], row["memo"])
    return diffs


def notion_event_venue_ids(master_conn):
    page_to_master_venue = venue_id_by_notion_page(master_conn)
    event_venues = {}
    for row in rows(
        master_conn,
        """
        SELECT page_id, related_page_id
        FROM notion.notion_relations
        WHERE property_name = '会場'
        """,
    ):
        venue_id = page_to_master_venue.get(row["related_page_id"])
        if venue_id:
            event_venues.setdefault(row["page_id"], []).append(venue_id)
    return event_venues


def compare_events(master_conn):
    diffs = []
    event_venues = notion_event_venue_ids(master_conn)
    occurrence_rows = rows(
        master_conn,
        """
        SELECT n.page_id, n.event_name, n.start_date, n.end_date, n.status,
               n.annual_months, n.detail, n.public_intro, n.source_url,
               o.occurrence_id, o.display_name, o.event_year, o.venue_id,
               o.date_start, o.date_end, o.date_status, o.lifecycle_status,
               o.source_url AS master_source_url,
               o.public_intro_override, o.detail AS master_detail
        FROM notion.notion_events n
        JOIN external_record_links l
          ON l.system = 'notion'
         AND l.source_key = 'events'
         AND l.master_table = 'event_occurrences'
         AND l.relation_kind = 'primary'
         AND l.external_id = n.page_id
        JOIN event_occurrences o ON o.occurrence_id = l.master_id
        """,
    )
    for row in occurrence_rows:
        entity_id = row["occurrence_id"]
        title = row["display_name"]
        expected_name = series_event_name(row["event_name"] or "")
        expected_year = parse_year(row["start_date"], row["event_name"], default=2026)
        expected_date_status = date_status(row["status"], row["start_date"])
        expected_lifecycle = lifecycle_status(row["status"])
        expected_venue = next(iter(event_venues.get(row["page_id"], [])), None) or ""
        add_diff(diffs, "event_occurrence", entity_id, title, "display_name", row["display_name"], expected_name)
        add_diff(diffs, "event_occurrence", entity_id, title, "event_year", row["event_year"], expected_year)
        add_diff(diffs, "event_occurrence", entity_id, title, "venue_id", row["venue_id"], expected_venue)
        add_diff(diffs, "event_occurrence", entity_id, title, "date_start", row["date_start"], row["start_date"])
        add_diff(diffs, "event_occurrence", entity_id, title, "date_end", row["date_end"], row["end_date"])
        add_diff(diffs, "event_occurrence", entity_id, title, "date_status", row["date_status"], expected_date_status)
        add_diff(diffs, "event_occurrence", entity_id, title, "lifecycle_status", row["lifecycle_status"], expected_lifecycle)
        add_diff(diffs, "event_occurrence", entity_id, title, "source_url", row["master_source_url"], row["source_url"])
        add_diff(diffs, "event_occurrence", entity_id, title, "public_intro_override", row["public_intro_override"], row["public_intro"])
        add_diff(diffs, "event_occurrence", entity_id, title, "detail", row["master_detail"], row["detail"])

    series_public_intro_values = {}
    series_source_url_values = {}
    for row in rows(
        master_conn,
        """
        SELECT l.master_id AS series_id, n.public_intro, n.source_url
        FROM notion.notion_events n
        JOIN external_record_links l
          ON l.system = 'notion'
         AND l.source_key = 'events'
         AND l.master_table = 'event_series'
         AND l.relation_kind = 'series_for_occurrence'
         AND l.external_id = n.page_id
        """,
    ):
        if row.get("public_intro"):
            series_public_intro_values.setdefault(row["series_id"], set()).add(row["public_intro"])
        if row.get("source_url"):
            series_source_url_values.setdefault(row["series_id"], set()).add(row["source_url"])

    series_rows = rows(
        master_conn,
        """
        SELECT n.page_id, n.event_name, n.annual_months, n.public_intro, n.source_url,
               s.series_id, s.canonical_name, s.usual_venue_id, s.annual_months_json,
               s.public_intro AS master_public_intro, s.source_url AS master_source_url
        FROM notion.notion_events n
        JOIN external_record_links l
          ON l.system = 'notion'
         AND l.source_key = 'events'
         AND l.master_table = 'event_series'
         AND l.relation_kind = 'series_for_occurrence'
         AND l.external_id = n.page_id
        JOIN event_series s ON s.series_id = l.master_id
        """,
    )
    for row in series_rows:
        entity_id = row["series_id"]
        title = row["canonical_name"]
        expected_name = series_event_name(row["event_name"] or "")
        expected_venue = next(iter(event_venues.get(row["page_id"], [])), None) or ""
        add_diff(diffs, "event_series", entity_id, title, "canonical_name", row["canonical_name"], expected_name)
        add_diff(diffs, "event_series", entity_id, title, "usual_venue_id", row["usual_venue_id"], expected_venue)
        add_diff(diffs, "event_series", entity_id, title, "annual_months_json", row["annual_months_json"], json_list(parse_months(row["annual_months"])))
        if not (
            row["master_public_intro"]
            and not row["public_intro"]
            and row["master_public_intro"] in series_public_intro_values.get(entity_id, set())
        ):
            add_diff(diffs, "event_series", entity_id, title, "public_intro", row["master_public_intro"], row["public_intro"])
        if not (
            row["master_source_url"]
            and row["master_source_url"] != row["source_url"]
            and row["master_source_url"] in series_source_url_values.get(entity_id, set())
        ):
            add_diff(diffs, "event_series", entity_id, title, "source_url", row["master_source_url"], row["source_url"])
    return diffs


def build_report(master_db, notion_db):
    with connect_existing(master_db) as master_conn:
        master_conn.execute("ATTACH DATABASE ? AS notion", (str(notion_db),))
        diffs = []
        diffs.extend(compare_venues(master_conn))
        diffs.extend(compare_songs(master_conn))
        diffs.extend(compare_events(master_conn))
        linked_counts = {
            "notion_venues_linked": len(linked_notion_page_ids(master_conn, "venues", "venues")),
            "notion_events_linked": len(linked_notion_page_ids(master_conn, "events", "event_occurrences")),
            "notion_songs_linked": len(linked_notion_page_ids(master_conn, "songs", "songs")),
        }
        notion_counts = {
            "notion_venues": rows(master_conn, "SELECT COUNT(*) AS count FROM notion.notion_venues")[0]["count"],
            "notion_events": rows(master_conn, "SELECT COUNT(*) AS count FROM notion.notion_events")[0]["count"],
            "notion_songs": rows(master_conn, "SELECT COUNT(*) AS count FROM notion.notion_songs")[0]["count"],
        }
    by_entity = Counter(row["entity_type"] for row in diffs)
    by_field = Counter(f"{row['entity_type']}.{row['field']}" for row in diffs)
    by_kind = Counter(row["drift_kind"] for row in diffs)
    by_recommendation = Counter(row["recommendation"] for row in diffs)
    return {
        "generated_by": "compare_notion_snapshot_to_master.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "master_db": str(master_db),
        "notion_db": str(notion_db),
        "status": "review_required" if diffs else "no_source_field_diffs",
        "summary": {
            "diff_count": len(diffs),
            "diffs_by_entity_type": dict(sorted(by_entity.items())),
            "diffs_by_field": dict(sorted(by_field.items())),
            "diffs_by_kind": dict(sorted(by_kind.items())),
            "diffs_by_recommendation": dict(sorted(by_recommendation.items())),
            "linked_counts": linked_counts,
            "notion_counts": notion_counts,
        },
        "diffs": diffs,
    }


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def md_escape(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(report):
    lines = [
        "# Notion snapshot -> master drift report",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- status: {report['status']}",
        f"- master_db: `{report['master_db']}`",
        f"- notion_db: `{report['notion_db']}`",
        f"- diff_count: {report['summary']['diff_count']}",
        f"- linked_counts: {report['summary']['linked_counts']}",
        f"- notion_counts: {report['summary']['notion_counts']}",
        "",
        "## Diffs by entity",
        "",
    ]
    for key, count in report["summary"]["diffs_by_entity_type"].items():
        lines.append(f"- {key}: {count}")
    if not report["summary"]["diffs_by_entity_type"]:
        lines.append("- none")
    lines.extend(["", "## Diffs by field", ""])
    for key, count in report["summary"]["diffs_by_field"].items():
        lines.append(f"- {key}: {count}")
    if not report["summary"]["diffs_by_field"]:
        lines.append("- none")
    lines.extend(["", "## Diffs by kind", ""])
    for key, count in report["summary"]["diffs_by_kind"].items():
        lines.append(f"- {key}: {count}")
    if not report["summary"]["diffs_by_kind"]:
        lines.append("- none")
    lines.extend(["", "## Diff detail", "", "| entity | title | field | kind | recommendation | master | notion snapshot |", "| --- | --- | --- | --- | --- | --- | --- |"])
    for diff in report["diffs"]:
        lines.append(
            "| {entity} | {title} | {field} | {kind} | {recommendation} | {master} | {notion} |".format(
                entity=md_escape(diff["entity_type"]),
                title=md_escape(diff["title"]),
                field=md_escape(diff["field"]),
                kind=md_escape(diff["drift_kind"]),
                recommendation=md_escape(diff["recommendation"]),
                master=md_escape(diff["master_value"]),
                notion=md_escape(diff["notion_snapshot_value"]),
            )
        )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-db", type=Path, default=MASTER_DB)
    parser.add_argument("--notion-db", type=Path, default=NOTION_DB)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    args = parser.parse_args()
    report = build_report(args.master_db, args.notion_db)
    write_json(args.out_json, report)
    Path(args.out_md).write_text(render_markdown(report), encoding="utf-8")
    print(
        "notion snapshot master drift: "
        f"status={report['status']} "
        f"diffs={report['summary']['diff_count']} "
        f"out={args.out_json}"
    )


if __name__ == "__main__":
    main()
