"""Apply reviewed YouTube backfill observations to event_occurrence_observations.json."""

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from youtube_backfill.build_event_occurrence_observations import build_series, render_markdown, write_json


DATA = Path("data")
OBSERVATIONS = DATA / "event_occurrence_observations.json"
PLAN = DATA / "event_occurrence_backfill_plan.json"
OUT_JSON = OBSERVATIONS
OUT_MD = DATA / "event_occurrence_observations.md"


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def merge_observations(existing, additions):
    by_id = {row["observation_id"]: row for row in existing}
    added = 0
    updated = 0
    for row in additions:
        if row["observation_id"] in by_id:
            by_id[row["observation_id"]] = row
            updated += 1
        else:
            by_id[row["observation_id"]] = row
            added += 1
    rows = sorted(by_id.values(), key=lambda row: (row["year"], row["event_name"], row["date_start"], row["observation_id"]))
    return rows, {"added": added, "updated": updated}


def rebuild_payload(payload, observations, apply_summary):
    series = build_series(observations)
    years = Counter(str(row["year"]) for row in observations)
    summary = {
        "observation_count": len(observations),
        "series_count": len(series),
        "source_video_count": sum(row["source_video_count"] for row in observations),
        "observed_years": sorted(years.keys()),
        "observations_by_year": dict(sorted(years.items())),
        "series_with_3year_window": sum(1 for row in series if row["has_3year_window"]),
        "observations_with_songs": sum(1 for row in observations if row.get("songs")),
        "active_review_skipped": (payload.get("summary") or {}).get("active_review_skipped") or {},
        "setlist_attach": (payload.get("summary") or {}).get("setlist_attach") or {},
        "backfill_apply": apply_summary,
    }
    return {
        **payload,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "series": series,
        "observations": observations,
    }


def apply_plan(payload, plan):
    observations, apply_summary = merge_observations(payload.get("observations") or [], plan.get("observations") or [])
    apply_summary.update({
        "source": str(PLAN),
        "source_observation_count": len(plan.get("observations") or []),
    })
    return rebuild_payload(payload, observations, apply_summary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--observations", default=str(OBSERVATIONS))
    parser.add_argument("--plan", default=str(PLAN))
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    args = parser.parse_args()

    payload = load_json(args.observations, {})
    plan = load_json(args.plan, {})
    data = apply_plan(payload, plan)
    write_json(args.out_json, data)
    Path(args.out_md).write_text(render_markdown(data), encoding="utf-8")
    apply_summary = data["summary"]["backfill_apply"]
    print(
        "event occurrence backfill applied: "
        f"added={apply_summary['added']} updated={apply_summary['updated']} "
        f"observations={data['summary']['observation_count']} "
        f"series_3year={data['summary']['series_with_3year_window']}"
    )


if __name__ == "__main__":
    main()
