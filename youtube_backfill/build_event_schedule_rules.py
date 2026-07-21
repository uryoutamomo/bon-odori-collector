"""Classify event-series schedule rules from yearly occurrence observations."""

import argparse
import json
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from build_event_date_predictions import (
    OBSERVATIONS,
    date_rule_candidates,
    row_features,
    weekday_rule_candidates,
)


DATA = Path("data")
OUT = DATA / "event_schedule_rules.json"
MD_OUT = DATA / "event_schedule_rules.md"

PRIMARY_AXIS = {
    "fixed_date": "date",
    "fixed_date_range": "date",
    "weekday_last": "weekday",
    "weekday_nth": "weekday",
    "weekday_near_day": "weekday_near_date",
    "weekend_near_day": "weekend_near_date",
    "date_near": "near_date",
}

AXIS_LABELS = {
    "date": "同一日タイプ",
    "weekday": "同一曜日タイプ",
    "weekday_near_date": "曜日優先・日付近傍タイプ",
    "weekend_near_date": "週末寄せタイプ",
    "near_date": "日付近傍タイプ",
    "unknown": "不明",
}

RULE_PRIORITY = {
    "fixed_date_range": 0,
    "fixed_date": 1,
    "weekday_last": 2,
    "weekday_nth": 3,
    "weekday_near_day": 4,
    "weekend_near_day": 5,
    "date_near": 6,
}


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


def normalize_text(value):
    return re.sub(r"\s+", "", str(value or "")).casefold()


