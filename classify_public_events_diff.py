"""Classify collector vs site public event diffs before any wholesale sync.

This is a read-only report generator. It compares the collector public
events_public.json with the site source data and classifies high-risk field
families into safe action buckets.
"""

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


DATA = Path("data")
COLLECTOR_EVENTS = DATA / "public" / "events_public.json"
SITE_EVENTS = Path("/Users/ryotauchida/bon-odori-site/data/events_public.json")
OUT_JSON = DATA / "public_events_diff_classification.json"
OUT_MD = DATA / "public_events_diff_classification.md"

HISTORICAL_FIELDS = {
    "historical_reference",
    "historical_reference_label",
    "historical_reference_confidence",
    "historical_reference_score",
    "historical_display_tier",
    "historical_last_seen_dates",
    "historical_last_seen_year",
}
HISTORICAL_SLIDE_FIELDS = {
    "historical_slide",
    "historical_slide_basis",
    "historical_slide_date",
    "historical_slide_date_end",
    "display_tier",
    "prediction_basis",
    "predicted_date",
    "predicted_date_end",
    "prediction_confidence",
}
SEASON_FIELDS = {
    "season_hint",
    "season_hint_label",
    "season_confidence",
    "season_months",
    "season_jun",
}
DATE_PREDICTION_FIELDS = {
    "date_prediction",
    "prediction_evidence_years",
    "recurrence_score",
    "recurrence_reasons",
}
DETAIL_FIELDS = {
    "detail",
}
POSTPROCESSOR_RULE_FIELDS = {
    "fixed_date_rule",
}

HIGH_RISK_FIELDS = (
    HISTORICAL_FIELDS
    | HISTORICAL_SLIDE_FIELDS
    | SEASON_FIELDS
    | DATE_PREDICTION_FIELDS
    | DETAIL_FIELDS
    | POSTPROCESSOR_RULE_FIELDS
)


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def event_key(row):
    return f"{row.get('name') or ''}||{row.get('venue') or ''}"


def index_events(rows):
    return {event_key(row): row for row in rows}


def field_family(field):
    if field in HISTORICAL_FIELDS:
        return "historical_reference"
    if field in HISTORICAL_SLIDE_FIELDS:
        return "historical_slide"
    if field in SEASON_FIELDS:
        return "season_hint"
    if field in DATE_PREDICTION_FIELDS:
        return "date_prediction"
    if field in DETAIL_FIELDS:
        return "detail"
    if field in POSTPROCESSOR_RULE_FIELDS:
        return "fixed_date_rule"
    return "other"


def value_side(collector_value, site_value):
    collector_present = collector_value is not None
    site_present = site_value is not None
    if collector_present and not site_present:
        return "collector_only"
    if site_present and not collector_present:
        return "site_only"
    if collector_present and site_present:
        return "both_different"
    return "unknown"


def recurrence_score_bucket(value):
    try:
        score = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if score >= 0.75:
        level = "map_high"
    elif score >= 0.55:
        level = "map_medium"
    else:
        level = "map_low"
    if score >= 0.90:
        label = "certainty_very_high"
    elif score >= 0.80:
        label = "certainty_high"
    elif score >= 0.65:
        label = "certainty_good"
    elif score >= 0.45:
        label = "certainty_mid"
    elif score >= 0.20:
        label = "certainty_low"
    else:
        label = "certainty_reference"
    return (level, label)


def classify_diff(field, collector_value, site_value):
    family = field_family(field)
    side = value_side(collector_value, site_value)

    if field == "recurrence_reasons":
        return "low_priority_or_unclassified"

    if field == "recurrence_score" and side == "both_different":
        if recurrence_score_bucket(collector_value) == recurrence_score_bucket(site_value):
            return "low_priority_or_unclassified"
        return "individual_review"

    if family in {"historical_reference", "historical_slide", "season_hint"}:
        if side == "site_only":
            return "restore_collector_from_site_or_reenable_export_postprocess"
        if side == "collector_only":
            return "site_update_candidate_after_review"
        return "individual_review"

    if family == "date_prediction":
        if side == "collector_only":
            return "site_update_candidate_after_review"
        if side == "site_only":
            return "restore_collector_from_site_or_reenable_export_postprocess"
        return "individual_review"

    if family == "detail":
        return "individual_review"

    if family == "fixed_date_rule":
        if side == "collector_only":
            return "collector_only_postprocess_rule"
        if side == "site_only":
            return "restore_collector_from_site_or_reenable_export_postprocess"
        return "individual_review"

    return "low_priority_or_unclassified"


