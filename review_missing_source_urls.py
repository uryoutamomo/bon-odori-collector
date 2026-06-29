"""Classify event occurrences that still have no source_url.

This is read-only review material. It only promotes source URLs when the local
RDB or prior harvest reports already contain a concrete source for the same
event. Date and venue gaps remain separate review work.
"""

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from master_db import MASTER_DB, connect_existing
from tokyo23_scope import is_outside_tokyo_23_scope


DATA = Path("data")
OUT_JSON = DATA / "missing_source_url_review.json"
OUT_MD = DATA / "missing_source_url_review.md"


REVIEW_HINTS = {
    "マロニエまつり盆踊り大会": {
        "review_action": "ready_source_url_candidate",
        "candidate_source_url": "https://x.com/1205uzonke/status/2065200648086487508",
        "candidate_source_kind": "retrospective_x_evidence",
        "confidence": "high",
        "reason": "same-date curated 浅草橋マロニエまつり盆踊り occurrence already has this source URL",
        "next_step": "fill occurrence.source_url only; leave duplicate/alias merge as a separate review",
        "local_evidence": [
            "event_occurrences duplicate occ_d5e89254b19fffb5",
            "data/retrospective_event_research_enriched.md",
            "apply_retrospective_ready_venue_events.py",
        ],
    },
    "雷門盆踊り（浅草）": {
        "review_action": "ready_source_url_candidate",
        "candidate_source_url": "https://x.com/STBA_Bonodori/status/2059220925862883623",
        "candidate_source_kind": "retrospective_x_evidence",
        "confidence": "medium",
        "reason": "prior retrospective harvest captured a concrete X evidence URL for 雷門盆踊り, but no exact date/venue",
        "next_step": "fill occurrence.source_url only; keep date and venue research open",
        "local_evidence": [
            "data/retrospective_occurrence_dry_run.json",
            "data/retrospective_occurrence_dry_run.md",
            "data/voices_seen.json",
        ],
    },
    "えどぐらん（江東区）": {
        "review_action": "ready_source_url_candidate",
        "candidate_source_url": "https://www.edogrand.tokyo/event/6924",
        "candidate_source_kind": "official_historical_event_page",
        "confidence": "medium",
        "reason": "official KYOBASHI EDOGRAND page confirms the annual 京橋盆踊り event; stored area label should be reviewed separately",
        "next_step": "fill occurrence.source_url only; review area/name separately because エドグラン is in 中央区, not 江東区",
        "local_evidence": [],
    },
    "すみだ河内音頭 小盆踊り": {
        "review_action": "ready_source_url_candidate",
        "candidate_source_url": "https://www.kinshicho-kawachiondo.jp/archives/1067",
        "candidate_source_kind": "official_current_year_event_page",
        "confidence": "high",
        "reason": "official すみだ錦糸町河内音頭大盆踊り site confirms the 5/16 小盆踊り occurrence",
        "next_step": "fill occurrence.source_url only; venue/date review can be handled separately",
        "local_evidence": [],
    },
    "月島第二児童公園 盆踊り": {
        "review_action": "ready_source_url_candidate",
        "candidate_source_url": "https://x.com/harumichiku/status/1955267713292435643",
        "candidate_source_kind": "historical_social_event_evidence",
        "confidence": "medium",
        "reason": "晴海地区 account confirms 勝どき DE 盆踊り at 月島第二児童公園 for the prior-year occurrence; no 2026 current-year source was found",
        "next_step": "fill occurrence.source_url only; keep current-year date confirmation as separate review",
        "local_evidence": [],
    },
    "鉄砲洲児童公園 盆踊り": {
        "review_action": "ready_source_url_candidate",
        "candidate_source_url": "https://x.com/iri2choukai/status/2069959259895496872",
        "candidate_source_kind": "organizer_social_current_year",
        "confidence": "high",
        "reason": "入船二丁目町会 account confirms the 2026 鉄砲洲納涼盆踊り schedule at 鉄砲洲公園",
        "next_step": "fill occurrence.source_url only; venue/name canonicalization can be handled separately",
        "local_evidence": ["tests/test_build_youtube_event_review.py"],
    },
}


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rows(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def matching_sourced_occurrences(conn, occurrence):
    date_start = occurrence.get("date_start") or ""
    name_terms = {
        occurrence["display_name"],
        occurrence["display_name"].replace("マロニエまつり盆踊り大会", "浅草橋マロニエまつり盆踊り"),
    }
    matches = []
    for term in sorted(name_terms):
        if not term:
            continue
        like = f"%{term}%"
        params = [like, like]
        date_filter = ""
        if date_start:
            date_filter = "AND COALESCE(o.date_start, '') = ?"
            params.append(date_start)
        params.append(occurrence["occurrence_id"])
        matches.extend(
            rows(
                conn,
                f"""
                SELECT o.occurrence_id, o.display_name, o.event_year, o.date_start,
                       o.source_url, s.series_id, s.canonical_name,
                       s.source_url AS series_source_url
                FROM event_occurrences o
                JOIN event_series s ON s.series_id = o.series_id
                WHERE (o.display_name LIKE ? OR s.canonical_name LIKE ?)
                  {date_filter}
                  AND o.occurrence_id != ?
                  AND COALESCE(o.source_url, s.source_url, '') != ''
                ORDER BY o.event_year DESC, o.display_name
                """,
                tuple(params),
            )
        )
    deduped = {}
    for match in matches:
        deduped[match["occurrence_id"]] = match
    return list(deduped.values())[:5]


def classify(conn, occurrence):
    hint = dict(REVIEW_HINTS.get(occurrence["display_name"]) or {})
    if not hint:
        hint = {
            "review_action": "source_research_required",
            "candidate_source_url": "",
            "candidate_source_kind": "",
            "confidence": "low",
            "reason": "no stored source URL review hint exists",
            "next_step": "research reliable source before filling source_url",
            "local_evidence": [],
        }
    matches = matching_sourced_occurrences(conn, occurrence)
    return {
        "occurrence_id": occurrence["occurrence_id"],
        "event_name": occurrence["display_name"],
        "event_year": occurrence["event_year"],
        "area": occurrence.get("area") or "",
        "venue_area": occurrence.get("venue_area") or "",
        "venue_address": occurrence.get("venue_address") or "",
        "date_start": occurrence.get("date_start") or "",
        "date_end": occurrence.get("date_end") or "",
        "date_status": occurrence.get("date_status") or "",
        "lifecycle_status": occurrence.get("lifecycle_status") or "",
        "series_id": occurrence.get("series_id") or "",
        "series_name": occurrence.get("canonical_name") or "",
        "current_source_kind": occurrence.get("source_kind") or "",
        "current_source_url": occurrence.get("source_url") or "",
        "series_source_url": occurrence.get("series_source_url") or "",
        "review_action": hint["review_action"],
        "candidate_source_url": hint.get("candidate_source_url") or "",
        "candidate_source_kind": hint.get("candidate_source_kind") or "",
        "confidence": hint.get("confidence") or "unknown",
        "reason": hint.get("reason") or "",
        "next_step": hint.get("next_step") or "",
        "local_evidence": hint.get("local_evidence") or [],
        "matching_sourced_occurrences": matches,
    }


def build(args):
    with connect_existing(args.master_db) as conn:
        occurrences = rows(
            conn,
            """
            SELECT o.occurrence_id, o.display_name, o.event_year, o.date_start,
                   o.date_end, o.date_status, o.lifecycle_status, o.source_kind,
                   o.source_url, o.series_id, s.canonical_name, s.area,
                   v.area AS venue_area, v.address AS venue_address,
                   s.source_url AS series_source_url
            FROM event_occurrences o
            JOIN event_series s ON s.series_id = o.series_id
            LEFT JOIN venues v ON v.venue_id = COALESCE(o.venue_id, s.usual_venue_id)
            WHERE COALESCE(o.source_url, '') = ''
            ORDER BY o.event_year DESC, o.display_name
            """,
        )
        in_scope = []
        skipped_outside_tokyo_23 = []
        for occurrence in occurrences:
            scope_values = (
                occurrence.get("display_name"),
                occurrence.get("canonical_name"),
                occurrence.get("area"),
                occurrence.get("venue_area"),
                occurrence.get("venue_address"),
            )
            if is_outside_tokyo_23_scope(*scope_values):
                skipped_outside_tokyo_23.append(occurrence)
                continue
            in_scope.append(occurrence)
        review = [classify(conn, occurrence) for occurrence in in_scope]

    result = {
        "generated_by": "review_missing_source_urls.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "read_only_missing_source_url_review",
        "sources": {"master_db": str(args.master_db)},
        "summary": {
            "missing_source_url_occurrence_count": len(review),
            "skipped_outside_tokyo_23_count": len(skipped_outside_tokyo_23),
            "actions": dict(Counter(item["review_action"] for item in review)),
            "ready_source_url_candidate_count": sum(
                1 for item in review if item["review_action"] == "ready_source_url_candidate"
            ),
        },
        "review": review,
        "skipped_outside_tokyo_23": [
            {
                "occurrence_id": item.get("occurrence_id"),
                "event_name": item.get("display_name"),
                "event_year": item.get("event_year"),
                "area": item.get("area") or item.get("venue_area") or "",
                "venue_address": item.get("venue_address") or "",
            }
            for item in skipped_outside_tokyo_23
        ],
    }
    write_json(args.out_json, result)
    Path(args.out_md).write_text(render_markdown(result), encoding="utf-8")
    return result


def render_markdown(result):
    lines = [
        "# Missing source URL review",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- scope: {result['scope']}",
        f"- missing_source_url_occurrence_count: {result['summary']['missing_source_url_occurrence_count']}",
        f"- skipped_outside_tokyo_23_count: {result['summary'].get('skipped_outside_tokyo_23_count', 0)}",
        f"- actions: {result['summary']['actions']}",
        f"- ready_source_url_candidate_count: {result['summary']['ready_source_url_candidate_count']}",
        "",
        "| action | event | date | candidate source | confidence | next step |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in result["review"]:
        date_range = item["date_start"]
        if item["date_end"] and item["date_end"] != item["date_start"]:
            date_range = f"{item['date_start']} to {item['date_end']}"
        lines.append(
            f"| {item['review_action']} | {item['event_name']} | {date_range} | "
            f"{item['candidate_source_url'] or '(none)'} | {item['confidence']} | {item['next_step']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-db", type=Path, default=MASTER_DB)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    args = parser.parse_args()
    result = build(args)
    print(f"missing source URL review: actions={result['summary']['actions']}")


if __name__ == "__main__":
    main()
