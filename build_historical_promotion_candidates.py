"""Build multi-year historical-reference promotion candidates.

This dry-run helper finds registered events that have observed evidence in
two or more historical years. It promotes evidence quality, not future dates:
year-only placeholders such as 2024-01-01 stay year-only and are never copied
as an exact event date.
"""

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from build_observed_promotion_candidates import (
    all_dates,
    best_curated_match,
    extract_event_name,
    load_curated_events,
    load_json,
    occurrence_by_id,
    write_json,
)
from manual_apply_guards import MASTER_RDB_ONE_OFF_CONFIRMATION, require_confirmation
from master_db import MASTER_DB, MASTER_MANIFEST, connect_existing, file_sha256, stable_id, table_counts


DATA = Path("data")
SONG_OCCURRENCES = DATA / "song_occurrences.json"
EVENT_DATE_PREDICTIONS = DATA / "event_date_predictions.json"
OUT_JSON = DATA / "historical_promotion_candidates.json"
OUT_MD = DATA / "historical_promotion_candidates.md"
TARGET_YEAR = 2026
MIN_AUTO_MATCH_SCORE = 3

WEEKDAY_RULE_TYPES = {
    "weekday_last",
    "weekday_nth",
    "weekday_near_day",
    "weekend_near_day",
}
DATE_RULE_TYPES = {
    "fixed_date",
    "date_near",
}


def rows(db_path, query, params=()):
    with connect_existing(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(query, params)]


def occurrence_by_series_year(db_path):
    data = rows(
        db_path,
        """
        SELECT occurrence_id, series_id, event_year, date_start, date_end, date_status
        FROM event_occurrences
        WHERE origin = 'curated'
        """,
    )
    return {
        (row["series_id"], row["event_year"]): row
        for row in data
    }


def evidence_year(ev):
    year = ev.get("year")
    if isinstance(year, int):
        return year
    for key in ("date", "event_start", "detected_event_date"):
        value = ev.get(key)
        if isinstance(value, str):
            match = re.match(r"^(20\d{2})-\d{2}-\d{2}$", value)
            if match:
                return int(match.group(1))
    text = ev.get("text") or ""
    match = re.search(r"(20\d{2})年", text)
    if match:
        return int(match.group(1))
    return None


def is_year_only_placeholder(ev, date_value):
    if not isinstance(date_value, str) or not re.match(r"^20\d{2}-01-01$", date_value):
        return False
    source = ev.get("source") or ""
    text = ev.get("text") or ""
    return source == "youtube_year_backfill_review" or "年ズレ" in text or "year backfill" in text


def evidence_dates_by_year(occurrence):
    exact_dates = defaultdict(set)
    year_only = defaultdict(int)
    evidence_urls = set()
    song_titles = set()
    evidence_counts = Counter()

    for song in occurrence.get("songs") or []:
        if song.get("song_name"):
            song_titles.add(song["song_name"])
        for ev in song.get("evidence") or []:
            year = evidence_year(ev)
            if not year or year >= TARGET_YEAR:
                continue
            evidence_counts[year] += 1
            if ev.get("url"):
                evidence_urls.add(ev["url"])
            date_values = []
            for key in ("date", "event_start", "detected_event_date"):
                value = ev.get(key)
                if isinstance(value, str) and re.match(r"^20\d{2}-\d{2}-\d{2}$", value):
                    date_values.append(value)
            text_dates = all_dates({"songs": [{"evidence": [ev]}]})
            date_values.extend(text_dates)
            year_has_exact = False
            for value in sorted(set(date_values)):
                if not value.startswith(f"{year}-"):
                    continue
                if is_year_only_placeholder(ev, value):
                    continue
                exact_dates[year].add(value)
                year_has_exact = True
            if not year_has_exact:
                year_only[year] += 1
    return {
        "years": set(exact_dates) | set(year_only),
        "exact_dates": {year: sorted(values) for year, values in exact_dates.items()},
        "year_only_counts": dict(year_only),
        "evidence_url_count": len(evidence_urls),
        "evidence_urls_sample": sorted(evidence_urls)[:10],
        "song_title_count": len(song_titles),
        "song_titles_sample": sorted(song_titles)[:20],
        "evidence_counts": dict(evidence_counts),
    }


def observed_rows(db_path):
    return rows(
        db_path,
        """
        SELECT observed_occurrence_id, source_occurrence_id, raw_event_name, raw_venue_name,
               event_year, quality_status, quality_flags_json
        FROM observed_occurrences
        WHERE quality_status IN ('matched_curated', 'review', 'discard_candidate')
        """,
    )


