"""Build weekday-first event date predictions from yearly observations."""

import argparse
import calendar
import json
import statistics
import tempfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from event_model.year_context import normalize_target_year


DATA = Path("data")
OBSERVATIONS = DATA / "event_occurrence_observations.json"
OUT = DATA / "event_date_predictions.json"
MD_OUT = DATA / "event_date_predictions.md"
WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".tmp-", suffix=".json", delete=False
    ) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        tmp_name = handle.name
    Path(tmp_name).replace(path)


def atomic_write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".tmp-", suffix=".md", delete=False
    ) as handle:
        handle.write(text)
        tmp_name = handle.name
    Path(tmp_name).replace(path)


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def fmt(value):
    return value.isoformat()


def weekday_label(value):
    return WEEKDAYS[value.weekday()]


def duration_days(row):
    start = parse_date(row["date_start"])
    end = parse_date(row.get("date_end") or row["date_start"])
    return max(1, (end - start).days + 1)


def nth_weekday_in_month(value):
    return ((value.day - 1) // 7) + 1


def is_last_weekday_in_month(value):
    return (value + timedelta(days=7)).month != value.month


def nth_weekday_date(year, month, weekday, nth):
    current = date(year, month, 1)
    offset = (weekday - current.weekday()) % 7
    candidate = current + timedelta(days=offset + 7 * (nth - 1))
    if candidate.month != month:
        return None
    return candidate


def last_weekday_date(year, month, weekday):
    _, last_day = calendar.monthrange(year, month)
    current = date(year, month, last_day)
    offset = (current.weekday() - weekday) % 7
    return current - timedelta(days=offset)


def nearest_weekday_to_day(year, month, weekday, target_day):
    _, last_day = calendar.monthrange(year, month)
    target_day = min(max(1, round(target_day)), last_day)
    candidates = []
    for day in range(1, last_day + 1):
        candidate = date(year, month, day)
        if candidate.weekday() == weekday:
            candidates.append(candidate)
    return min(candidates, key=lambda value: (abs(value.day - target_day), value.day))


def add_duration(start, duration):
    return start + timedelta(days=max(1, duration) - 1)


def median_int(values):
    return int(round(statistics.median(values)))


def confidence_label(score):
    if score >= 0.8:
        return "high"
    if score >= 0.6:
        return "medium"
    return "low"


def row_features(row):
    start = parse_date(row["date_start"])
    return {
        "year": row["year"],
        "month": start.month,
        "day": start.day,
        "weekday": start.weekday(),
        "weekday_label": weekday_label(start),
        "nth_weekday": nth_weekday_in_month(start),
        "is_last_weekday": is_last_weekday_in_month(start),
        "duration": duration_days(row),
        "confidence": row.get("confidence") or "",
        "source_video_count": row.get("source_video_count") or 0,
        "date_start": row["date_start"],
        "date_end": row.get("date_end") or row["date_start"],
    }


def candidate_payload(rule_type, rows, start, duration, score, reason):
    years = sorted({row["year"] for row in rows})
    return {
        "rule_type": rule_type,
        "predicted_date_start": fmt(start),
        "predicted_date_end": fmt(add_duration(start, duration)),
        "predicted_weekday_start": weekday_label(start),
        "predicted_weekday_end": weekday_label(add_duration(start, duration)),
        "duration_days": duration,
        "score": round(score, 2),
        "confidence": confidence_label(score),
        "basis": reason,
        "evidence_years": years,
        "evidence_count": len(years),
        "evidence_rows": [
            {
                "year": row["year"],
                "date_start": row["date_start"],
                "date_end": row["date_end"],
                "weekday_start": row["weekday_label"],
                "duration_days": row["duration"],
                "confidence": row["confidence"],
                "source_video_count": row["source_video_count"],
            }
            for row in sorted(rows, key=lambda item: item["year"])
        ],
    }


def weekday_rule_candidates(features, target_year):
    candidates = []
    by_last = defaultdict(list)
    by_nth = defaultdict(list)
    by_month_weekday = defaultdict(list)
    by_month = defaultdict(list)
    for row in features:
        by_month[row["month"]].append(row)
        by_month_weekday[(row["month"], row["weekday"])].append(row)
        if row["is_last_weekday"]:
            by_last[(row["month"], row["weekday"])].append(row)
        by_nth[(row["month"], row["weekday"], row["nth_weekday"])].append(row)

    for (month, weekday), rows in by_last.items():
        years = {row["year"] for row in rows}
        if len(years) < 2:
            continue
        duration = max(row["duration"] for row in rows)
        start = last_weekday_date(target_year, month, weekday)
        score = 0.86 if len(years) >= 3 else 0.74
        candidates.append(candidate_payload(
            "weekday_last",
            rows,
            start,
            duration,
            score,
            f"{month}月の最終{WEEKDAYS[weekday]}曜",
        ))

    for (month, weekday, nth), rows in by_nth.items():
        years = {row["year"] for row in rows}
        if len(years) < 2:
            continue
        start = nth_weekday_date(target_year, month, weekday, nth)
        if not start:
            continue
        duration = max(row["duration"] for row in rows)
        score = 0.82 if len(years) >= 3 else 0.7
        candidates.append(candidate_payload(
            "weekday_nth",
            rows,
            start,
            duration,
            score,
            f"{month}月第{nth}{WEEKDAYS[weekday]}曜",
        ))

    for (month, weekday), rows in by_month_weekday.items():
        years = {row["year"] for row in rows}
        if len(years) < 2:
            continue
        days = [row["day"] for row in rows]
        start = nearest_weekday_to_day(target_year, month, weekday, statistics.median(days))
        duration = max(row["duration"] for row in rows)
        spread = max(days) - min(days)
        score = 0.68 if spread <= 7 else 0.6
        if len(years) >= 3:
            score += 0.06
        candidates.append(candidate_payload(
            "weekday_near_day",
            rows,
            start,
            duration,
            min(score, 0.78),
            f"{month}月{round(statistics.median(days))}日前後の{WEEKDAYS[weekday]}曜",
        ))

    for month, rows in by_month.items():
        years = {row["year"] for row in rows}
        if len(years) < 2:
            continue
        days = [row["day"] for row in rows]
        if max(days) - min(days) > 7:
            continue
        weekendish = [row for row in rows if row["weekday"] in {3, 4, 5, 6}]
        if len({row["year"] for row in weekendish}) < 2:
            continue
        start = nearest_weekday_to_day(target_year, month, 5, statistics.median(days))
        duration = max(1, median_int([row["duration"] for row in rows]))
        score = 0.64 if len(years) >= 3 else 0.6
        candidates.append(candidate_payload(
            "weekend_near_day",
            rows,
            start,
            duration,
            score,
            f"{month}月{round(statistics.median(days))}日前後の週末",
        ))
    return candidates


def date_rule_candidates(features, target_year):
    candidates = []
    by_month_day = defaultdict(list)
    by_month = defaultdict(list)
    for row in features:
        by_month_day[(row["month"], row["day"])].append(row)
        by_month[row["month"]].append(row)

    for (month, day), rows in by_month_day.items():
        years = {row["year"] for row in rows}
        if len(years) < 2:
            continue
        duration = max(row["duration"] for row in rows)
        all_observed_starts_match = len(rows) == len(features)
        if len(years) >= 3 or all_observed_starts_match:
            score = 0.8 if len(years) >= 3 else 0.72
        else:
            score = 0.56
        candidates.append(candidate_payload(
            "fixed_date",
            rows,
            date(target_year, month, day),
            duration,
            score,
            f"毎年{month}/{day}開始",
        ))

    for month, rows in by_month.items():
        years = {row["year"] for row in rows}
        if len(years) < 2:
            continue
        days = [row["day"] for row in rows]
        spread = max(days) - min(days)
        if spread > 7:
            continue
        duration = max(row["duration"] for row in rows)
        day = min(max(1, median_int(days)), calendar.monthrange(target_year, month)[1])
        score = 0.58 if spread <= 3 else 0.5
        candidates.append(candidate_payload(
            "date_near",
            rows,
            date(target_year, month, day),
            duration,
            score,
            f"{month}月{day}日前後",
        ))
    return candidates


def choose_prediction(candidates):
    if not candidates:
        return None
    priority = {
        "weekday_last": 0,
        "weekday_nth": 1,
        "weekday_near_day": 2,
        "weekend_near_day": 3,
        "fixed_date": 4,
        "date_near": 5,
    }
    return sorted(
        candidates,
        key=lambda row: (-row["score"], priority.get(row["rule_type"], 99), row["predicted_date_start"]),
    )[0]


def build_predictions(payload, target_year):
    target_year = normalize_target_year(target_year)
    grouped = defaultdict(list)
    actual_by_series = defaultdict(list)
    for row in payload.get("observations") or []:
        if row["year"] < target_year:
            grouped[row["series_key"]].append(row)
        elif row["year"] == target_year:
            actual_by_series[row["series_key"]].append(row)

    predictions = []
    for series in payload.get("series") or []:
        rows = grouped.get(series["series_key"]) or []
        years = {row["year"] for row in rows}
        if len(years) < 2:
            continue
        features = [row_features(row) for row in rows]
        candidates = weekday_rule_candidates(features, target_year) + date_rule_candidates(features, target_year)
        prediction = choose_prediction(candidates)
        if not prediction:
            continue
        actuals = sorted(actual_by_series.get(series["series_key"]) or [], key=lambda row: row["date_start"])
        predictions.append({
            "series_key": series["series_key"],
            "event_name": series["canonical_name"],
            "venue": series["usual_venue"],
            "target_year": target_year,
            "prediction": prediction,
            "candidate_rules": sorted(candidates, key=lambda row: (-row["score"], row["rule_type"]))[:5],
            "actual_observations": [
                {
                    "date_start": row["date_start"],
                    "date_end": row.get("date_end") or row["date_start"],
                    "weekday_start": row.get("weekday_start") or "",
                    "weekday_end": row.get("weekday_end") or "",
                    "confidence": row.get("confidence") or "",
                    "source_video_count": row.get("source_video_count") or 0,
                }
                for row in actuals
            ],
        })

    predictions.sort(key=lambda row: (-row["prediction"]["score"], row["event_name"], row["venue"]))
    counts = Counter(row["prediction"]["rule_type"] for row in predictions)
    confs = Counter(row["prediction"]["confidence"] for row in predictions)
    return {
        "generated_by": "build_event_date_predictions.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_year": target_year,
        "source": str(OBSERVATIONS),
        "summary": {
            "prediction_count": len(predictions),
            "rule_counts": dict(sorted(counts.items())),
            "confidence_counts": dict(sorted(confs.items())),
            "with_actual_observation": sum(1 for row in predictions if row["actual_observations"]),
        },
        "predictions": predictions,
    }


def md_cell(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(data):
    lines = [
        "# 年次開催回 日付予測",
        "",
        f"- 生成: {data['generated_at']}",
        f"- target_year: {data['target_year']}",
        f"- prediction_count: {data['summary']['prediction_count']}",
        f"- with_actual_observation: {data['summary']['with_actual_observation']}",
        "",
        "| confidence | rule | predicted | weekday | event | venue | basis | actual |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in data["predictions"]:
        pred = row["prediction"]
        predicted = pred["predicted_date_start"]
        if pred["predicted_date_end"] != pred["predicted_date_start"]:
            predicted = f"{predicted}〜{pred['predicted_date_end']}"
        weekday = pred["predicted_weekday_start"]
        if pred["predicted_weekday_end"] != pred["predicted_weekday_start"]:
            weekday = f"{weekday}〜{pred['predicted_weekday_end']}"
        actual = ""
        if row["actual_observations"]:
            actual_row = row["actual_observations"][0]
            actual = actual_row["date_start"]
            if actual_row["date_end"] != actual_row["date_start"]:
                actual = f"{actual}〜{actual_row['date_end']}"
        lines.append(
            f"| {pred['confidence']} | {pred['rule_type']} | {predicted} | {weekday} | "
            f"{md_cell(row['event_name'])} | {md_cell(row['venue'])} | {md_cell(pred['basis'])} | {actual} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--observations", default=str(OBSERVATIONS))
    parser.add_argument("--target-year", type=int, required=True)
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--md-out", default=str(MD_OUT))
    args = parser.parse_args()

    payload = load_json(args.observations, {})
    data = build_predictions(payload, target_year=args.target_year)
    atomic_write_json(args.out, data)
    atomic_write_text(args.md_out, render_markdown(data))
    print(
        "event date predictions: "
        f"target_year={args.target_year} "
        f"predictions={data['summary']['prediction_count']} "
        f"rules={data['summary']['rule_counts']}"
    )


if __name__ == "__main__":
    main()
