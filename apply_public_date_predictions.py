"""Attach event date predictions to public event JSON without overwriting dates."""

import argparse
import json
from pathlib import Path

from export_public_events import write_public_js


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
    return {
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


def should_attach(event, prediction):
    target_year = prediction["target_year"]
    date_value = str(event.get("date") or "")
    if date_value.startswith(f"{target_year}-"):
        return False
    return True


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
        if not should_attach(event, public):
            skipped.append({
                "event_name": event.get("name"),
                "venue": event.get("venue"),
                "reason": "target_year_date_already_present",
                "date": event.get("date"),
                "date_prediction": public,
            })
            event.pop("date_prediction", None)
            continue
        event["date_prediction"] = public
        applied.append({
            "event_name": event.get("name"),
            "venue": event.get("venue"),
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-events", default=str(PUBLIC_EVENTS))
    parser.add_argument("--predictions", default=str(PREDICTIONS))
    parser.add_argument("--out-json", default=str(PUBLIC_EVENTS))
    parser.add_argument("--out-js", default=str(PUBLIC_EVENTS_JS))
    parser.add_argument("--report", default=str(OUT_REPORT))
    args = parser.parse_args()

    events = load_json(args.public_events, [])
    predictions = load_json(args.predictions, {})
    result = apply_predictions(events, predictions)
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
