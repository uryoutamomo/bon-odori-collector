"""Validate and materialize LLM judgments for event-date predictions.

The probability in this contract is deliberately joint: it means the chance
that the named event will be held in the target year *and* that its date range
will equal the prediction.  It is not a rule-fit score and it must not be used
as proof of an officially confirmed schedule.
"""

from __future__ import annotations

import argparse
import calendar
import json
import shutil
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "llm_event_date_judgment_v1"
PUBLIC_MEANING = "このイベントが、この予測日に開催される確からしさ"
PRIMARY_RULE_SOURCE_KINDS = {"organizer_primary", "municipality_primary"}
CURRENT_YEAR_SIGNAL_SOURCE_KINDS = {
    "community_organization",
    "independent_local",
    "local_official",
    "municipality_calendar",
    "organizer_secondary",
    "venue_host",
}
HISTORICAL_SOURCE_KINDS = {
    "organizer_archive",
    "municipality_archive",
    "trusted_post",
    "youtube_observation",
}
SUPPORTED_RULE_TYPES = {
    "fixed_date",
    "last_full_weekend",
    "weekday_last",
    "weekday_nth",
}


class EventDateJudgmentError(ValueError):
    """Raised when an LLM judgment violates the frozen contract."""


def certainty_label(probability: float) -> str:
    """Return the public Japanese label for the joint probability."""

    if probability >= 0.90:
        return "ほぼ確実"
    if probability >= 0.75:
        return "可能性が高い"
    if probability >= 0.55:
        return "可能性あり"
    if probability >= 0.30:
        return "参考予測"
    return "可能性は低い"


def legacy_confidence(probability: float) -> str:
    """Keep the old high/medium/low field for current public consumers."""

    if probability >= 0.75:
        return "high"
    if probability >= 0.55:
        return "medium"
    return "low"


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EventDateJudgmentError(f"{field} must be a non-empty string")
    return value.strip()


def _require_url(value: Any, field: str) -> str:
    value = _require_text(value, field)
    if not value.startswith(("https://", "http://")):
        raise EventDateJudgmentError(f"{field} must be an http(s) URL")
    return value


def _parse_iso_date(value: Any, field: str) -> date:
    value = _require_text(value, field)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise EventDateJudgmentError(f"{field} must be an ISO date") from exc


def _last_weekday(year: int, month: int, weekday: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    value = date(year, month, last_day)
    return value - timedelta(days=(value.weekday() - weekday) % 7)


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    first = date(year, month, 1)
    value = first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (nth - 1))
    if value.month != month:
        raise EventDateJudgmentError("weekday_nth does not exist in the requested month")
    return value