def merge_item(grouped, match):
    key = match["occurrence_id"]
    return grouped.setdefault(
        key,
        {
            "candidate_id": stable_id("histprom", key),
            "target_series_id": match["series_id"],
            "target_occurrence_id": key,
            "target_event_name": match["canonical_name"],
            "target_event_year": match["event_year"],
            "target_current_date": match.get("date_start") or "",
            "target_current_venue": match.get("venue") or "",
            "source_types": set(),
            "historical_years": set(),
            "exact_dates": defaultdict(set),
            "year_only_evidence_counts": Counter(),
            "prediction_summaries": [],
            "source_occurrence_ids": set(),
            "evidence_url_count": 0,
            "evidence_urls_sample": set(),
            "song_title_count": 0,
            "song_titles_sample": set(),
            "match_score": 0,
            "source_rows": [],
        },
    )


def add_song_occurrence_candidates(grouped, skipped, db_path, song_occurrences_path, curated_events):
    song_by_id = occurrence_by_id(song_occurrences_path)

    for row in observed_rows(db_path):
        source = song_by_id.get(row["source_occurrence_id"]) or {}
        evidence = evidence_dates_by_year(source)
        if not evidence["years"]:
            skipped["song_occurrences_no_historical_evidence"] += 1
            continue

        raw_text = " ".join([row.get("raw_event_name") or "", row.get("raw_venue_name") or ""])
        extracted_event = extract_event_name(row.get("raw_event_name") or "")
        match = best_curated_match(raw_text, extracted_event, curated_events)
        if not match:
            skipped["song_occurrences_no_curated_match"] += 1
            continue

        item = merge_item(grouped, match)
        item["source_types"].add("song_occurrences")
        item["historical_years"].update(evidence["years"])
        for year, dates in evidence["exact_dates"].items():
            item["exact_dates"][year].update(dates)
        item["year_only_evidence_counts"].update(evidence["year_only_counts"])
        item["source_occurrence_ids"].add(f"song_occurrences:{row['source_occurrence_id']}")
        item["evidence_url_count"] += evidence["evidence_url_count"]
        item["evidence_urls_sample"].update(evidence["evidence_urls_sample"])
        item["song_title_count"] += evidence["song_title_count"]
        item["song_titles_sample"].update(evidence["song_titles_sample"])
        item["match_score"] = max(item["match_score"], match["match_score"])
        item["source_rows"].append(
            {
                "source": "song_occurrences",
                "observed_occurrence_id": row["observed_occurrence_id"],
                "source_occurrence_id": row["source_occurrence_id"],
                "raw_event_name": row["raw_event_name"],
                "raw_venue_name": row["raw_venue_name"],
                "quality_status": row["quality_status"],
            }
        )


def prediction_rows(path):
    data = load_json(path, {})
    return data.get("predictions") or []


def add_event_date_prediction_candidates(grouped, skipped, path, curated_events):
    for row in prediction_rows(path):
        prediction = row.get("prediction") or {}
        evidence_rows = prediction.get("evidence_rows") or []
        years = {item.get("year") for item in evidence_rows if isinstance(item.get("year"), int) and item.get("year") < TARGET_YEAR}
        if len(years) < 2:
            skipped["event_date_predictions_less_than_two_years"] += 1
            continue
        raw_text = " ".join([row.get("event_name") or "", row.get("venue") or ""])
        match = best_curated_match(raw_text, row.get("event_name") or "", curated_events)
        if not match:
            skipped["event_date_predictions_no_curated_match"] += 1
            continue
        item = merge_item(grouped, match)
        item["source_types"].add("event_date_predictions")
        item["historical_years"].update(years)
        for ev in evidence_rows:
            year = ev.get("year")
            if not isinstance(year, int) or year >= TARGET_YEAR:
                continue
            for key in ("date_start", "date_end"):
                value = ev.get(key)
                if isinstance(value, str) and re.match(r"^20\d{2}-\d{2}-\d{2}$", value):
                    item["exact_dates"][year].add(value)
        item["source_occurrence_ids"].add(f"event_date_predictions:{row.get('series_key') or row.get('event_name')}")
        item["evidence_url_count"] += sum(int(ev.get("source_video_count") or 0) for ev in evidence_rows)
        item["match_score"] = max(item["match_score"], match["match_score"])
        item["prediction_summaries"].append(
            {
                "source": "event_date_predictions",
                "series_key": row.get("series_key"),
                "event_name": row.get("event_name"),
                "venue": row.get("venue"),
                "rule_type": prediction.get("rule_type"),
                "predicted_date_start": prediction.get("predicted_date_start"),
                "predicted_date_end": prediction.get("predicted_date_end"),
                "confidence": prediction.get("confidence"),
                "score": prediction.get("score"),
                "basis": prediction.get("basis"),
                "evidence_years": sorted(years),
                "evidence_rows": evidence_rows,
            }
        )
        item["source_rows"].append(
            {
                "source": "event_date_predictions",
                "series_key": row.get("series_key"),
                "event_name": row.get("event_name"),
                "venue": row.get("venue"),
            }
        )


