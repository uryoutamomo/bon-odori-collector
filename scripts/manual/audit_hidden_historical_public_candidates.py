#!/usr/bin/env python3
"""Find events that are hidden or under-modeled despite historical evidence."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from event_series_normalization import series_event_name
from export_public_events import clean_public_event_name
from master_db import connect_existing


ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "bon_odori_master.sqlite"
PUBLIC_EVENTS = ROOT / "data" / "public" / "events_public.json"
OVERRIDES = ROOT / "data" / "public_event_overrides.json"
OUT_JSON = ROOT / "data" / "hidden_historical_public_candidates.json"
OUT_MD = ROOT / "data" / "hidden_historical_public_candidates.md"
TOKYO_23 = {
    "千代田区",
    "中央区",
    "港区",
    "新宿区",
    "文京区",
    "台東区",
    "墨田区",
    "江東区",
    "品川区",
    "目黒区",
    "大田区",
    "世田谷区",
    "渋谷区",
    "中野区",
    "杉並区",
    "豊島区",
    "北区",
    "荒川区",
    "板橋区",
    "練馬区",
    "足立区",
    "葛飾区",
    "江戸川区",
}
NON_PUBLIC_LIFECYCLE = {"merged", "duplicate", "rejected", "superseded_by_curated"}


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def public_key(name: str | None, venue: str | None) -> str:
    return f"{name or ''}\u241f{venue or ''}"


def public_event_name(name: str | None) -> str:
    return series_event_name(clean_public_event_name(name))


def public_keys(path: Path) -> set[str]:
    events = load_json(path, [])
    return {public_key(row.get("name"), row.get("venue")) for row in events if isinstance(row, dict)}


def skip_override_keys(path: Path) -> set[str]:
    payload = load_json(path, {})
    keys = set()
    for rule in payload.get("overrides") or []:
        if not rule.get("skip"):
            continue
        match = rule.get("match") or {}
        name = match.get("name")
        venues = match.get("venues")
        if venues:
            for venue in venues:
                keys.add(public_key(name, venue))
        else:
            keys.add(public_key(name, match.get("venue")))
    return keys


def rows(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def parse_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except ValueError:
        return default


def occurrence_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return rows(
        conn,
        """
        SELECT
          o.occurrence_id,
          o.origin AS occurrence_origin,
          o.event_year,
          o.display_name,
          o.date_start,
          o.date_end,
          o.date_status,
          o.lifecycle_status,
          o.confidence,
          o.source_kind,
          o.source_url,
          o.detail,
          s.series_id,
          s.origin AS series_origin,
          s.canonical_name AS series_name,
          s.status AS series_status,
          s.annual_months_json,
          v.venue_id,
          v.canonical_name AS venue_name,
          v.area,
          v.review_status AS venue_review_status,
          v.address
        FROM event_occurrences o
        JOIN event_series s ON s.series_id = o.series_id
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE o.event_year = 2026
        ORDER BY v.area, s.canonical_name, o.display_name
        """,
    )


def historical_dates(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows(
        conn,
        """
        SELECT occurrence_id, date_start, date_end, date_type, confidence, basis
        FROM occurrence_dates
        ORDER BY date_start
        """,
    ):
        grouped[row["occurrence_id"]].append(
            {
                **row,
                "basis": parse_json(row.get("basis"), row.get("basis")),
            }
        )
    return grouped


def predicted_dates(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows(
        conn,
        """
        SELECT target_occurrence_id, date_start, date_end, basis_type, rule_type,
               basis, confidence, score, application_status
        FROM predicted_occurrence_dates
        WHERE predicted_year = 2026
        ORDER BY score DESC, date_start
        """,
    ):
        grouped[row["target_occurrence_id"]].append(row)
    return grouped


def promotion_candidates(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows(
        conn,
        """
        SELECT target_occurrence_id, historical_years_json, exact_dates_json,
               prediction_json, evidence_url_count, song_title_count, match_score,
               promotion_confidence, auto_promote_eligible, recommended_action, notes
        FROM historical_promotion_candidates
        ORDER BY match_score DESC
        """,
    ):
        grouped[row["target_occurrence_id"]].append(
            {
                **row,
                "historical_years": parse_json(row.pop("historical_years_json"), []),
                "exact_dates": parse_json(row.pop("exact_dates_json"), {}),
                "prediction": parse_json(row.pop("prediction_json"), {}),
            }
        )
    return grouped


def public_eligibility(row: dict[str, Any]) -> tuple[bool, list[str]]:
    blockers = []
    if row.get("area") not in TOKYO_23:
        blockers.append("outside_tokyo23_or_missing_area")
    if not row.get("venue_id"):
        blockers.append("missing_venue")
    if row.get("venue_review_status") != "active":
        blockers.append("venue_not_active")
    if row.get("occurrence_origin") != "curated":
        blockers.append("origin_not_curated")
    if row.get("series_status") != "active":
        blockers.append("series_not_active")
    if row.get("lifecycle_status") in NON_PUBLIC_LIFECYCLE:
        blockers.append(f"lifecycle:{row.get('lifecycle_status')}")
    return not blockers, blockers


def evidence_score(
    hist_dates: list[dict[str, Any]],
    preds: list[dict[str, Any]],
    promos: list[dict[str, Any]],
) -> tuple[int, list[str]]:
    score = 0
    reasons = []
    hist_years = sorted({str(date["date_start"])[:4] for date in hist_dates if date.get("date_start")})
    if hist_years:
        score += 2
        reasons.append(f"historical_dates:{','.join(hist_years)}")
    if len(hist_years) >= 2:
        score += 2
        reasons.append("multiple_historical_years")
    if any(date.get("date_type") == "historical_reference" for date in hist_dates):
        score += 1
        reasons.append("historical_reference_date")
    if preds:
        score += 3
        reasons.append("predicted_occurrence_date")
    if promos:
        best = promos[0]
        if best.get("promotion_confidence") in {"high", "medium"}:
            score += 2
            reasons.append(f"promotion_confidence:{best.get('promotion_confidence')}")
        if best.get("evidence_url_count", 0) or best.get("song_title_count", 0):
            score += 1
            reasons.append("external_or_song_evidence")
    return score, reasons


def recommendation(row: dict[str, Any], in_public: bool, skipped_by_override: bool, blockers: list[str], score: int) -> str:
    if in_public:
        return "already_public_check_prediction_fields"
    if skipped_by_override and score >= 3 and not blockers:
        return "remove_skip_and_publish_historical_slide"
    if not blockers and score >= 5:
        return "publish_historical_slide_candidate"
    if not blockers and score >= 3:
        return "review_then_publish_historical_reference"
    if blockers:
        return "fix_blockers_before_public"
    return "insufficient_historical_evidence"


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    keys = public_keys(args.public_events)
    skip_keys = skip_override_keys(args.overrides)
    with connect_existing(args.db) as conn:
        hist_by_occ = historical_dates(conn)
        pred_by_occ = predicted_dates(conn)
        promo_by_occ = promotion_candidates(conn)
        candidates = []
        for row in occurrence_rows(conn):
            raw_name = row.get("display_name") or row.get("series_name")
            name = public_event_name(raw_name)
            venue = row.get("venue_name")
            key = public_key(name, venue)
            hist = hist_by_occ.get(row["occurrence_id"], [])
            preds = pred_by_occ.get(row["occurrence_id"], [])
            promos = promo_by_occ.get(row["occurrence_id"], [])
            score, reasons = evidence_score(hist, preds, promos)
            eligible, blockers = public_eligibility(row)
            in_public = key in keys
            skipped = key in skip_keys
            if in_public and score == 0:
                continue
            if not in_public and score == 0 and not skipped:
                continue
            candidates.append(
                {
                    "event_name": name,
                    "venue": venue,
                    "area": row.get("area"),
                    "occurrence_id": row["occurrence_id"],
                    "series_id": row["series_id"],
                    "date_start": row.get("date_start"),
                    "date_status": row.get("date_status"),
                    "lifecycle_status": row.get("lifecycle_status"),
                    "public_key": key,
                    "in_public_json": in_public,
                    "skipped_by_override": skipped,
                    "public_eligible": eligible,
                    "blockers": blockers,
                    "evidence_score": score,
                    "evidence_reasons": reasons,
                    "historical_dates": hist,
                    "predicted_dates": preds,
                    "historical_promotion_candidates": promos[:3],
                    "recommendation": recommendation(row, in_public, skipped, blockers, score),
                }
            )
    candidates.sort(
        key=lambda row: (
            row["in_public_json"],
            -row["evidence_score"],
            row["recommendation"],
            row.get("area") or "",
            row["event_name"] or "",
        )
    )
    counts = Counter(row["recommendation"] for row in candidates)
    return {
        "generated_by": "audit_hidden_historical_public_candidates.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "db": str(args.db),
            "public_events": str(args.public_events),
            "overrides": str(args.overrides),
        },
        "summary": {
            "candidate_count": len(candidates),
            "recommendation_counts": dict(sorted(counts.items())),
            "hidden_candidate_count": sum(1 for row in candidates if not row["in_public_json"]),
            "skipped_by_override_count": sum(1 for row in candidates if row["skipped_by_override"]),
        },
        "candidates": candidates,
    }


def md_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Hidden historical public candidates",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- candidate_count: {report['summary']['candidate_count']}",
        f"- hidden_candidate_count: {report['summary']['hidden_candidate_count']}",
        f"- skipped_by_override_count: {report['summary']['skipped_by_override_count']}",
        "",
        "## Recommendation counts",
        "",
    ]
    for key, count in report["summary"]["recommendation_counts"].items():
        lines.append(f"- {key}: {count}")
    lines.extend(
        [
            "",
            "## Candidates",
            "",
            "| recommendation | score | public | skipped | blockers | event | venue | historical | predicted |",
            "| --- | ---: | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in report["candidates"]:
        historical = ", ".join(
            date.get("date_start") or ""
            for date in row.get("historical_dates") or []
        )
        predicted = ", ".join(
            date.get("date_start") or ""
            for date in row.get("predicted_dates") or []
        )
        lines.append(
            "| {recommendation} | {score} | {public} | {skipped} | {blockers} | {event} | {venue} | {historical} | {predicted} |".format(
                recommendation=md_cell(row["recommendation"]),
                score=row["evidence_score"],
                public="yes" if row["in_public_json"] else "no",
                skipped="yes" if row["skipped_by_override"] else "no",
                blockers=md_cell(", ".join(row["blockers"])),
                event=md_cell(row["event_name"]),
                venue=md_cell(row["venue"]),
                historical=md_cell(historical),
                predicted=md_cell(predicted),
            )
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--public-events", type=Path, default=PUBLIC_EVENTS)
    parser.add_argument("--overrides", type=Path, default=OVERRIDES)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    args = parser.parse_args()
    report = build_report(args)
    write_json(args.out_json, report)
    args.out_md.write_text(render_markdown(report), encoding="utf-8")
    print(
        "hidden historical public candidates: "
        f"candidates={report['summary']['candidate_count']} "
        f"hidden={report['summary']['hidden_candidate_count']} "
        f"skipped={report['summary']['skipped_by_override_count']} "
        f"out={args.out_json}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
