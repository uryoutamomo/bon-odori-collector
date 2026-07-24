"""Attach historical-reference hints to recurring_last_year public events."""

import argparse
import calendar
import json
import re
from datetime import date, timedelta
from pathlib import Path

from event_model.year_context import EventYearContext, normalize_target_year


DATA = Path("data")
PUBLIC_EVENTS = DATA / "public" / "events_public.json"
PUBLIC_EVENTS_JS = DATA / "public" / "events_public.js"
OUT_REPORT = DATA / "public_historical_reference_dry_run.json"
FIXED_DATE_RULES = DATA / "public_fixed_date_rules.json"
WEEKDAY_LABELS = ["月", "火", "水", "木", "金", "土", "日"]


HISTORICAL_REFERENCE_FIELDS = (
    "historical_reference",
    "historical_display_tier",
    "historical_last_seen_year",
    "historical_last_seen_dates",
    "historical_reference_label",
    "historical_reference_confidence",
    "historical_reference_score",
    "historical_slide",
    "historical_slide_date",
    "historical_slide_date_end",
    "historical_slide_method",
    "historical_slide_basis",
)
HISTORICAL_SLIDE_OUTPUT_FIELDS = (
    "historical_slide",
    "historical_slide_date",
    "historical_slide_date_end",
    "historical_slide_method",
    "historical_slide_basis",
)
HISTORICAL_SLIDE_PREDICTION_FIELDS = (
    "predicted_date",
    "predicted_date_end",
    "prediction_basis",
    "prediction_confidence",
)


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def normalize_match_key(value):
    return re.sub(r"\s+", "", str(value or "")).casefold()


def fixed_rule_key(name, venue):
    return (normalize_match_key(name), normalize_match_key(venue))


def load_fixed_date_rules(path=FIXED_DATE_RULES):
    payload = load_json(path, {})
    rules = {}
    for row in payload.get("rules") or []:
        key = fixed_rule_key(row.get("name"), row.get("venue"))
        if key[0] and key[1]:
            rules[key] = row
    return rules


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def clear_historical_reference_fields(event):
    for field in HISTORICAL_REFERENCE_FIELDS:
        event.pop(field, None)
    if not event.get("date_prediction"):
        clear_historical_slide_prediction_fields(event)


def clear_historical_slide_fields(event):
    for field in HISTORICAL_SLIDE_OUTPUT_FIELDS:
        event.pop(field, None)


def clear_historical_slide_prediction_fields(event):
    for field in HISTORICAL_SLIDE_PREDICTION_FIELDS:
        event.pop(field, None)


def confidence_for_score(score):
    if score >= 0.75:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"


def parse_iso_date(value):
    if not value:
        return None
    try:
        year, month, day = [int(part) for part in str(value).split("-")]
        return date(year, month, day)
    except Exception:
        return None


def fmt(value):
    return value.isoformat() if value else None


def nth_weekday_in_month(value):
    return (value.day - 1) // 7 + 1


def same_nth_weekday(target_year, source):
    """Return target-year date with same month, nth weekday; clamp to last matching weekday."""
    weekday = source.weekday()
    nth = nth_weekday_in_month(source)
    month_days = calendar.monthrange(target_year, source.month)[1]
    matches = [
        date(target_year, source.month, day)
        for day in range(1, month_days + 1)
        if date(target_year, source.month, day).weekday() == weekday
    ]
    if not matches:
        return None
    return matches[min(nth, len(matches)) - 1]


def slide_date_range_to_target_year(start_value, end_value=None, *, target_year):
    target_year = normalize_target_year(target_year)
    start = parse_iso_date(start_value)
    if not start:
        return None
    slide_start = same_nth_weekday(target_year, start)
    if not slide_start:
        return None
    end = parse_iso_date(end_value)
    if end and end >= start:
        duration = (end - start).days
    else:
        duration = 0
    slide_end = slide_start + timedelta(days=duration)
    return {
        "date": fmt(slide_start),
        "date_end": fmt(slide_end),
        "method": "same_weekday",
        "basis": f"{start.year}年実績の同月第{nth_weekday_in_month(start)}{WEEKDAY_LABELS[start.weekday()]}曜を{target_year}年へスライド",
        "source_date": fmt(start),
        "source_date_end": fmt(end),
        "duration_days": duration + 1,
    }