def build_candidates(db_path, song_occurrences_path, event_date_predictions_path):
    curated_events = load_curated_events(db_path)
    grouped = {}
    skipped = Counter()
    add_song_occurrence_candidates(grouped, skipped, db_path, song_occurrences_path, curated_events)
    add_event_date_prediction_candidates(grouped, skipped, event_date_predictions_path, curated_events)

    candidates = []
    for item in grouped.values():
        years = sorted(item.pop("historical_years"))
        if len(years) < 2:
            skipped["less_than_two_years"] += 1
            continue
        exact_dates = {str(year): sorted(values) for year, values in item.pop("exact_dates").items()}
        year_only = {str(year): count for year, count in item.pop("year_only_evidence_counts").items()}
        source_types = sorted(item.pop("source_types"))
        prediction_summaries = item.pop("prediction_summaries")
        source_ids = sorted(item.pop("source_occurrence_ids"))
        urls = sorted(item.pop("evidence_urls_sample"))
        songs = sorted(item.pop("song_titles_sample"))
        high_match = item["match_score"] >= MIN_AUTO_MATCH_SCORE
        has_recent = 2025 in years or "event_date_predictions" in source_types
        auto_eligible = bool(high_match and has_recent)
        confidence = "high" if auto_eligible and 2025 in years else "medium" if auto_eligible else "low"
        item.update(
            {
                "source_types": source_types,
                "historical_years": years,
                "historical_year_count": len(years),
                "exact_dates": exact_dates,
                "year_only_evidence_counts": year_only,
                "prediction_summaries": prediction_summaries,
                "source_occurrence_ids": source_ids,
                "source_occurrence_count": len(source_ids),
                "evidence_urls_sample": urls[:10],
                "song_titles_sample": songs[:20],
                "promotion_confidence": confidence,
                "auto_promote_eligible": auto_eligible,
                "recommended_action": (
                    "auto_promote_historical_reference"
                    if auto_eligible
                    else "manual_review_multi_year_history"
                ),
                "notes": (
                    "Promote as historical evidence only; do not copy historical dates to 2026."
                    if auto_eligible
                    else "Multiple historical years found, but match confidence is below automatic threshold."
                ),
            }
        )
        candidates.append(item)

    candidates.sort(
        key=lambda row: (
            not row["auto_promote_eligible"],
            -row["historical_year_count"],
            -row["match_score"],
            row["target_event_name"],
        )
    )
    return candidates, skipped


def prediction_basis_type(rule_type):
    if rule_type in WEEKDAY_RULE_TYPES:
        return "weekday_based", "曜日ベース"
    if rule_type in DATE_RULE_TYPES:
        return "date_based", "日にちベース"
    return "pattern_based", "パターンベース"


def application_status_for_prediction(target_occurrence, prediction):
    if not target_occurrence:
        return "candidate_for_2026_occurrence"
    occurrence_date = target_occurrence.get("date_start") or ""
    occurrence_end = target_occurrence.get("date_end") or ""
    predicted_start = prediction.get("date_start") or ""
    predicted_end = prediction.get("date_end") or ""
    if occurrence_date and occurrence_date == predicted_start and (occurrence_end or "") == (predicted_end or ""):
        return "matches_curated"
    if occurrence_date:
        return "superseded_by_curated"
    return "candidate_for_existing_2026_occurrence"


