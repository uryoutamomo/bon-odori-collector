"""Synchronize generated event-date predictions into the Master RDB.

The JSON file is a generated input, while ``predicted_occurrence_dates`` is
the canonical source consumed by public projection.  This command keeps only
the rows owned by ``event_date_predictions`` in sync.  Confirmed occurrence
dates and predictions promoted to a manual/LLM source are never overwritten.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import tempfile
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from event_model.year_context import normalize_target_year
from master_rdb.master_db import MASTER_DB, connect_existing, normalize_text, stable_id
from promotion_candidates.build_historical_promotion_candidates import (
    application_status_for_prediction,
    prediction_basis_type,
)


PREDICTION_SOURCE = "event_date_predictions"
CONFIRM_TEXT = "SYNC EVENT DATE PREDICTIONS"
DEFAULT_PREDICTIONS = Path("data/event_date_predictions.json")


class PredictionSyncError(ValueError):
    """Raised when generated predictions cannot be synchronized safely."""


def _load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PredictionSyncError(f"prediction JSON does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PredictionSyncError(f"prediction JSON is invalid: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PredictionSyncError("prediction JSON root must be an object")
    return payload


def _parse_prediction_date(value: Any, field: str, *, target_year: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PredictionSyncError(f"{field} must be a non-empty ISO date")
    try:
        parsed = date.fromisoformat(value.strip())
    except ValueError as exc:
        raise PredictionSyncError(f"{field} must be an ISO date: {value!r}") from exc
    if parsed.year != target_year:
        raise PredictionSyncError(
            f"{field} year must equal target_year {target_year}: {value!r}"
        )
    return parsed.isoformat()


def load_prediction_rows(path: Path, *, target_year: int) -> list[dict]:
    """Validate the generated JSON boundary before resolving any RDB identity."""

    target_year = normalize_target_year(target_year)
    payload = _load_json(path)
    payload_year = payload.get("target_year")
    if payload_year not in (None, target_year):
        raise PredictionSyncError(
            f"prediction JSON target_year mismatch: expected {target_year}, got {payload_year!r}"
        )
    raw_rows = payload.get("predictions")
    if not isinstance(raw_rows, list):
        raise PredictionSyncError("prediction JSON predictions must be a list")

    rows = []
    seen_series_keys = set()
    for index, raw in enumerate(raw_rows):
        if not isinstance(raw, dict):
            raise PredictionSyncError(f"predictions[{index}] must be an object")
        event_name = str(raw.get("event_name") or "").strip()
        venue = str(raw.get("venue") or "").strip()
        series_key = str(raw.get("series_key") or "").strip()
        if not event_name or not venue or not series_key:
            raise PredictionSyncError(
                f"predictions[{index}] requires series_key, event_name, and venue"
            )
        if series_key in seen_series_keys:
            raise PredictionSyncError(f"duplicate prediction series_key: {series_key}")
        seen_series_keys.add(series_key)
        row_year = raw.get("target_year")
        if row_year != target_year:
            raise PredictionSyncError(
                f"predictions[{index}].target_year must equal {target_year}: {row_year!r}"
            )
        prediction = raw.get("prediction")
        if not isinstance(prediction, dict):
            raise PredictionSyncError(f"predictions[{index}].prediction must be an object")
        start = _parse_prediction_date(
            prediction.get("predicted_date_start"),
            f"predictions[{index}].prediction.predicted_date_start",
            target_year=target_year,
        )
        end = _parse_prediction_date(
            prediction.get("predicted_date_end") or start,
            f"predictions[{index}].prediction.predicted_date_end",
            target_year=target_year,
        )
        if end < start:
            raise PredictionSyncError(f"predictions[{index}] date_end precedes date_start")
        normalized = dict(raw)
        normalized["event_name"] = event_name
        normalized["venue"] = venue
        normalized["series_key"] = series_key
        normalized["target_year"] = target_year
        normalized["prediction"] = {**prediction, "predicted_date_start": start, "predicted_date_end": end}
        rows.append(normalized)
    return rows


def _identity_index(conn: sqlite3.Connection, *, target_year: int) -> dict[str, dict]:
    conn.row_factory = sqlite3.Row
    series = {
        row["series_id"]: {
            "series_id": row["series_id"],
            "canonical_name": row["canonical_name"],
            "canonical_norm": normalize_text(row["canonical_name"]),
            "event_names": {normalize_text(row["canonical_name"])},
            "occurrences": [],
        }
        for row in conn.execute("SELECT series_id, canonical_name FROM event_series")
    }
    for row in conn.execute("SELECT series_id, alias FROM event_series_aliases"):
        if row["series_id"] in series:
            series[row["series_id"]]["event_names"].add(normalize_text(row["alias"]))

    venue_names: dict[str, set[str]] = defaultdict(set)
    for row in conn.execute("SELECT venue_id, canonical_name FROM venues"):
        venue_names[row["venue_id"]].add(normalize_text(row["canonical_name"]))
    for row in conn.execute("SELECT venue_id, alias FROM venue_aliases"):
        venue_names[row["venue_id"]].add(normalize_text(row["alias"]))

    for row in conn.execute(
        """
        SELECT occurrence_id, series_id, event_year, venue_id, date_start, date_end
        FROM event_occurrences
        WHERE origin = 'curated'
        ORDER BY event_year DESC, occurrence_id
        """
    ):
        item = series.get(row["series_id"])
        if item is None:
            continue
        occurrence = dict(row)
        occurrence["venue_names"] = venue_names.get(row["venue_id"], set())
        item["occurrences"].append(occurrence)
    for item in series.values():
        item["target_occurrence"] = next(
            (row for row in item["occurrences"] if row["event_year"] == target_year),
            None,
        )
    return series


def _event_name_matches(event_norm: str, item: dict) -> tuple[bool, str]:
    if event_norm in item["event_names"]:
        return True, "exact_or_alias"
    canonical = item["canonical_norm"]
    # Generated names sometimes retain a locality, edition number, or the
    # ``盆踊り`` program suffix around the canonical series name.  Venue
    # equality and unique-series resolution below keep this shortcut bounded.
    if len(canonical) >= 6 and canonical in event_norm:
        return True, "canonical_contained"
    return False, ""


def resolve_prediction(row: dict, index: dict[str, dict], *, target_year: int) -> dict:
    event_norm = normalize_text(row["event_name"])
    venue_norm = normalize_text(row["venue"])
    candidates = []
    for item in index.values():
        name_matches, match_kind = _event_name_matches(event_norm, item)
        if not name_matches:
            continue
        venue_scope = (
            [item["target_occurrence"]]
            if item["target_occurrence"] is not None
            else item["occurrences"]
        )
        if not any(venue_norm in occurrence["venue_names"] for occurrence in venue_scope):
            continue
        candidates.append((item, match_kind))
    if len(candidates) != 1:
        names = sorted(item["canonical_name"] for item, _ in candidates)
        reason = "unmatched" if not candidates else f"ambiguous: {names}"
        raise PredictionSyncError(
            f"prediction identity {reason}: {row['event_name']} @ {row['venue']}"
        )
    item, match_kind = candidates[0]
    target_occurrence = item["target_occurrence"]
    anchor_occurrence = target_occurrence or next(iter(item["occurrences"]), None)
    if anchor_occurrence is None:
        raise PredictionSyncError(
            f"resolved series has no curated occurrence: {item['canonical_name']}"
        )
    return {
        "series": item,
        "target_occurrence": target_occurrence,
        "anchor_occurrence": anchor_occurrence,
        "match_kind": match_kind,
        "target_year": target_year,
    }


def _source_payload(row: dict) -> dict:
    prediction = row["prediction"]
    payload = {
        "series_key": row["series_key"],
        "event_name": row["event_name"],
        "venue": row["venue"],
        "predicted_date_start": prediction["predicted_date_start"],
        "predicted_date_end": prediction["predicted_date_end"],
        "rule_type": prediction.get("rule_type") or "",
        "basis": prediction.get("basis") or "",
        "confidence": prediction.get("confidence") or "unknown",
        "score": prediction.get("score"),
        "evidence_years": prediction.get("evidence_years") or [],
        "evidence_count": prediction.get("evidence_count"),
        "evidence_rows": prediction.get("evidence_rows") or [],
        "candidate_rules": row.get("candidate_rules") or [prediction],
        "actual_observations": row.get("actual_observations") or [],
    }
    for key in (
        "joint_probability",
        "probability_percent",
        "certainty_label",
        "certainty_meaning",
    ):
        if key in prediction:
            payload[key] = prediction[key]
    return payload


def _desired_prediction(
    row: dict,
    resolved: dict,
    *,
    historical_candidate_id: str | None = None,
) -> dict:
    prediction = row["prediction"]
    series = resolved["series"]
    target_occurrence = resolved["target_occurrence"]
    anchor = resolved["anchor_occurrence"]
    candidate_id = historical_candidate_id or stable_id(
        "histprom", anchor["occurrence_id"]
    )
    rule_type = prediction.get("rule_type") or ""
    basis_type, basis_label = prediction_basis_type(rule_type)
    date_start = prediction["predicted_date_start"]
    date_end = prediction["predicted_date_end"]
    predicted_date_id = stable_id(
        "preddate", candidate_id, date_start, date_end, rule_type
    )
    status = application_status_for_prediction(
        target_occurrence,
        {"date_start": date_start, "date_end": date_end},
    )
    return {
        "predicted_date_id": predicted_date_id,
        "historical_candidate_id": candidate_id,
        "target_series_id": series["series_id"],
        "target_occurrence_id": (target_occurrence or {}).get("occurrence_id"),
        "target_event_name": series["canonical_name"],
        "predicted_year": resolved["target_year"],
        "date_start": date_start,
        "date_end": date_end,
        "date_status": "predicted",
        "basis_type": basis_type,
        "basis_type_label": basis_label,
        "rule_type": rule_type,
        "basis": prediction.get("basis") or "",
        "confidence": prediction.get("confidence") or "unknown",
        "score": prediction.get("score"),
        "application_status": status,
        "source": PREDICTION_SOURCE,
        "source_payload_json": json.dumps(
            _source_payload(row), ensure_ascii=False, sort_keys=True
        ),
        "anchor_occurrence_id": anchor["occurrence_id"],
        "match_kind": resolved["match_kind"],
        "source_row": row,
    }


def build_sync_plan(conn: sqlite3.Connection, rows: list[dict], *, target_year: int) -> list[dict]:
    index = _identity_index(conn, target_year=target_year)
    conn.row_factory = sqlite3.Row
    existing_by_series_key = {}
    existing_by_target_series = {}
    for existing in conn.execute(
        """
        SELECT p.predicted_date_id, p.historical_candidate_id, p.target_series_id,
               p.source_payload_json, c.target_series_id AS candidate_series_id
        FROM predicted_occurrence_dates p
        JOIN historical_promotion_candidates c
          ON c.candidate_id = p.historical_candidate_id
        WHERE p.source=? AND p.predicted_year=?
        """,
        (PREDICTION_SOURCE, target_year),
    ):
        try:
            payload = json.loads(existing["source_payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        series_key = str(payload.get("series_key") or "").strip()
        if series_key:
            if series_key in existing_by_series_key:
                raise PredictionSyncError(
                    f"multiple existing RDB predictions use series_key: {series_key}"
                )
            existing_by_series_key[series_key] = dict(existing)
        existing_by_target_series.setdefault(existing["target_series_id"], []).append(
            dict(existing)
        )

    desired = []
    for row in rows:
        resolved = resolve_prediction(row, index, target_year=target_year)
        existing = existing_by_series_key.get(row["series_key"])
        if existing is None:
            same_series = existing_by_target_series.get(resolved["series"]["series_id"], [])
            if len(same_series) == 1:
                existing = same_series[0]
        candidate_id = None
        if existing is not None:
            # A previously fuzzy-resolved row can point at the wrong series.
            # Do not carry its candidate identity forward; the old owned row
            # becomes stale and is removed after the exact resolution succeeds.
            if existing["candidate_series_id"] == resolved["series"]["series_id"]:
                candidate_id = existing["historical_candidate_id"]
        desired.append(
            _desired_prediction(
                row,
                resolved,
                historical_candidate_id=candidate_id,
            )
        )
    ids = [row["predicted_date_id"] for row in desired]
    if len(ids) != len(set(ids)):
        raise PredictionSyncError("multiple JSON predictions resolved to the same predicted_date_id")
    return desired


def _candidate_values(row: dict, *, now: str) -> dict:
    source_row = row["source_row"]
    prediction = source_row["prediction"]
    evidence_rows = prediction.get("evidence_rows") or []
    evidence_years = sorted(
        {
            item.get("year")
            for item in evidence_rows
            if isinstance(item, dict) and isinstance(item.get("year"), int)
        }
        or {year for year in prediction.get("evidence_years") or [] if isinstance(year, int)}
    )
    exact_dates: dict[str, list[str]] = defaultdict(list)
    for item in evidence_rows:
        if not isinstance(item, dict) or not isinstance(item.get("year"), int):
            continue
        values = {
            value
            for value in (item.get("date_start"), item.get("date_end"))
            if isinstance(value, str) and value.startswith(f"{item['year']}-")
        }
        exact_dates[str(item["year"])].extend(sorted(values))
    source_id = f"event_date_predictions:{source_row['series_key']}"
    return {
        "candidate_id": row["historical_candidate_id"],
        "target_series_id": row["target_series_id"],
        "target_occurrence_id": row["anchor_occurrence_id"],
        "target_event_name": row["target_event_name"],
        "source_types_json": json.dumps([PREDICTION_SOURCE], ensure_ascii=False),
        "historical_years_json": json.dumps(evidence_years, ensure_ascii=False),
        "exact_dates_json": json.dumps(dict(exact_dates), ensure_ascii=False, sort_keys=True),
        "year_only_evidence_json": "{}",
        "prediction_json": json.dumps([_source_payload(source_row)], ensure_ascii=False, sort_keys=True),
        "source_occurrence_ids_json": json.dumps([source_id], ensure_ascii=False),
        "evidence_url_count": sum(
            int(item.get("source_video_count") or 0)
            for item in evidence_rows
            if isinstance(item, dict)
        ),
        "song_title_count": 0,
        "match_score": 6 if row["match_kind"] == "exact_or_alias" else 5,
        "promotion_confidence": prediction.get("confidence") or "unknown",
        "auto_promote_eligible": 1,
        "recommended_action": "auto_promote_historical_reference",
        "notes": "Support row created by the narrow event-date prediction sync.",
        "created_at": now,
        "updated_at": now,
    }


PREDICTION_COLUMNS = (
    "predicted_date_id",
    "historical_candidate_id",
    "target_series_id",
    "target_occurrence_id",
    "target_event_name",
    "predicted_year",
    "date_start",
    "date_end",
    "date_status",
    "basis_type",
    "basis_type_label",
    "rule_type",
    "basis",
    "confidence",
    "score",
    "application_status",
    "source",
    "source_payload_json",
)


def _apply_plan(conn: sqlite3.Connection, desired: list[dict], *, target_year: int, now: str) -> dict:
    conn.row_factory = sqlite3.Row
    before_occurrences = [
        tuple(row)
        for row in conn.execute("SELECT * FROM event_occurrences ORDER BY occurrence_id")
    ]
    candidate_inserted = 0
    for row in desired:
        candidate = _candidate_values(row, now=now)
        columns = tuple(candidate)
        cursor = conn.execute(
            f"INSERT OR IGNORE INTO historical_promotion_candidates "
            f"({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            tuple(candidate[column] for column in columns),
        )
        candidate_inserted += cursor.rowcount

    desired_ids = {row["predicted_date_id"] for row in desired}
    current_owned = {
        row["predicted_date_id"]: dict(row)
        for row in conn.execute(
            "SELECT * FROM predicted_occurrence_dates WHERE source=? AND predicted_year=?",
            (PREDICTION_SOURCE, target_year),
        )
    }
    stale_ids = sorted(set(current_owned) - desired_ids)
    if stale_ids:
        conn.executemany(
            "DELETE FROM predicted_occurrence_dates WHERE predicted_date_id=? AND source=?",
            [(prediction_id, PREDICTION_SOURCE) for prediction_id in stale_ids],
        )

    inserted = updated = unchanged = protected = 0
    details = []
    for row in desired:
        existing = conn.execute(
            "SELECT * FROM predicted_occurrence_dates WHERE predicted_date_id=?",
            (row["predicted_date_id"],),
        ).fetchone()
        values = {column: row[column] for column in PREDICTION_COLUMNS}
        if existing is not None and existing["source"] != PREDICTION_SOURCE:
            identity_fields = (
                "target_series_id",
                "predicted_year",
                "date_start",
                "date_end",
            )
            if any(existing[field] != values[field] for field in identity_fields):
                raise PredictionSyncError(
                    f"protected prediction ID collision: {row['predicted_date_id']}"
                )
            protected += 1
            action = "protected"
        elif existing is None:
            columns = PREDICTION_COLUMNS + ("created_at", "updated_at")
            conn.execute(
                f"INSERT INTO predicted_occurrence_dates ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                tuple(values.get(column, now) for column in columns),
            )
            inserted += 1
            action = "inserted"
        else:
            changed = any(existing[column] != values[column] for column in PREDICTION_COLUMNS[1:])
            if changed:
                assignments = ", ".join(f"{column}=?" for column in PREDICTION_COLUMNS[1:])
                conn.execute(
                    f"UPDATE predicted_occurrence_dates SET {assignments}, updated_at=? "
                    "WHERE predicted_date_id=? AND source=?",
                    tuple(values[column] for column in PREDICTION_COLUMNS[1:])
                    + (now, row["predicted_date_id"], PREDICTION_SOURCE),
                )
                updated += 1
                action = "updated"
            else:
                unchanged += 1
                action = "unchanged"
        details.append(
            {
                "predicted_date_id": row["predicted_date_id"],
                "series_key": row["source_row"]["series_key"],
                "event_name": row["source_row"]["event_name"],
                "target_series_id": row["target_series_id"],
                "target_occurrence_id": row["target_occurrence_id"],
                "match_kind": row["match_kind"],
                "action": action,
            }
        )

    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
    after_occurrences = [
        tuple(row)
        for row in conn.execute("SELECT * FROM event_occurrences ORDER BY occurrence_id")
    ]
    if integrity != "ok" or foreign_keys or before_occurrences != after_occurrences:
        raise PredictionSyncError(
            "prediction sync verification failed: "
            f"integrity={integrity!r} foreign_keys={len(foreign_keys)} "
            f"event_occurrences_changed={before_occurrences != after_occurrences}"
        )
    summary = {
        "input_prediction_count": len(desired),
        "resolved_prediction_count": len(desired),
        "inserted_count": inserted,
        "updated_count": updated,
        "deleted_stale_count": len(stale_ids),
        "unchanged_count": unchanged,
        "protected_count": protected,
        "support_candidate_inserted_count": candidate_inserted,
    }
    summary["change_count"] = inserted + updated + len(stale_ids) + candidate_inserted
    return {
        "summary": summary,
        "verification": {
            "integrity_check": integrity,
            "foreign_key_issue_count": len(foreign_keys),
            "event_occurrences_unchanged": True,
        },
        "predictions": details,
    }


def _apply_to_path(db_path: Path, rows: list[dict], *, target_year: int, now: str) -> dict:
    with connect_existing(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            desired = build_sync_plan(conn, rows, target_year=target_year)
            result = _apply_plan(conn, desired, target_year=target_year, now=now)
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise


def run(
    *,
    db_path: Path,
    predictions_path: Path,
    target_year: int,
    execute: bool = False,
    confirm: str | None = None,
    check: bool = False,
    now: str | None = None,
) -> dict:
    """Preflight on a copy, then optionally apply the identical plan to the DB."""

    if execute and check:
        raise PredictionSyncError("--execute and --check are mutually exclusive")
    if execute and confirm != CONFIRM_TEXT:
        raise PredictionSyncError(f"--execute requires --confirm {CONFIRM_TEXT!r}")
    db_path = Path(db_path)
    predictions_path = Path(predictions_path)
    if not db_path.is_file():
        raise PredictionSyncError(f"master RDB does not exist: {db_path}")
    target_year = normalize_target_year(target_year)
    rows = load_prediction_rows(predictions_path, target_year=target_year)
    timestamp = now or datetime.now(timezone.utc).isoformat()

    with tempfile.TemporaryDirectory(prefix="event-date-prediction-sync-") as temp_dir:
        preflight_db = Path(temp_dir) / db_path.name
        shutil.copy2(db_path, preflight_db)
        preflight = _apply_to_path(
            preflight_db, rows, target_year=target_year, now=timestamp
        )

    if execute:
        applied = _apply_to_path(db_path, rows, target_year=target_year, now=timestamp)
        if applied["summary"] != preflight["summary"]:
            raise PredictionSyncError("preflight/apply summary mismatch")
        result = applied
        mode = "execute"
    else:
        result = preflight
        mode = "check" if check else "dry_run"
    status = (
        "changes_required"
        if check and result["summary"]["change_count"]
        else "pass"
    )
    return {
        "schema": "event_date_prediction_rdb_sync_v1",
        "mode": mode,
        "status": status,
        "target_year": target_year,
        "source_db": str(db_path),
        "predictions_path": str(predictions_path),
        **result,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Synchronize generated event-date predictions into the Master RDB."
    )
    parser.add_argument("--db", type=Path, default=MASTER_DB)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--target-year", type=int, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--confirm")
    parser.add_argument("--report-out", type=Path)
    args = parser.parse_args(argv)
    try:
        report = run(
            db_path=args.db,
            predictions_path=args.predictions,
            target_year=args.target_year,
            execute=args.execute,
            confirm=args.confirm,
            check=args.check,
        )
    except PredictionSyncError as exc:
        parser.error(str(exc))
    if args.report_out:
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False))
    return 1 if report["status"] != "pass" else 0


if __name__ == "__main__":
    raise SystemExit(main())
