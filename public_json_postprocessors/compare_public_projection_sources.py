"""Compare public postprocessor fields with available Master RDB projection sources.

This is a read-only C-phase report. It does not change public JSON or the
Master RDB. The goal is to show which public fields can already be projected
from RDB tables before removing the legacy postprocessor scripts.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from event_series.normalization import series_event_name
from master_db import MASTER_DB, require_existing_db


DATA = Path("data")
PUBLIC_EVENTS = DATA / "public" / "events_public.json"
PUBLIC_EVENT_SOURCE_MAP = DATA / "public_event_source_map.json"
OUT_JSON = DATA / "public_projection_source_compare.json"
OUT_MD = DATA / "public_projection_source_compare.md"


def load_json(path: Path, default):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_key_part(value) -> str:
    value = series_event_name(str(value or ""))
    value = re.sub(r"\s+", "", value)
    return value.casefold()


def event_key(name, venue) -> str:
    return f"{normalize_key_part(name)}||{normalize_key_part(venue)}"


def public_event_key(event: dict) -> str:
    return event_key(event.get("name"), event.get("venue"))


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


def json_dict(value) -> dict:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def json_list(value) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def db_rows(db_path: Path, query: str, params=()) -> list[dict]:
    require_existing_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(query, params)]


def add_index_row(index: dict[str, list[dict]], key: str, row: dict) -> None:
    if key and key != "||":
        index[key].append(row)


def load_prediction_sources(db_path: Path, target_year: int) -> dict[str, list[dict]]:
    rows = db_rows(
        db_path,
        """
        SELECT
          p.predicted_date_id,
          p.target_event_name,
          p.predicted_year,
          p.date_start,
          p.date_end,
          p.date_status,
          p.basis_type,
          p.basis_type_label,
          p.rule_type,
          p.basis,
          p.confidence,
          p.score,
          p.application_status,
          p.source,
          p.source_payload_json,
          p.target_occurrence_id AS occurrence_id,
          COALESCE(o.display_name, p.target_event_name, s.canonical_name) AS event_name,
          COALESCE(v.canonical_name, uv.canonical_name, '') AS venue_name
        FROM predicted_occurrence_dates p
        JOIN event_series s ON s.series_id = p.target_series_id
        LEFT JOIN event_occurrences o ON o.occurrence_id = p.target_occurrence_id
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        LEFT JOIN venues uv ON uv.venue_id = s.usual_venue_id
        WHERE p.predicted_year = ?
        """,
        (target_year,),
    )
    index: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        payload = json_dict(row.get("source_payload_json"))
        source = {
            "predicted_date_id": row.get("predicted_date_id"),
            "occurrence_id": row.get("occurrence_id"),
            "event_name": row.get("event_name"),
            "venue": row.get("venue_name"),
            "date": row.get("date_start"),
            "date_end": row.get("date_end"),
            "confidence": row.get("confidence"),
            "score": row.get("score"),
            "rule_type": row.get("rule_type"),
            "basis": row.get("basis"),
            "basis_type": row.get("basis_type"),
            "application_status": row.get("application_status"),
            "evidence_years": payload.get("evidence_years") or [],
        }
        add_index_row(index, event_key(source["event_name"], source["venue"]), source)
    return dict(index)


def load_historical_sources(db_path: Path, target_year: int) -> dict[str, list[dict]]:
    rows = db_rows(
        db_path,
        """
        SELECT
          od.occurrence_date_id,
          od.occurrence_id,
          od.date_start,
          od.date_end,
          od.confidence,
          od.basis,
          od.source_evidence_id,
          ei.title AS source_title,
          ei.url AS source_url,
          o.display_name AS event_name,
          o.event_year,
          s.canonical_name AS series_name,
          v.canonical_name AS venue_name
        FROM occurrence_dates od
        JOIN event_occurrences o ON o.occurrence_id = od.occurrence_id
        JOIN event_series s ON s.series_id = o.series_id
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        LEFT JOIN evidence_items ei ON ei.evidence_id = od.source_evidence_id
        WHERE od.date_type = 'historical_reference'
          AND od.date_start < ?
        """,
        (f"{target_year}-01-01",),
    )
    index: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        basis = json_dict(row.get("basis"))
        source = {
            "occurrence_date_id": row.get("occurrence_date_id"),
            "occurrence_id": row.get("occurrence_id"),
            "event_name": row.get("event_name") or row.get("series_name"),
            "venue": row.get("venue_name"),
            "date": row.get("date_start"),
            "date_end": row.get("date_end"),
            "confidence": row.get("confidence"),
            "basis": basis,
            "source_evidence_id": row.get("source_evidence_id"),
            "source_title": row.get("source_title"),
            "source_url": row.get("source_url"),
        }
        add_index_row(index, event_key(source["event_name"], source["venue"]), source)
    return dict(index)


def load_season_sources(db_path: Path, target_year: int) -> dict[str, list[dict]]:
    rows = db_rows(
        db_path,
        """
        SELECT
          o.occurrence_id,
          COALESCE(o.display_name, s.canonical_name) AS event_name,
          o.event_year,
          o.date_start,
          o.date_end,
          s.annual_months_json,
          s.schedule_rule_type,
          s.schedule_rule_detail,
          v.canonical_name AS venue_name
        FROM event_occurrences o
        JOIN event_series s ON s.series_id = o.series_id
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE o.event_year = ?
          AND o.origin = 'curated'
          AND o.lifecycle_status NOT IN ('merged', 'duplicate', 'rejected', 'superseded_by_curated')
        """,
        (target_year,),
    )
    index: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        months = [
            int(month)
            for month in json_list(row.get("annual_months_json"))
            if str(month).isdigit() and 1 <= int(month) <= 12
        ]
        source = {
            "occurrence_id": row.get("occurrence_id"),
            "event_name": row.get("event_name"),
            "venue": row.get("venue_name"),
            "months": sorted(set(months)),
            "schedule_rule_type": row.get("schedule_rule_type"),
            "schedule_rule_detail": row.get("schedule_rule_detail"),
            "has_confirmed_or_historical_date": bool(row.get("date_start")),
        }
        add_index_row(index, event_key(source["event_name"], source["venue"]), source)
    return dict(index)


def first_match(index: dict[str, list[dict]], key: str) -> dict | None:
    rows = index.get(key) or []
    return rows[0] if rows else None


def index_by_occurrence_id(index: dict[str, list[dict]]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    seen = set()
    for rows in index.values():
        for row in rows:
            occurrence_id = row.get("occurrence_id")
            row_key = (occurrence_id, row.get("predicted_date_id"), row.get("occurrence_date_id"))
            if not occurrence_id or row_key in seen:
                continue
            seen.add(row_key)
            out[occurrence_id].append(row)
    return dict(out)


def first_source(index: dict[str, list[dict]], by_occurrence: dict[str, list[dict]], key: str, occurrence_id: str | None) -> dict | None:
    if occurrence_id:
        rows = by_occurrence.get(occurrence_id) or []
        if rows:
            return rows[0]
    return first_match(index, key)


def matching_sources(index: dict[str, list[dict]], by_occurrence: dict[str, list[dict]], key: str, occurrence_id: str | None) -> list[dict]:
    if occurrence_id:
        rows = by_occurrence.get(occurrence_id) or []
        if rows:
            return rows
    return index.get(key) or []


def compare_prediction(event: dict, source: dict | None) -> dict:
    prediction = event.get("date_prediction") or {}
    if not prediction:
        return {"status": "not_applicable"}
    if not source:
        return {"status": "missing_rdb_source"}
    mismatches = {}
    field_map = {
        "date": "date",
        "date_end": "date_end",
        "confidence": "confidence",
        "rule_type": "rule_type",
        "basis": "basis",
    }
    for public_field, source_field in field_map.items():
        if prediction.get(public_field) != source.get(source_field):
            mismatches[public_field] = {
                "public": prediction.get(public_field),
                "rdb": source.get(source_field),
            }
    return {
        "status": "match" if not mismatches else "field_mismatch",
        "source_id": source.get("predicted_date_id"),
        "mismatches": mismatches,
    }


def historical_source_dates(source: dict) -> list[str]:
    return [value for value in [source.get("date"), source.get("date_end")] if value]


def compare_historical(event: dict, sources: list[dict] | dict | None) -> dict:
    reference = event.get("historical_reference") or {}
    if not reference:
        return {"status": "not_applicable"}
    if isinstance(sources, dict):
        sources = [sources]
    sources = sources or []
    if not sources:
        return {"status": "missing_rdb_source"}
    public_dates = reference.get("last_seen_dates") or []
    public_date_set = set(public_dates)
    rdb_sources = [
        {
            "source_id": source.get("occurrence_date_id"),
            "dates": historical_source_dates(source),
            "source_evidence_id": source.get("source_evidence_id"),
            "source_title": source.get("source_title"),
            "source_url": source.get("source_url"),
        }
        for source in sources
    ]
    for source, source_row in zip(sources, rdb_sources):
        if public_date_set & set(source_row["dates"]):
            return {
                "status": "match",
                "source_id": source.get("occurrence_date_id"),
                "public_dates": public_dates,
                "rdb_dates": source_row["dates"],
                "rdb_source_count": len(sources),
            }
    return {
        "status": "date_mismatch",
        "source_id": sources[0].get("occurrence_date_id"),
        "public_dates": public_dates,
        "rdb_dates": [date for source in rdb_sources for date in source["dates"]],
        "rdb_sources": rdb_sources,
    }


def compare_season(event: dict, source: dict | None) -> dict:
    hint = event.get("season_hint") or {}
    if not hint:
        return {"status": "not_applicable"}
    if not source:
        return {"status": "missing_rdb_source"}
    public_months = sorted(int(month) for month in hint.get("months") or [])
    source_months = sorted(int(month) for month in source.get("months") or [])
    missing = [month for month in public_months if month not in source_months]
    return {
        "status": "match" if not missing else "month_mismatch",
        "source_id": source.get("occurrence_id"),
        "public_months": public_months,
        "rdb_months": source_months,
        "missing_months": missing,
        "has_schedule_rule": bool(source.get("schedule_rule_type") or source.get("schedule_rule_detail")),
    }


def build_report(public_events: list[dict], master_db: Path, target_year: int = 2026, source_map: dict[str, dict] | None = None) -> dict:
    predictions = load_prediction_sources(master_db, target_year)
    historical = load_historical_sources(master_db, target_year)
    seasons = load_season_sources(master_db, target_year)
    prediction_by_occurrence = index_by_occurrence_id(predictions)
    historical_by_occurrence = index_by_occurrence_id(historical)
    season_by_occurrence = index_by_occurrence_id(seasons)
    source_map = source_map or {}

    rows = []
    counters = Counter()
    sidecar_hits = 0
    for event in public_events:
        key = public_event_key(event)
        sidecar = source_map.get(public_event_sidecar_key(event)) or {}
        occurrence_id = sidecar.get("occurrence_id")
        if occurrence_id:
            sidecar_hits += 1
        prediction = compare_prediction(
            event,
            first_source(predictions, prediction_by_occurrence, key, occurrence_id),
        )
        historical_result = compare_historical(
            event,
            matching_sources(historical, historical_by_occurrence, key, occurrence_id),
        )
        season = compare_season(
            event,
            first_source(seasons, season_by_occurrence, key, occurrence_id),
        )
        for family, result in (
            ("prediction", prediction),
            ("historical", historical_result),
            ("season", season),
        ):
            counters[f"{family}:{result['status']}"] += 1
        if any(result["status"] not in {"not_applicable", "match"} for result in (prediction, historical_result, season)):
            rows.append(
                {
                    "name": event.get("name"),
                    "venue": event.get("venue"),
                    "public_category": event.get("public_category"),
                    "display_tier": event.get("display_tier"),
                    "occurrence_id": occurrence_id,
                    "prediction": prediction,
                    "historical_reference": historical_result,
                    "season_hint": season,
                }
            )

    return {
        "generated_by": "compare_public_projection_sources.py",
        "scope": "read_only_c_phase_projection_readiness",
        "target_year": target_year,
        "public_event_count": len(public_events),
        "source_counts": {
            "prediction_keys": len(predictions),
            "historical_keys": len(historical),
            "season_keys": len(seasons),
            "sidecar_keys": len(source_map),
            "sidecar_hits": sidecar_hits,
        },
        "summary": dict(sorted(counters.items())),
        "blocking_row_count": len(rows),
        "blocking_rows": rows[:200],
        "next_step": (
            "Resolve missing_rdb_source and field/month mismatches before replacing "
            "public postprocessor scripts with RDB-native projection."
        ),
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Public Projection Source Compare",
        "",
        f"- generated_by: {report['generated_by']}",
        f"- scope: {report['scope']}",
        f"- target_year: {report['target_year']}",
        f"- public_event_count: {report['public_event_count']}",
        f"- source_counts: {report['source_counts']}",
        f"- blocking_row_count: {report['blocking_row_count']}",
        "",
        "## Summary",
        "",
    ]
    for key, value in report["summary"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Blocking Examples", ""])
    if not report["blocking_rows"]:
        lines.append("- none")
    for row in report["blocking_rows"][:50]:
        lines.append(
            f"- {row['name']} / {row['venue']}: "
            f"prediction={row['prediction']['status']}, "
            f"historical={row['historical_reference']['status']}, "
            f"season={row['season_hint']['status']}"
        )
    lines.extend(["", "## Next Step", "", f"- {report['next_step']}", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-events", default=str(PUBLIC_EVENTS))
    parser.add_argument("--master-db", default=str(MASTER_DB))
    parser.add_argument("--source-map", default=str(PUBLIC_EVENT_SOURCE_MAP))
    parser.add_argument("--target-year", type=int, default=2026)
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    args = parser.parse_args()

    public_events = load_json(Path(args.public_events), [])
    source_map = load_source_map(Path(args.source_map))
    report = build_report(public_events, Path(args.master_db), target_year=args.target_year, source_map=source_map)
    write_json(Path(args.out_json), report)
    Path(args.out_md).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_md).write_text(render_markdown(report), encoding="utf-8")
    print(
        "public projection source compare: "
        f"events={report['public_event_count']} "
        f"blocking={report['blocking_row_count']} "
        f"out={args.out_json}"
    )


if __name__ == "__main__":
    main()
