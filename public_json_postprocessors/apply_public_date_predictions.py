"""Attach event date predictions to public event JSON without overwriting dates."""

import argparse
import json
from pathlib import Path

from event_model.year_context import normalize_target_year


DATA = Path("data")
PUBLIC_EVENTS = DATA / "public" / "events_public.json"
PUBLIC_EVENTS_JS = DATA / "public" / "events_public.js"
PREDICTIONS = DATA / "event_date_predictions.json"
OUT_REPORT = DATA / "public_date_prediction_apply_result.json"


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def event_key(name, venue):
    return (str(name or "").strip(), str(venue or "").strip())


def public_prediction(prediction_row):
    prediction = prediction_row["prediction"]
    public = {
        "display_tier": "rule_predicted",
        "target_year": prediction_row["target_year"],
        "date": prediction["predicted_date_start"],
        "date_end": prediction["predicted_date_end"],
        "weekday_start": prediction["predicted_weekday_start"],
        "weekday_end": prediction["predicted_weekday_end"],
        "confidence": prediction["confidence"],
        "score": prediction["score"],
        "rule_type": prediction["rule_type"],
        "basis": prediction["basis"],
        "evidence_years": prediction["evidence_years"],
        "evidence_count": prediction["evidence_count"],
        "has_actual_observation": bool(prediction_row.get("actual_observations")),
    }
    for field in (
        "joint_probability",
        "probability_percent",
        "certainty_label",
        "certainty_meaning",
    ):
        if prediction.get(field) is not None:
            public[field] = prediction[field]
    return public


def should_attach(event, prediction):
    state = event.get("current_event_state")
    if state not in {None, "", "predicted", "announced"}:
        return False
    target_year = prediction["target_year"]
    date_value = str(event.get("date") or "")
    if date_value.startswith(f"{target_year}-"):
        return False
    return True


PREDICTION_EVENT_FIELDS = (
    "date_prediction",
    "display_tier",
    "predicted_date",
    "predicted_date_end",
    "prediction_basis",
    "prediction_confidence",
    "prediction_evidence_years",
    "prediction_probability",
    "prediction_probability_percent",
    "prediction_certainty_label",
    "prediction_certainty_meaning",
)


def clear_public_prediction_fields(event):
    for field in PREDICTION_EVENT_FIELDS:
        event.pop(field, None)


def attach_public_prediction_fields(event, public):
    event["date_prediction"] = public
    event["current_event_state"] = event.get("current_event_state") or "predicted"
    event["date_certainty_tier"] = "rule_predicted"
    event["display_tier"] = public["display_tier"]
    event["predicted_date"] = public["date"]
    event["predicted_date_end"] = public["date_end"]
    event["prediction_basis"] = public["basis"]
    event["prediction_confidence"] = public["confidence"]
    event["prediction_evidence_years"] = public["evidence_years"]
    if public.get("joint_probability") is not None:
        event["prediction_probability"] = public["joint_probability"]
    if public.get("probability_percent") is not None:
        event["prediction_probability_percent"] = public["probability_percent"]
    if public.get("certainty_label"):
        event["prediction_certainty_label"] = public["certainty_label"]
    if public.get("certainty_meaning"):
        event["prediction_certainty_meaning"] = public["certainty_meaning"]


def apply_predictions(events, predictions):
    by_key = {
        event_key(row.get("name"), row.get("venue")): row
        for row in events
    }
    applied = []
    skipped = []
    unmatched = []
    for row in predictions.get("predictions") or []:
        key = event_key(row.get("event_name"), row.get("venue"))
        event = by_key.get(key)
        public = public_prediction(row)
        if not event:
            unmatched.append({
                "event_name": row.get("event_name"),
                "venue": row.get("venue"),
                "date_prediction": public,
            })
            continue
        before = {
            "date": event.get("date"),
            "date_end": event.get("date_end"),
            "display_tier": event.get("display_tier"),
            "predicted_date": event.get("predicted_date"),
            "predicted_date_end": event.get("predicted_date_end"),
        }
        if not should_attach(event, public):
            skipped.append({
                "event_name": event.get("name"),
                "venue": event.get("venue"),
                "reason": "target_year_date_already_present",
                "date": event.get("date"),
                "date_prediction": public,
            })
            clear_public_prediction_fields(event)
            continue
        if public.get("confidence") == "low":
            skipped.append({
                "event_name": event.get("name"),
                "venue": event.get("venue"),
                "reason": "low_confidence_public_prediction",
                "date": event.get("date"),
                "date_prediction": public,
            })
            clear_public_prediction_fields(event)
            continue
        attach_public_prediction_fields(event, public)
        applied.append({
            "event_name": event.get("name"),
            "venue": event.get("venue"),
            "before": before,
            "after": {
                "date": event.get("date"),
                "date_end": event.get("date_end"),
                "display_tier": event.get("display_tier"),
                "predicted_date": event.get("predicted_date"),
                "predicted_date_end": event.get("predicted_date_end"),
            },
            "date_prediction": public,
        })
    return {
        "events": events,
        "report": {
            "generated_by": "apply_public_date_predictions.py",
            "source": str(PREDICTIONS),
            "public_events": str(PUBLIC_EVENTS),
            "applied_count": len(applied),
            "skipped_count": len(skipped),
            "unmatched_count": len(unmatched),
            "applied": applied,
            "skipped": skipped,
            "unmatched": unmatched,
        },
    }


def predictions_for_target_year(payload, *, target_year):
    target_year = normalize_target_year(target_year)
    filtered = dict(payload or {})
    filtered["target_year"] = target_year
    filtered["predictions"] = [
        row
        for row in filtered.get("predictions") or []
        if row.get("target_year") == target_year
    ]
    return filtered


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-events", default=str(PUBLIC_EVENTS))
    parser.add_argument("--predictions", default=str(PREDICTIONS))
    parser.add_argument("--out-json", default=str(PUBLIC_EVENTS))
    parser.add_argument("--out-js", default=str(PUBLIC_EVENTS_JS))
    parser.add_argument("--report", default=str(OUT_REPORT))
    parser.add_argument("--target-year", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    events = load_json(args.public_events, [])
    predictions = predictions_for_target_year(
        load_json(args.predictions, {}), target_year=args.target_year
    )
    result = apply_predictions(events, predictions)
    from public_json_postprocessors.apply_public_display_tiers import apply_display_tiers

    result["events"] = apply_display_tiers(
        result["events"], target_year=args.target_year
    )
    result["report"]["dry_run"] = bool(args.dry_run)
    if not args.dry_run:
        from export_public_events import write_public_js

        write_json(args.out_json, result["events"])
        write_public_js(args.out_js, result["events"])
    write_json(args.report, result["report"])
    print(
        "public date predictions: "
        f"applied={result['report']['applied_count']} "
        f"skipped={result['report']['skipped_count']} "
        f"unmatched={result['report']['unmatched_count']}"
    )


if __name__ == "__main__":
    main()