def fixed_date_range_to_target_year(rule, *, target_year):
    target_year = normalize_target_year(target_year)
    try:
        start = date(target_year, int(rule["month"]), int(rule["day"]))
        end_month = int(rule.get("end_month") or rule["month"])
        end_day = int(rule.get("end_day") or rule["day"])
        end = date(target_year, end_month, end_day)
    except (KeyError, TypeError, ValueError):
        return None
    if end < start:
        return None
    if start == end:
        date_label = f"{start.month}/{start.day}"
    else:
        date_label = f"{start.month}/{start.day}〜{end.month}/{end.day}"
    return {
        "date": fmt(start),
        "date_end": fmt(end),
        "method": "fixed_date",
        "basis": rule.get("basis") or f"根拠付き固定日ルール: 毎年{date_label}",
        "source_date": rule.get("source_date"),
        "source_date_end": rule.get("source_date_end"),
        "duration_days": (end - start).days + 1,
        "rule_type": rule.get("rule_type") or "fixed_date_range",
        "source_url": rule.get("source_url") or "",
    }


def fixed_date_rule_for_event(event, rules):
    embedded = event.get("fixed_date_rule")
    if embedded:
        return embedded
    if not rules:
        return None
    return rules.get(fixed_rule_key(event.get("name"), event.get("venue")))


def historical_label(event):
    dates = event.get("last_seen_dates") or [value for value in [event.get("date"), event.get("date_end")] if value]
    if not dates:
        return "過去実績あり・今年未確認"
    if len(dates) >= 2 and dates[0] != dates[-1]:
        return f"{dates[0]}〜{dates[-1]}実績・今年未確認"
    return f"{dates[0]}実績・今年未確認"


def public_historical_reference(event, *, target_year, today, fixed_date_rules=None):
    context = EventYearContext(target_year=target_year, as_of=today)
    if event.get("public_category") != "recurring_last_year":
        return None
    score = float(event.get("recurrence_score") or 0)
    confidence = confidence_for_score(score)
    should_slide = confidence in {"high", "medium"} and not event.get("date_prediction")
    slide = None
    fixed_rule = fixed_date_rule_for_event(event, fixed_date_rules)
    if fixed_rule and not event.get("date_prediction"):
        slide = fixed_date_range_to_target_year(fixed_rule, target_year=context.target_year)
    elif should_slide:
        slide = slide_date_range_to_target_year(
            event.get("date"), event.get("date_end"), target_year=context.target_year
        )
    if slide:
        if slide and parse_iso_date(slide.get("date")) < context.as_of:
            slide["downgrade_reason"] = "slide_date_before_today"
            slide = None
    return {
        "display_tier": "historical_slide" if slide else "historical_reference",
        "last_seen_year": event.get("last_seen_year"),
        "last_seen_dates": event.get("last_seen_dates") or [value for value in [event.get("date"), event.get("date_end")] if value],
        "label": historical_label(event),
        "confidence": confidence,
        "score": score,
        "status": event.get("public_status"),
        "status_label": event.get("public_status_label"),
        "recurrence_label": event.get("recurrence_label"),
        "reasons": event.get("recurrence_reasons") or [],
        "cautions": event.get("recurrence_cautions") or [],
        "edition_number": event.get("edition_number"),
        "has_rule_prediction": bool(event.get("date_prediction")),
        "slide": slide,
    }


def attach_historical_reference_fields(event, reference):
    clear_historical_slide_fields(event)
    if not reference.get("has_rule_prediction"):
        clear_historical_slide_prediction_fields(event)
    event["historical_reference"] = reference
    event["historical_display_tier"] = reference["display_tier"]
    event["historical_last_seen_year"] = reference["last_seen_year"]
    event["historical_last_seen_dates"] = reference["last_seen_dates"]
    event["historical_reference_label"] = reference["label"]
    event["historical_reference_confidence"] = reference["confidence"]
    event["historical_reference_score"] = reference["score"]
    if reference.get("slide"):
        slide = reference["slide"]
        event["historical_slide"] = slide
        event["historical_slide_date"] = slide["date"]
        event["historical_slide_date_end"] = slide["date_end"]
        event["historical_slide_method"] = slide["method"]
        event["historical_slide_basis"] = slide["basis"]
        event["display_tier"] = "historical_slide"
        event["predicted_date"] = slide["date"]
        event["predicted_date_end"] = slide["date_end"]
        event["prediction_basis"] = slide["basis"]
        event["prediction_confidence"] = reference["confidence"]
    elif not reference.get("has_rule_prediction"):
        event["display_tier"] = "historical_reference"