def normalized_generated_value(field, value):
    if field not in {"historical_reference", "historical_slide"}:
        return value
    if isinstance(value, dict):
        normalized = {}
        for key, item in value.items():
            if key == "method" and item == "same_weekday":
                continue
            normalized[key] = normalized_generated_value(field, item)
        return normalized
    if isinstance(value, list):
        return [normalized_generated_value(field, item) for item in value]
    return value


def values_differ(field, collector_value, site_value):
    return normalized_generated_value(field, collector_value) != normalized_generated_value(field, site_value)


def rule_prediction_replaces_matching_historical_slide(records):
    actionable = [
        record
        for record in records
        if record["recommended_action"]
        in {
            "individual_review",
            "site_update_candidate_after_review",
            "restore_collector_from_site_or_reenable_export_postprocess",
        }
    ]
    allowed_fields = {
        "date_prediction",
        "display_tier",
        "historical_display_tier",
        "historical_reference",
        "historical_slide",
        "historical_slide_basis",
        "historical_slide_date",
        "historical_slide_date_end",
        "prediction_basis",
        "prediction_evidence_years",
    }
    if not actionable or any(record["field"] not in allowed_fields for record in actionable):
        return False

    date_prediction = next((record for record in records if record["field"] == "date_prediction"), None)
    if not date_prediction or date_prediction.get("side") != "collector_only":
        return False
    predicted = date_prediction.get("collector_value") or {}
    predicted_start = predicted.get("date")
    predicted_end = predicted.get("date_end") or predicted_start
    if not predicted_start:
        return False

    slide_record = next((record for record in records if record["field"] == "historical_slide"), None)
    slide = (slide_record or {}).get("site_value") or {}
    slide_start = slide.get("date")
    slide_end = slide.get("date_end") or slide_start
    for record in records:
        if record["field"] == "historical_slide_date":
            slide_start = record.get("site_value") or slide_start
        if record["field"] == "historical_slide_date_end":
            slide_end = record.get("site_value") or slide_end
    return predicted_start == slide_start and predicted_end == slide_end


def fixed_date_rule_basis_refresh(records):
    actionable = [
        record
        for record in records
        if record["recommended_action"]
        in {
            "individual_review",
            "site_update_candidate_after_review",
            "restore_collector_from_site_or_reenable_export_postprocess",
        }
    ]
    allowed_fields = {
        "historical_reference",
        "historical_reference_score",
        "historical_slide",
        "historical_slide_basis",
        "prediction_basis",
    }
    if not actionable or any(record["field"] not in allowed_fields for record in actionable):
        return False

    slide_record = next((record for record in records if record["field"] == "historical_slide"), None)
    if not slide_record:
        return False
    collector_slide = slide_record.get("collector_value") or {}
    site_slide = slide_record.get("site_value") or {}
    if collector_slide.get("date") != site_slide.get("date"):
        return False
    if (collector_slide.get("date_end") or collector_slide.get("date")) != (
        site_slide.get("date_end") or site_slide.get("date")
    ):
        return False
    if collector_slide.get("rule_type") != site_slide.get("rule_type"):
        return False
    if collector_slide.get("rule_type") not in {"fixed_date", "fixed_date_range"}:
        return False

    score_record = next((record for record in records if record["field"] == "historical_reference_score"), None)
    if score_record and recurrence_score_bucket(score_record.get("collector_value")) != recurrence_score_bucket(
        score_record.get("site_value")
    ):
        return False
    return True