def md_cell(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def rule_confidence(candidate):
    years = candidate.get("evidence_years") or []
    if len(years) >= 3:
        return "high"
    if len(years) >= 2:
        return "medium"
    return "low"


def add_rule_metadata(candidate):
    rule = dict(candidate)
    rule_type = rule.get("rule_type") or "unknown"
    axis = PRIMARY_AXIS.get(rule_type, "unknown")
    rule["primary_axis"] = axis
    rule["axis_label"] = AXIS_LABELS.get(axis, "不明")
    rule["rule_confidence"] = rule_confidence(rule)
    rule["legacy_prediction_confidence"] = rule.get("confidence")
    rule["warnings"] = list(rule.get("warnings") or [])
    return rule


def fixed_date_is_strong(rule):
    return (
        rule.get("rule_type") in {"fixed_date", "fixed_date_range"}
        and len(rule.get("evidence_years") or []) >= 3
    )


def weekday_is_strong(rule):
    return (
        rule.get("rule_type") in {"weekday_last", "weekday_nth"}
        and len(rule.get("evidence_years") or []) >= 3
    )


def choose_schedule_rule(candidates):
    if not candidates:
        return None, "no_candidate"
    rules = [add_rule_metadata(row) for row in candidates]
    fixed = [row for row in rules if row.get("rule_type") in {"fixed_date", "fixed_date_range"}]
    weekday = [row for row in rules if row.get("rule_type") in {"weekday_last", "weekday_nth"}]
    if fixed and weekday:
        best_fixed = sorted(fixed, key=lambda row: (-row["score"], RULE_PRIORITY[row["rule_type"]]))[0]
        best_weekday = sorted(weekday, key=lambda row: (-row["score"], RULE_PRIORITY[row["rule_type"]]))[0]
        if fixed_date_is_strong(best_fixed) and not weekday_is_strong(best_weekday):
            best_fixed["tie_break_reason"] = "fixed_date_3plus_years"
            return best_fixed, "fixed_date_3plus_years"
        if weekday_is_strong(best_weekday) and not fixed_date_is_strong(best_fixed):
            best_weekday["tie_break_reason"] = "weekday_3plus_years"
            return best_weekday, "weekday_3plus_years"
        if abs(best_fixed["score"] - best_weekday["score"]) <= 0.04:
            chosen = sorted([best_fixed, best_weekday], key=lambda row: RULE_PRIORITY[row["rule_type"]])[0]
            chosen["tie_break_reason"] = "priority_on_close_score"
            return chosen, "priority_on_close_score"

    chosen = sorted(
        rules,
        key=lambda row: (-row["score"], RULE_PRIORITY.get(row["rule_type"], 99), row["predicted_date_start"]),
    )[0]
    chosen["tie_break_reason"] = "score"
    return chosen, "score"


def series_lookup(payload):
    by_key = {}
    for row in payload.get("series") or []:
        key = row.get("series_key")
        if key:
            by_key[key] = row
    return by_key


def observation_warnings(series_key, observations):
    warnings = []
    names = {normalize_text(row.get("event_name")) for row in observations if row.get("event_name")}
    venues = {normalize_text(row.get("venue")) for row in observations if row.get("venue")}
    if len(names) > 1:
        warnings.append("series_merge_suspected")
    if len(venues) > 1:
        warnings.append("venue_ambiguous")
    if not series_key:
        warnings.append("missing_series_key")
    return warnings


def build_rules(payload, target_year=2026):
    grouped = defaultdict(list)
    actual_by_series = defaultdict(list)
    for row in payload.get("observations") or []:
        year = int(row.get("year") or 0)
        if year < target_year:
            grouped[row.get("series_key")].append(row)
        elif year == target_year:
            actual_by_series[row.get("series_key")].append(row)

    series_by_key = series_lookup(payload)
    rules = []
    for series_key, rows in sorted(grouped.items(), key=lambda item: str(item[0] or "")):
        if not series_key:
            continue
        years = sorted({int(row["year"]) for row in rows})
        if len(years) < 2:
            continue
        features = [row_features(row) for row in rows]
        candidates = weekday_rule_candidates(features, target_year) + date_rule_candidates(features, target_year)
        if not candidates:
            continue
        rule, tie_break_reason = choose_schedule_rule(candidates)
        if not rule:
            continue
        series = series_by_key.get(series_key) or {}
        warnings = observation_warnings(series_key, rows)
        for warning in warnings:
            if warning not in rule["warnings"]:
                rule["warnings"].append(warning)
        candidate_rules = [
            add_rule_metadata(row)
            for row in sorted(candidates, key=lambda item: (-item["score"], RULE_PRIORITY.get(item["rule_type"], 99)))[:6]
        ]
        rules.append({
            "series_key": series_key,
            "event_name": series.get("canonical_name") or rows[0].get("event_name"),
            "venue": series.get("usual_venue") or rows[0].get("venue"),
            "target_year": target_year,
            "rule": rule,
            "tie_break_reason": tie_break_reason,
            "candidate_rules": candidate_rules,
            "observed_years": years,
            "actual_observations": [
                {
                    "date_start": row["date_start"],
                    "date_end": row.get("date_end") or row["date_start"],
                    "confidence": row.get("confidence") or "",
                    "source_video_count": row.get("source_video_count") or 0,
                }
                for row in sorted(actual_by_series.get(series_key) or [], key=lambda item: item["date_start"])
            ],
            "observations": [
                {
                    "year": row["year"],
                    "date_start": row["date_start"],
                    "date_end": row.get("date_end") or row["date_start"],
                    "weekday_start": row.get("weekday_start") or "",
                    "confidence": row.get("confidence") or "",
                    "source_type": row.get("source_type") or "",
                    "source_video_count": row.get("source_video_count") or 0,
                }
                for row in sorted(rows, key=lambda item: (item["year"], item["date_start"]))
            ],
        })

    rules.sort(key=lambda row: (-row["rule"]["score"], row["event_name"] or "", row["venue"] or ""))
    rule_counts = Counter(row["rule"]["rule_type"] for row in rules)
    axis_counts = Counter(row["rule"]["primary_axis"] for row in rules)
    confidence_counts = Counter(row["rule"]["rule_confidence"] for row in rules)
    warning_counts = Counter(warning for row in rules for warning in row["rule"].get("warnings") or [])
    return {
        "generated_by": "build_event_schedule_rules.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_year": target_year,
        "source": str(OBSERVATIONS),
        "summary": {
            "rule_count": len(rules),
            "rule_counts": dict(sorted(rule_counts.items())),
            "axis_counts": dict(sorted(axis_counts.items())),
            "confidence_counts": dict(sorted(confidence_counts.items())),
            "warning_counts": dict(sorted(warning_counts.items())),
            "with_actual_observation": sum(1 for row in rules if row["actual_observations"]),
        },
        "rules": rules,
    }


def render_markdown(data):
    lines = [
        "# 開催パターン分類",
        "",
        f"- 生成: {data['generated_at']}",
        f"- target_year: {data['target_year']}",
        f"- rule_count: {data['summary']['rule_count']}",
        f"- confidence_counts: {data['summary']['confidence_counts']}",
        f"- axis_counts: {data['summary']['axis_counts']}",
        "",
        "| confidence | axis | rule | predicted | event | venue | evidence_years | observations | warnings |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in data["rules"]:
        rule = row["rule"]
        predicted = rule["predicted_date_start"]
        if rule["predicted_date_end"] != rule["predicted_date_start"]:
            predicted = f"{predicted}〜{rule['predicted_date_end']}"
        observations = " / ".join(
            f"{obs['year']}:{obs['date_start']}"
            + (f"〜{obs['date_end']}" if obs["date_end"] != obs["date_start"] else "")
            for obs in row["observations"]
        )
        lines.append(
            f"| {rule['rule_confidence']} | {md_cell(rule['axis_label'])} | {rule['rule_type']} | "
            f"{predicted} | {md_cell(row['event_name'])} | {md_cell(row['venue'])} | "
            f"{','.join(str(year) for year in rule['evidence_years'])} | {md_cell(observations)} | "
            f"{md_cell(','.join(rule.get('warnings') or []))} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--observations", default=str(OBSERVATIONS))
    parser.add_argument("--target-year", type=int, default=2026)
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--md-out", default=str(MD_OUT))
    args = parser.parse_args()

    payload = load_json(args.observations, {})
    data = build_rules(payload, target_year=args.target_year)
    atomic_write_json(args.out, data)
    atomic_write_text(args.md_out, render_markdown(data))
    print(
        "event schedule rules: "
        f"target_year={args.target_year} "
        f"rules={data['summary']['rule_count']} "
        f"axes={data['summary']['axis_counts']}"
    )


if __name__ == "__main__":
    main()