def apply_historical_references(events, *, target_year, today, fixed_date_rules=None):
    context = EventYearContext(target_year=target_year, as_of=today)
    applied = []
    skipped = []
    target_count = 0
    for event in events:
        if event.get("public_category") != "recurring_last_year":
            clear_historical_reference_fields(event)
            continue
        target_count += 1
        reference = public_historical_reference(
            event,
            target_year=context.target_year,
            today=context.as_of,
            fixed_date_rules=fixed_date_rules,
        )
        if not reference:
            clear_historical_reference_fields(event)
            skipped.append({
                "name": event.get("name"),
                "venue": event.get("venue"),
                "reason": "not_historical_reference_candidate",
            })
            continue
        before = {
            "historical_reference": event.get("historical_reference"),
            "display_tier": event.get("display_tier"),
            "date_prediction": event.get("date_prediction"),
        }
        attach_historical_reference_fields(event, reference)
        applied.append({
            "name": event.get("name"),
            "venue": event.get("venue"),
            "before": before,
            "after": {
                "historical_reference_label": event.get("historical_reference_label"),
                "historical_reference_confidence": event.get("historical_reference_confidence"),
                "historical_reference_score": event.get("historical_reference_score"),
                "display_tier": event.get("display_tier"),
                "predicted_date": event.get("predicted_date"),
                "predicted_date_end": event.get("predicted_date_end"),
            },
            "historical_reference": reference,
        })
    return {
        "events": events,
        "report": {
            "generated_by": "apply_public_historical_references.py",
            "source": str(PUBLIC_EVENTS),
            "target_year": context.target_year,
            "today": fmt(context.as_of),
            "target_category": "recurring_last_year",
            "target_count": target_count,
            "applied_count": len(applied),
            "skipped_count": len(skipped),
            "with_rule_prediction_count": sum(1 for row in applied if row["historical_reference"].get("has_rule_prediction")),
            "slide_count": sum(1 for row in applied if row["historical_reference"].get("slide")),
            "fixed_date_rule_count": sum(
                1
                for row in applied
                if (row["historical_reference"].get("slide") or {}).get("method") == "fixed_date"
            ),
            "reference_only_count": sum(1 for row in applied if not row["historical_reference"].get("slide")),
            "rule_prediction_reference_count": sum(
                1
                for row in applied
                if row["historical_reference"].get("has_rule_prediction")
                and not row["historical_reference"].get("slide")
            ),
            "low_reference_only_count": sum(
                1
                for row in applied
                if row["historical_reference"].get("confidence") == "low"
                and not row["historical_reference"].get("slide")
            ),
            "past_slide_downgrade_count": sum(
                1
                for row in applied
                if row["historical_reference"].get("confidence") in {"high", "medium"}
                and not row["historical_reference"].get("has_rule_prediction")
                and not row["historical_reference"].get("slide")
            ),
            "confidence_counts": {
                "high": sum(1 for row in applied if row["historical_reference"].get("confidence") == "high"),
                "medium": sum(1 for row in applied if row["historical_reference"].get("confidence") == "medium"),
                "low": sum(1 for row in applied if row["historical_reference"].get("confidence") == "low"),
            },
            "applied": applied,
            "skipped": skipped,
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-events", default=str(PUBLIC_EVENTS))
    parser.add_argument("--out-json", default=str(PUBLIC_EVENTS))
    parser.add_argument("--out-js", default=str(PUBLIC_EVENTS_JS))
    parser.add_argument("--report", default=str(OUT_REPORT))
    parser.add_argument("--fixed-date-rules", default=str(FIXED_DATE_RULES))
    parser.add_argument("--target-year", type=int, required=True)
    parser.add_argument("--today", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    events = load_json(args.public_events, [])
    today = parse_iso_date(args.today)
    if not today:
        raise SystemExit(f"invalid --today: {args.today}")
    result = apply_historical_references(
        events,
        target_year=args.target_year,
        today=today,
        fixed_date_rules=load_fixed_date_rules(args.fixed_date_rules),
    )
    from public_json_postprocessors.apply_public_display_tiers import apply_display_tiers

    result["events"] = apply_display_tiers(result["events"], target_year=args.target_year)
    result["report"]["dry_run"] = bool(args.dry_run)
    if not args.dry_run:
        from export_public_events import write_public_js

        write_json(args.out_json, result["events"])
        write_public_js(args.out_js, result["events"])
    write_json(args.report, result["report"])
    print(
        "public historical references: "
        f"applied={result['report']['applied_count']} "
        f"skipped={result['report']['skipped_count']}"
    )


if __name__ == "__main__":
    main()