def expected_date_range(rule: Mapping[str, Any], year: int) -> tuple[str, str]:
    """Calculate a date range from the LLM-selected finite calendar rule."""

    rule_type = rule.get("type")
    if rule_type not in SUPPORTED_RULE_TYPES:
        raise EventDateJudgmentError(f"unsupported calendar_rule.type: {rule_type}")
    try:
        month = int(rule["month"])
        duration_days = int(rule.get("duration_days") or 1)
    except (KeyError, TypeError, ValueError) as exc:
        raise EventDateJudgmentError("calendar_rule month/duration_days must be integers") from exc
    if month not in range(1, 13) or duration_days not in range(1, 8):
        raise EventDateJudgmentError("calendar_rule month or duration_days is out of range")

    try:
        if rule_type == "fixed_date":
            start = date(year, month, int(rule["day"]))
        elif rule_type == "last_full_weekend":
            if duration_days != 2:
                raise EventDateJudgmentError("last_full_weekend requires duration_days=2")
            end = _last_weekday(year, month, 6)
            start = end - timedelta(days=1)
        elif rule_type == "weekday_last":
            start = _last_weekday(year, month, int(rule["weekday"]))
        else:
            start = _nth_weekday(year, month, int(rule["weekday"]), int(rule["nth"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise EventDateJudgmentError(f"invalid parameters for {rule_type}") from exc
    end = start + timedelta(days=duration_days - 1)
    if start.month != month or end.month != month:
        raise EventDateJudgmentError("calendar rule must keep the entire event inside its month")
    return start.isoformat(), end.isoformat()


def _validate_rule_source(raw: Any) -> dict | None:
    if raw in (None, {}):
        return None
    if not isinstance(raw, Mapping):
        raise EventDateJudgmentError("organizer_rule must be an object or null")
    source_kind = _require_text(raw.get("source_kind"), "organizer_rule.source_kind")
    if source_kind not in PRIMARY_RULE_SOURCE_KINDS:
        raise EventDateJudgmentError("organizer_rule must use a primary organizer/municipality source")
    return {
        "source_kind": source_kind,
        "source_url": _require_url(raw.get("source_url"), "organizer_rule.source_url"),
        "rule_text": _require_text(raw.get("rule_text"), "organizer_rule.rule_text"),
    }


def _validate_historical_matches(
    raw_rows: Any,
    *,
    target_year: int,
    calendar_rule: Mapping[str, Any],
) -> list[dict]:
    if not isinstance(raw_rows, list):
        raise EventDateJudgmentError("historical_matches must be a list")
    rows = []
    seen_years = set()
    for index, raw in enumerate(raw_rows):
        if not isinstance(raw, Mapping):
            raise EventDateJudgmentError(f"historical_matches[{index}] must be an object")
        try:
            year = int(raw["year"])
        except (KeyError, TypeError, ValueError) as exc:
            raise EventDateJudgmentError(f"historical_matches[{index}].year is invalid") from exc
        if year >= target_year or year in seen_years:
            raise EventDateJudgmentError("historical match years must be unique and before target_year")
        seen_years.add(year)
        start = _parse_iso_date(raw.get("date_start"), f"historical_matches[{index}].date_start")
        end = _parse_iso_date(raw.get("date_end"), f"historical_matches[{index}].date_end")
        expected_start, expected_end = expected_date_range(calendar_rule, year)
        if (start.isoformat(), end.isoformat()) != (expected_start, expected_end):
            raise EventDateJudgmentError(
                f"historical_matches[{index}] does not match calendar_rule: "
                f"expected {expected_start}..{expected_end}"
            )
        source_kind = _require_text(raw.get("source_kind"), f"historical_matches[{index}].source_kind")
        if source_kind not in HISTORICAL_SOURCE_KINDS:
            raise EventDateJudgmentError(f"unsupported historical source kind: {source_kind}")
        rows.append(
            {
                "year": year,
                "date_start": start.isoformat(),
                "date_end": end.isoformat(),
                "source_kind": source_kind,
                "source_url": _require_url(raw.get("source_url"), f"historical_matches[{index}].source_url"),
            }
        )
    return sorted(rows, key=lambda row: row["year"])


def _validate_current_signals(
    raw_rows: Any,
    *,
    target_year: int,
    predicted_range: tuple[str, str],
) -> list[dict]:
    if not isinstance(raw_rows, list):
        raise EventDateJudgmentError("current_year_signals must be a list")
    rows = []
    for index, raw in enumerate(raw_rows):
        if not isinstance(raw, Mapping):
            raise EventDateJudgmentError(f"current_year_signals[{index}] must be an object")
        source_kind = _require_text(raw.get("source_kind"), f"current_year_signals[{index}].source_kind")
        if source_kind not in CURRENT_YEAR_SIGNAL_SOURCE_KINDS:
            raise EventDateJudgmentError(f"unsupported current-year signal kind: {source_kind}")
        start = _parse_iso_date(raw.get("date_start"), f"current_year_signals[{index}].date_start")
        end = _parse_iso_date(raw.get("date_end"), f"current_year_signals[{index}].date_end")
        if start.year != target_year or end.year != target_year:
            raise EventDateJudgmentError("current-year signal date must belong to target_year")
        if (start.isoformat(), end.isoformat()) != predicted_range:
            raise EventDateJudgmentError("current-year signal must match the predicted date range exactly")
        rows.append(
            {
                "source_kind": source_kind,
                "source_url": _require_url(raw.get("source_url"), f"current_year_signals[{index}].source_url"),
                "date_start": start.isoformat(),
                "date_end": end.isoformat(),
                "description": _require_text(raw.get("description"), f"current_year_signals[{index}].description"),
            }
        )
    return rows


def probability_cap(*, has_primary_rule: bool, history_count: int, signal_count: int, conflicts: int) -> float:
    """Return the evidence ceiling; the LLM chooses the value below it."""

    if conflicts:
        return 0.49
    if has_primary_rule:
        if history_count >= 3 and signal_count:
            return 0.97
        if history_count >= 3:
            return 0.93
        if history_count >= 2 and signal_count:
            return 0.94
        if history_count >= 2:
            return 0.89
        if history_count >= 1 and signal_count:
            return 0.84
        return 0.69
    if history_count >= 4 and signal_count:
        return 0.92
    if history_count >= 3 and signal_count:
        return 0.89
    if history_count >= 4:
        return 0.87
    if history_count >= 3:
        return 0.84
    if history_count >= 2 and signal_count:
        return 0.82
    if history_count >= 2:
        return 0.74
    return 0.54


def validate_llm_judgment(raw: Mapping[str, Any]) -> dict:
    """Validate an LLM decision and add deterministic public fields."""

    if not isinstance(raw, Mapping) or raw.get("schema") != SCHEMA:
        raise EventDateJudgmentError(f"schema must be {SCHEMA}")
    if raw.get("official_current_year_confirmation") is not False:
        raise EventDateJudgmentError("official current-year dates must use the confirmed-date path")

    target_year = raw.get("target_year")
    if not isinstance(target_year, int) or target_year < 2000:
        raise EventDateJudgmentError("target_year must be an integer")
    calendar_rule = raw.get("calendar_rule")
    if not isinstance(calendar_rule, Mapping):
        raise EventDateJudgmentError("calendar_rule must be an object")
    calendar_rule = dict(calendar_rule)
    expected_range = expected_date_range(calendar_rule, target_year)
    proposed_range = (
        _parse_iso_date(raw.get("predicted_date_start"), "predicted_date_start").isoformat(),
        _parse_iso_date(raw.get("predicted_date_end"), "predicted_date_end").isoformat(),
    )
    if proposed_range != expected_range:
        raise EventDateJudgmentError(
            f"predicted range does not match calendar_rule: expected {expected_range[0]}..{expected_range[1]}"
        )

    organizer_rule = _validate_rule_source(raw.get("organizer_rule"))
    historical_matches = _validate_historical_matches(
        raw.get("historical_matches"),
        target_year=target_year,
        calendar_rule=calendar_rule,
    )
    current_signals = _validate_current_signals(
        raw.get("current_year_signals"),
        target_year=target_year,
        predicted_range=expected_range,
    )
    conflicts = raw.get("conflicts")
    if not isinstance(conflicts, list):
        raise EventDateJudgmentError("conflicts must be a list")
    conflicts = [_require_text(value, f"conflicts[{index}]") for index, value in enumerate(conflicts)]

    probability = raw.get("joint_probability")
    if isinstance(probability, bool) or not isinstance(probability, (int, float)):
        raise EventDateJudgmentError("joint_probability must be a number")
    probability = round(float(probability), 4)
    if not 0 <= probability < 1:
        raise EventDateJudgmentError("joint_probability must be in [0, 1)")
    cap = probability_cap(
        has_primary_rule=organizer_rule is not None,
        history_count=len(historical_matches),
        signal_count=len(current_signals),
        conflicts=len(conflicts),
    )
    if probability > cap:
        raise EventDateJudgmentError(
            f"joint_probability {probability:.2f} exceeds evidence cap {cap:.2f}"
        )
    label = certainty_label(probability)
    if raw.get("certainty_label") not in (None, label):
        raise EventDateJudgmentError(f"certainty_label must be {label}")

    normalized = dict(raw)
    normalized.update(
        {
            "predicted_date_start": expected_range[0],
            "predicted_date_end": expected_range[1],
            "calendar_rule": calendar_rule,
            "organizer_rule": organizer_rule,
            "historical_matches": historical_matches,
            "current_year_signals": current_signals,
            "conflicts": conflicts,
            "joint_probability": probability,
            "probability_percent": round(probability * 100),
            "certainty_label": label,
            "certainty_meaning": PUBLIC_MEANING,
            "legacy_confidence": legacy_confidence(probability),
            "date_certainty_tier": "rule_predicted",
            "machine_checks": {
                "evidence_cap": cap,
                "historical_match_count": len(historical_matches),
                "current_year_signal_count": len(current_signals),
                "calendar_rule_verified": True,
                "no_conflict": not conflicts,
            },
        }
    )
    for field in (
        "judgment_id",
        "predicted_date_id",
        "target_series_id",
        "target_event_name",
        "venue",
        "reason_summary",
    ):
        normalized[field] = _require_text(raw.get(field), field)
    return normalized


def validate_judgment_set(payload: Mapping[str, Any]) -> list[dict]:
    if not isinstance(payload, Mapping) or payload.get("schema") != "llm_event_date_judgment_set_v1":
        raise EventDateJudgmentError("unsupported judgment-set schema")
    rows = payload.get("judgments")
    if not isinstance(rows, list):
        raise EventDateJudgmentError("judgments must be a list")
    normalized = [validate_llm_judgment(row) for row in rows]
    ids = [row["judgment_id"] for row in normalized]
    if len(ids) != len(set(ids)):
        raise EventDateJudgmentError("judgment_id values must be unique")
    return normalized


def _prediction_snapshot(conn: sqlite3.Connection, predicted_date_id: str) -> dict:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT p.*, s.canonical_name AS series_name,
               o.event_year, o.current_event_state, o.date_certainty_tier,
               v.canonical_name AS venue_name
        FROM predicted_occurrence_dates p
        JOIN event_series s ON s.series_id = p.target_series_id
        LEFT JOIN event_occurrences o ON o.occurrence_id = p.target_occurrence_id
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE p.predicted_date_id = ?
        """,
        (predicted_date_id,),
    ).fetchone()
    if row is None:
        raise EventDateJudgmentError(f"unknown predicted_date_id: {predicted_date_id}")
    return dict(row)


def apply_validated_judgment(conn: sqlite3.Connection, judgment: Mapping[str, Any], *, now: str) -> dict:
    """Apply one validated judgment to an open prediction in a transaction."""

    judgment = validate_llm_judgment(judgment)
    before = _prediction_snapshot(conn, judgment["predicted_date_id"])
    expected = {
        "target_series_id": judgment["target_series_id"],
        "target_event_name": judgment["target_event_name"],
        "series_name": judgment["target_event_name"],
        "venue_name": judgment["venue"],
        "predicted_year": judgment["target_year"],
    }
    for field, value in expected.items():
        if before.get(field) != value:
            raise EventDateJudgmentError(
                f"frozen identity mismatch for {field}: database={before.get(field)!r}, judgment={value!r}"
            )
    if before.get("event_year") != judgment["target_year"]:
        raise EventDateJudgmentError("target occurrence year does not match target_year")
    if before.get("current_event_state") not in {"predicted", "announced"}:
        raise EventDateJudgmentError("only predicted/announced occurrences accept an LLM prediction")
    if before.get("application_status") not in {"candidate_for_2026_occurrence", "candidate_for_occurrence"}:
        raise EventDateJudgmentError("prediction is no longer an open candidate")

    try:
        prior_payload = json.loads(before.get("source_payload_json") or "{}")
    except json.JSONDecodeError:
        prior_payload = {"unparseable_source_payload": before.get("source_payload_json")}
    source_payload = {
        "series_key": judgment["target_series_id"],
        "event_name": judgment["target_event_name"],
        "venue": judgment["venue"],
        "predicted_date_start": judgment["predicted_date_start"],
        "predicted_date_end": judgment["predicted_date_end"],
        "rule_type": judgment["calendar_rule"]["type"],
        "basis": judgment["reason_summary"],
        "confidence": judgment["legacy_confidence"],
        "score": judgment["joint_probability"],
        "evidence_years": [row["year"] for row in judgment["historical_matches"]],
        "evidence_count": len(judgment["historical_matches"]),
        "joint_probability": judgment["joint_probability"],
        "probability_percent": judgment["probability_percent"],
        "certainty_label": judgment["certainty_label"],
        "certainty_meaning": judgment["certainty_meaning"],
        "llm_judgment": judgment,
        "prior_prediction": prior_payload,
    }
    conn.execute(
        """
        UPDATE predicted_occurrence_dates
        SET date_start=?, date_end=?, rule_type=?, basis=?, confidence=?, score=?,
            source='llm_event_date_judgment_v1', source_payload_json=?, updated_at=?
        WHERE predicted_date_id=?
        """,
        (
            judgment["predicted_date_start"],
            judgment["predicted_date_end"],
            judgment["calendar_rule"]["type"],
            judgment["reason_summary"],
            judgment["legacy_confidence"],
            judgment["joint_probability"],
            json.dumps(source_payload, ensure_ascii=False, sort_keys=True),
            now,
            judgment["predicted_date_id"],
        ),
    )
    conn.execute(
        """
        UPDATE event_occurrences
        SET date_certainty_tier='rule_predicted', updated_at=?
        WHERE occurrence_id=?
        """,
        (now, before["target_occurrence_id"]),
    )
    conn.execute(
        """
        UPDATE event_series
        SET schedule_rule_type=?, schedule_rule_detail=?, updated_at=?
        WHERE series_id=?
        """,
        (
            judgment["calendar_rule"]["type"],
            judgment["organizer_rule"]["rule_text"] if judgment["organizer_rule"] else judgment["reason_summary"],
            now,
            judgment["target_series_id"],
        ),
    )
    return {"before": before, "after": _prediction_snapshot(conn, judgment["predicted_date_id"]), "judgment": judgment}


def apply_judgment_set_to_copy(
    source_db: Path,
    output_db: Path,
    payload: Mapping[str, Any],
    *,
    now: str | None = None,
) -> dict:
    """Apply judgments to a DB copy; source_db is never opened for writing."""

    source_db = Path(source_db)
    output_db = Path(output_db)
    if source_db.resolve() == output_db.resolve():
        raise EventDateJudgmentError("output_db must differ from source_db")
    if not source_db.is_file():
        raise EventDateJudgmentError(f"source_db does not exist: {source_db}")
    if output_db.exists():
        raise EventDateJudgmentError(f"refusing to overwrite output_db: {output_db}")
    judgments = validate_judgment_set(payload)
    output_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_db, output_db)
    timestamp = now or datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(output_db)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        results = [apply_validated_judgment(conn, row, now=timestamp) for row in judgments]
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign_keys:
            raise EventDateJudgmentError("database validation failed after applying judgments")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {
        "schema": "llm_event_date_apply_report_v1",
        "source_db": str(source_db),
        "output_db": str(output_db),
        "applied_count": len(results),
        "integrity_check": "ok",
        "foreign_key_violations": 0,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate LLM event-date judgments and apply them to a new SQLite copy."
    )
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--output-db", required=True)
    parser.add_argument("--judgments", default="data/llm_event_date_prediction_judgments.json")
    parser.add_argument("--report")
    args = parser.parse_args()

    payload = json.loads(Path(args.judgments).read_text(encoding="utf-8"))
    report = apply_judgment_set_to_copy(Path(args.source_db), Path(args.output_db), payload)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
    print(
        "LLM event-date judgments: "
        f"applied={report['applied_count']} output={report['output_db']} integrity=ok"
    )


if __name__ == "__main__":
    main()
