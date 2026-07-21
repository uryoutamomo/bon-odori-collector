"""Prioritize public events that still need individual diff review."""

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


DATA = Path("data")
CLASSIFICATION = DATA / "public_events_diff_classification.json"
OUT_JSON = DATA / "public_individual_review_priority.json"
OUT_MD = DATA / "public_individual_review_priority.md"


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


def compact(value):
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return ""
    text = str(value)
    return text if len(text) <= 220 else text[:217] + "..."


def priority_for(row, records):
    families = set(row.get("families") or [])
    actions = row.get("actions") or {}
    fields = set(row.get("fields") or [])
    if "detail" in families:
        return {
            "priority": "P0",
            "bucket": "visible_detail",
            "reason": "detail changes can affect visible event explanation.",
        }
    if "date_prediction" in families or actions.get("site_update_candidate_after_review"):
        return {
            "priority": "P1",
            "bucket": "date_prediction_or_site_update_candidate",
            "reason": "collector has prediction/date metadata that may be worth copying to site after review.",
        }
    if "historical_slide" in families and "historical_reference" in families:
        return {
            "priority": "P2",
            "bucket": "historical_reference_vs_slide",
            "reason": "historical reference and slide fields differ; lower risk after required postprocessors are guarded.",
        }
    if fields:
        return {
            "priority": "P3",
            "bucket": "other_individual_review",
            "reason": "individual review required, but no date/detail/fixed-rule signal was detected.",
        }
    return {
        "priority": "P9",
        "bucket": "unknown",
        "reason": "no fields found",
    }


def build(args):
    classification = load_json(args.classification, {})
    records_by_event = defaultdict(list)
    for record in classification.get("records") or []:
        records_by_event[record.get("event_key")].append(record)

    rows = []
    for row in classification.get("event_rows") or []:
        if row.get("recommended_action") != "individual_review":
            continue
        records = records_by_event.get(row.get("event_key"), [])
        priority = priority_for(row, records)
        review_fields = [
            {
                "field": record.get("field"),
                "family": record.get("family"),
                "side": record.get("side"),
                "action": record.get("recommended_action"),
                "collector_value": record.get("collector_value"),
                "site_value": record.get("site_value"),
            }
            for record in records
            if record.get("recommended_action") in {"individual_review", "site_update_candidate_after_review"}
        ]
        rows.append(
            {
                "event_key": row.get("event_key"),
                "event_name": row.get("event_name"),
                "venue": row.get("venue"),
                "priority": priority["priority"],
                "bucket": priority["bucket"],
                "reason": priority["reason"],
                "families": row.get("families") or [],
                "field_count": row.get("field_count"),
                "actions": row.get("actions") or {},
                "review_field_count": len(review_fields),
                "review_fields": review_fields,
            }
        )
    rows.sort(key=lambda row: (row["priority"], row["event_name"], row["venue"]))
    data = {
        "generated_by": "prioritize_public_individual_review.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "read_only_public_individual_review_priority_no_writes",
        "sources": {
            "classification": str(args.classification),
        },
        "summary": {
            "individual_review_event_count": len(rows),
            "by_priority": dict(Counter(row["priority"] for row in rows)),
            "by_bucket": dict(Counter(row["bucket"] for row in rows)),
            "p0_p1_event_count": sum(1 for row in rows if row["priority"] in {"P0", "P1"}),
        },
        "rows": rows,
    }
    write_json(args.out_json, data)
    Path(args.out_md).write_text(render_markdown(data), encoding="utf-8")
    return data


def render_markdown(data):
    summary = data["summary"]
    lines = [
        "# Public individual review priority",
        "",
        f"- generated_at: {data['generated_at']}",
        f"- scope: {data['scope']}",
        f"- individual_review_event_count: {summary['individual_review_event_count']}",
        f"- p0_p1_event_count: {summary['p0_p1_event_count']}",
        f"- by_priority: {summary['by_priority']}",
        f"- by_bucket: {summary['by_bucket']}",
        "",
        "## Review Order",
        "",
        "| priority | bucket | event | venue | families | review_fields | reason |",
        "| --- | --- | --- | --- | --- | ---: | --- |",
    ]
    for row in data["rows"]:
        lines.append(
            f"| {row['priority']} | {row['bucket']} | {row['event_name']} | {row['venue']} | "
            f"{', '.join(row['families'])} | {row['review_field_count']} | {row['reason']} |"
        )
    lines.extend(["", "## P0/P1 Field Details", ""])
    for row in data["rows"]:
        if row["priority"] not in {"P0", "P1"}:
            continue
        lines.extend(
            [
                f"### {row['priority']} {row['event_name']} / {row['venue']}",
                "",
                "| field | family | side | action | collector | site |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for field in row["review_fields"]:
            lines.append(
                f"| {field['field']} | {field['family']} | {field['side']} | {field['action']} | "
                f"{compact(field['collector_value'])} | {compact(field['site_value'])} |"
            )
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--classification", default=str(CLASSIFICATION))
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    args = parser.parse_args()
    data = build(args)
    print(
        "public individual review priority: "
        f"events={data['summary']['individual_review_event_count']} "
        f"by_priority={data['summary']['by_priority']}"
    )


if __name__ == "__main__":
    main()