def recommended_event_action(actions, records):
    if rule_prediction_replaces_matching_historical_slide(records):
        return "rule_prediction_replaces_matching_historical_slide"
    if fixed_date_rule_basis_refresh(records):
        return "fixed_date_rule_basis_refresh"
    if actions.get("individual_review"):
        return "individual_review"
    if actions.get("site_update_candidate_after_review") and actions.get(
        "restore_collector_from_site_or_reenable_export_postprocess"
    ):
        return "individual_review"
    if actions.get("site_update_candidate_after_review"):
        return "site_update_candidate_after_review"
    if actions.get("restore_collector_from_site_or_reenable_export_postprocess"):
        return "restore_collector_from_site_or_reenable_export_postprocess"
    if actions.get("collector_only_postprocess_rule"):
        return "collector_only_postprocess_rule"
    return "low_priority_or_unclassified"


def changed_fields(collector, site):
    fields = sorted(set(collector) | set(site))
    return [field for field in fields if values_differ(field, collector.get(field), site.get(field))]


def compact_value(value):
    if isinstance(value, dict):
        keep = {}
        for key in [
            "display_tier",
            "label",
            "confidence",
            "score",
            "date",
            "date_end",
            "basis",
            "rule_type",
            "last_seen_year",
            "last_seen_dates",
        ]:
            if key in value:
                keep[key] = value[key]
        return keep or {key: value[key] for key in list(value)[:6]}
    if isinstance(value, list):
        return value[:6]
    if isinstance(value, str) and len(value) > 180:
        return value[:177] + "..."
    return value


def build_classification(collector_path, site_path):
    collector_rows = load_json(collector_path, [])
    site_rows = load_json(site_path, [])
    collector = index_events(collector_rows)
    site = index_events(site_rows)
    common = sorted(set(collector) & set(site))

    records = []
    for key in common:
        left = collector[key]
        right = site[key]
        for field in changed_fields(left, right):
            if field not in HIGH_RISK_FIELDS:
                continue
            family = field_family(field)
            action = classify_diff(field, left.get(field), right.get(field))
            records.append(
                {
                    "event_key": key,
                    "event_name": left.get("name") or right.get("name") or "",
                    "venue": left.get("venue") or right.get("venue") or "",
                    "field": field,
                    "family": family,
                    "side": value_side(left.get(field), right.get(field)),
                    "recommended_action": action,
                    "collector_value": compact_value(left.get(field)),
                    "site_value": compact_value(right.get(field)),
                }
            )

    event_actions = defaultdict(lambda: {"fields": [], "families": set(), "actions": Counter(), "records": []})
    for record in records:
        item = event_actions[record["event_key"]]
        item["fields"].append(record["field"])
        item["families"].add(record["family"])
        item["actions"][record["recommended_action"]] += 1
        item["records"].append(record)

    event_rows = []
    for key, item in event_actions.items():
        actions = item["actions"]
        event_action = recommended_event_action(actions, item["records"])
        sample = next(record for record in records if record["event_key"] == key)
        event_rows.append(
            {
                "event_key": key,
                "event_name": sample["event_name"],
                "venue": sample["venue"],
                "recommended_action": event_action,
                "families": sorted(item["families"]),
                "field_count": len(item["fields"]),
                "fields": sorted(item["fields"]),
                "actions": dict(actions),
            }
        )

    event_rows.sort(key=lambda row: (row["recommended_action"], row["event_name"], row["venue"]))
    summary = {
        "collector_event_count": len(collector_rows),
        "site_event_count": len(site_rows),
        "collector_only_count": len(set(collector) - set(site)),
        "site_only_count": len(set(site) - set(collector)),
        "high_risk_diff_record_count": len(records),
        "high_risk_event_count": len(event_rows),
        "records_by_family": dict(Counter(record["family"] for record in records)),
        "records_by_action": dict(Counter(record["recommended_action"] for record in records)),
        "events_by_action": dict(Counter(row["recommended_action"] for row in event_rows)),
    }
    return {
        "summary": summary,
        "event_rows": event_rows,
        "records": records,
    }