def predicted_dates_for_candidate(item, occurrence_lookup=None):
    if not item.get("auto_promote_eligible"):
        return []
    occurrence_lookup = occurrence_lookup or {}
    target_occurrence = occurrence_lookup.get((item["target_series_id"], TARGET_YEAR))
    rows = []
    for prediction in item.get("prediction_summaries") or []:
        date_start = prediction.get("predicted_date_start") or ""
        if not date_start.startswith(f"{TARGET_YEAR}-"):
            continue
        rule_type = prediction.get("rule_type") or ""
        basis_type, basis_label = prediction_basis_type(rule_type)
        rows.append(
            {
                "predicted_date_id": stable_id("preddate", item["candidate_id"], date_start, prediction.get("predicted_date_end"), rule_type),
                "historical_candidate_id": item["candidate_id"],
                "target_series_id": item["target_series_id"],
                "target_occurrence_id": (target_occurrence or {}).get("occurrence_id"),
                "target_event_name": item["target_event_name"],
                "predicted_year": TARGET_YEAR,
                "date_start": date_start,
                "date_end": prediction.get("predicted_date_end") or "",
                "date_status": "predicted",
                "basis_type": basis_type,
                "basis_type_label": basis_label,
                "rule_type": rule_type,
                "basis": prediction.get("basis") or "",
                "confidence": prediction.get("confidence") or "unknown",
                "score": prediction.get("score"),
                "application_status": application_status_for_prediction(
                    target_occurrence,
                    {
                        "date_start": date_start,
                        "date_end": prediction.get("predicted_date_end") or "",
                    },
                ),
                "source": "event_date_predictions",
                "source_payload": prediction,
            }
        )
    return rows


def clear_predicted_date_sync_jobs(conn):
    conn.execute(
        """
        DELETE FROM notion_sync_jobs
        WHERE requested_by = ?
          AND target_table = 'predicted_occurrence_dates'
        """,
        ("build_historical_promotion_candidates.py",),
    )


def write_candidates_to_master(db_path, candidates):
    now = datetime.now(timezone.utc).isoformat()
    occurrence_lookup = occurrence_by_series_year(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM predicted_occurrence_dates")
        conn.execute("DELETE FROM historical_promotion_candidates")
        for item in candidates:
            conn.execute(
                """
                INSERT INTO historical_promotion_candidates(
                  candidate_id, target_series_id, target_occurrence_id, target_event_name,
                  source_types_json, historical_years_json, exact_dates_json, year_only_evidence_json,
                  prediction_json,
                  source_occurrence_ids_json, evidence_url_count, song_title_count,
                  match_score, promotion_confidence, auto_promote_eligible,
                  recommended_action, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["candidate_id"],
                    item["target_series_id"],
                    item["target_occurrence_id"],
                    item["target_event_name"],
                    json.dumps(item["source_types"], ensure_ascii=False),
                    json.dumps(item["historical_years"], ensure_ascii=False),
                    json.dumps(item["exact_dates"], ensure_ascii=False, sort_keys=True),
                    json.dumps(item["year_only_evidence_counts"], ensure_ascii=False, sort_keys=True),
                    json.dumps(item["prediction_summaries"], ensure_ascii=False, sort_keys=True),
                    json.dumps(item["source_occurrence_ids"], ensure_ascii=False),
                    item["evidence_url_count"],
                    item["song_title_count"],
                    item["match_score"],
                    item["promotion_confidence"],
                    int(item["auto_promote_eligible"]),
                    item["recommended_action"],
                    item["notes"],
                    now,
                    now,
                ),
            )
            predictions = predicted_dates_for_candidate(item, occurrence_lookup)
            for prediction in predictions:
                conn.execute(
                    """
                    INSERT INTO predicted_occurrence_dates(
                      predicted_date_id, historical_candidate_id, target_series_id, target_occurrence_id,
                      target_event_name, predicted_year, date_start, date_end, date_status,
                      basis_type, basis_type_label, rule_type, basis, confidence, score,
                      application_status, source, source_payload_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        prediction["predicted_date_id"],
                        prediction["historical_candidate_id"],
                        prediction["target_series_id"],
                        prediction["target_occurrence_id"],
                        prediction["target_event_name"],
                        prediction["predicted_year"],
                        prediction["date_start"],
                        prediction["date_end"],
                        prediction["date_status"],
                        prediction["basis_type"],
                        prediction["basis_type_label"],
                        prediction["rule_type"],
                        prediction["basis"],
                        prediction["confidence"],
                        prediction["score"],
                        prediction["application_status"],
                        prediction["source"],
                        json.dumps(prediction["source_payload"], ensure_ascii=False, sort_keys=True),
                        now,
                        now,
                    ),
                )
        clear_predicted_date_sync_jobs(conn)
        conn.commit()


def refresh_manifest(master_db, manifest_path, output_path):
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        return
    manifest = load_json(manifest_path, {})
    with connect_existing(master_db) as conn:
        manifest["table_counts"] = table_counts(conn)
    manifest["database_checksum"] = file_sha256(master_db)
    manifest.setdefault("post_build_outputs", {})
    manifest["post_build_outputs"]["historical_promotion_candidates"] = str(output_path)
    manifest.setdefault("post_build_steps", [])
    if "build_historical_promotion_candidates.py" not in manifest["post_build_steps"]:
        manifest["post_build_steps"].append("build_historical_promotion_candidates.py")
    write_json(manifest_path, manifest)


def render_markdown(data):
    lines = [
        "# Historical promotion candidates",
        "",
        f"- generated_at: {data['generated_at']}",
        f"- candidate_count: {data['summary']['candidate_count']}",
        f"- auto_promote_eligible_count: {data['summary']['auto_promote_eligible_count']}",
        f"- predicted_date_count: {data['summary']['predicted_date_count']}",
        f"- skipped: {data['summary']['skipped']}",
        "",
        "| auto | score | target | years | exact dates | year-only | urls | songs | action |",
        "| --- | ---: | --- | --- | --- | --- | ---: | ---: | --- |",
    ]
    for row in data["candidates"]:
        exact = "; ".join(f"{year}:{','.join(dates[:3])}" for year, dates in row["exact_dates"].items())
        year_only = ", ".join(f"{year}:{count}" for year, count in row["year_only_evidence_counts"].items())
        lines.append(
            f"| {'yes' if row['auto_promote_eligible'] else ''} | {row['match_score']} | "
            f"{row['target_event_name']} | {', '.join(str(year) for year in row['historical_years'])} | "
            f"{exact} | {year_only} | {row['evidence_url_count']} | {row['song_title_count']} | "
            f"{row['recommended_action']} |"
        )
    lines.extend(
        [
            "",
            "## 2026 predicted dates",
            "",
            "| target | predicted date | basis type | rule | basis | confidence | status |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in data["predicted_dates"]:
        date_value = row["date_start"]
        if row.get("date_end") and row["date_end"] != row["date_start"]:
            date_value = f"{row['date_start']} to {row['date_end']}"
        lines.append(
            f"| {row['target_event_name']} | {date_value} | {row['basis_type_label']} | "
            f"{row['rule_type']} | {row['basis']} | {row['confidence']} | {row['application_status']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(MASTER_DB))
    parser.add_argument("--song-occurrences", default=str(SONG_OCCURRENCES))
    parser.add_argument("--event-date-predictions", default=str(EVENT_DATE_PREDICTIONS))
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    parser.add_argument("--manifest", default=str(MASTER_MANIFEST))
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        require_confirmation(
            True,
            args.confirm,
            MASTER_RDB_ONE_OFF_CONFIRMATION,
            "master RDB historical promotion derived-table rebuild",
        )
    except ValueError as exc:
        parser.error(str(exc))

    candidates, skipped = build_candidates(
        Path(args.db),
        Path(args.song_occurrences),
        Path(args.event_date_predictions),
    )
    write_candidates_to_master(Path(args.db), candidates)
    predicted_dates = [
        prediction
        for candidate in candidates
            for prediction in predicted_dates_for_candidate(candidate, occurrence_by_series_year(Path(args.db)))
    ]
    data = {
        "generated_by": "build_historical_promotion_candidates.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "db": args.db,
            "song_occurrences": args.song_occurrences,
            "event_date_predictions": args.event_date_predictions,
        },
        "summary": {
            "candidate_count": len(candidates),
            "auto_promote_eligible_count": sum(1 for row in candidates if row["auto_promote_eligible"]),
            "predicted_date_count": len(predicted_dates),
            "notion_sync_jobs_queued": 0,
            "predicted_dates_by_basis_type": dict(Counter(row["basis_type_label"] for row in predicted_dates)),
            "by_confidence": dict(Counter(row["promotion_confidence"] for row in candidates)),
            "by_source_type": dict(
                Counter(source for row in candidates for source in row["source_types"])
            ),
            "skipped": dict(skipped),
        },
        "candidates": candidates,
        "predicted_dates": predicted_dates,
    }
    write_json(args.out_json, data)
    Path(args.out_md).write_text(render_markdown(data), encoding="utf-8")
    refresh_manifest(Path(args.db), Path(args.manifest), Path(args.out_json))
    print(
        "historical promotion candidates: "
        f"candidates={len(candidates)} "
        f"auto={data['summary']['auto_promote_eligible_count']} "
        f"predicted_dates={len(predicted_dates)} "
        f"skipped={dict(skipped)}"
    )


if __name__ == "__main__":
    main()