def build(args):
    classified = build_classification(args.collector_events, args.site_events)
    data = {
        "generated_by": "classify_public_events_diff.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "read_only_diff_classification_no_writes",
        "sources": {
            "collector_events": str(args.collector_events),
            "site_events": str(args.site_events),
        },
        "policy": {
            "restore_collector_from_site_or_reenable_export_postprocess": "site has post-processed fields that collector would delete on wholesale sync",
            "site_update_candidate_after_review": "collector has new fields absent from site; review before copying",
            "individual_review": "mixed direction or human-authored/detail/date fields; review event-by-event",
            "collector_only_postprocess_rule": "collector has an internal postprocessor rule that is excluded from the public snapshot",
            "rule_prediction_replaces_matching_historical_slide": "collector rule prediction keeps the same displayed date as the legacy historical slide",
            "fixed_date_rule_basis_refresh": "collector fixed-date postprocessor keeps the same displayed date while refreshing the public basis text",
        },
        **classified,
    }
    write_json(args.out_json, data)
    Path(args.out_md).write_text(render_markdown(data), encoding="utf-8")
    return data


def render_markdown(data):
    summary = data["summary"]
    lines = [
        "# Public events diff classification",
        "",
        f"- generated_at: {data['generated_at']}",
        f"- scope: {data['scope']}",
        f"- collector_event_count: {summary['collector_event_count']}",
        f"- site_event_count: {summary['site_event_count']}",
        f"- collector_only_count: {summary['collector_only_count']}",
        f"- site_only_count: {summary['site_only_count']}",
        f"- high_risk_event_count: {summary['high_risk_event_count']}",
        f"- high_risk_diff_record_count: {summary['high_risk_diff_record_count']}",
        f"- records_by_family: {summary['records_by_family']}",
        f"- records_by_action: {summary['records_by_action']}",
        f"- events_by_action: {summary['events_by_action']}",
        "",
        "## Action Buckets",
        "",
    ]
    for action in [
        "restore_collector_from_site_or_reenable_export_postprocess",
        "site_update_candidate_after_review",
        "individual_review",
        "collector_only_postprocess_rule",
        "rule_prediction_replaces_matching_historical_slide",
        "fixed_date_rule_basis_refresh",
        "low_priority_or_unclassified",
    ]:
        rows = [row for row in data["event_rows"] if row["recommended_action"] == action]
        if not rows:
            continue
        lines.extend([f"### {action}", ""])
        lines.append("| event | venue | families | fields |")
        lines.append("| --- | --- | --- | ---: |")
        for row in rows[:120]:
            lines.append(
                f"| {row['event_name']} | {row['venue']} | {', '.join(row['families'])} | {row['field_count']} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Field-Level Site Update Candidates",
            "",
            "These collector-only fields may be copied to site after individual review, but their events may still have other mixed diffs.",
            "",
            "| event | venue | field | collector | site |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for record in data["records"]:
        if record["recommended_action"] != "site_update_candidate_after_review":
            continue
        lines.append(
            f"| {record['event_name']} | {record['venue']} | {record['field']} | "
            f"{json.dumps(record['collector_value'], ensure_ascii=False)} | "
            f"{json.dumps(record['site_value'], ensure_ascii=False)} |"
        )
    lines.append("")

    lines.extend(
        [
            "## Individual Review Details",
            "",
            "| event | venue | field | side | collector | site |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for record in data["records"]:
        if record["recommended_action"] != "individual_review":
            continue
        lines.append(
            f"| {record['event_name']} | {record['venue']} | {record['field']} | {record['side']} | "
            f"{json.dumps(record['collector_value'], ensure_ascii=False)} | "
            f"{json.dumps(record['site_value'], ensure_ascii=False)} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--collector-events", default=str(COLLECTOR_EVENTS))
    parser.add_argument("--site-events", default=str(SITE_EVENTS))
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    args = parser.parse_args()
    data = build(args)
    print(
        "public events diff classification: "
        f"events={data['summary']['high_risk_event_count']} "
        f"actions={data['summary']['events_by_action']}"
    )


if __name__ == "__main__":
    main()
