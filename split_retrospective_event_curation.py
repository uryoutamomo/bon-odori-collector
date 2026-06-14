#!/usr/bin/env python3
"""Split curated retrospective event rows into follow-up queues."""

import argparse
import json
from pathlib import Path


DEFAULT_CURATION = Path("data/retrospective_event_apply_curation.json")
OUT_EXISTING = Path("data/retrospective_existing_event_update_queue.json")
OUT_RESEARCH = Path("data/retrospective_event_research_queue.json")
OUT_OBSERVATIONS = Path("data/retrospective_non_event_observation_queue.json")


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


def split(curation):
    existing = []
    research = []
    observations = []
    for row in curation.get("rows") or []:
        action = row.get("action")
        base = {
            "candidate_key": row.get("candidate_key"),
            "event_name": row.get("event_name"),
            "venue": row.get("venue"),
            "estimated_date": row.get("estimated_date"),
            "source_url": row.get("source_url"),
            "reason": row.get("reason"),
        }
        if action == "update_existing_or_skip_create":
            existing.append({**base, "next_action": "既存イベントへ証拠/日付/別名を統合するか確認"})
        elif action in {"needs_research", "needs_venue_master", "create_event_candidate"}:
            research.append({**base, "next_action": "正式イベント名・会場・既存重複を調査"})
        elif action == "do_not_create_event":
            observations.append({**base, "next_action": "イベント作成せず、occurrence observations/event_songs証拠として扱う"})
    return existing, research, observations


def payload(name, source, rows):
    return {
        "generated_by": "split_retrospective_event_curation.py",
        "source": source,
        "count": len(rows),
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--curation", type=Path, default=DEFAULT_CURATION)
    parser.add_argument("--existing-out", type=Path, default=OUT_EXISTING)
    parser.add_argument("--research-out", type=Path, default=OUT_RESEARCH)
    parser.add_argument("--observations-out", type=Path, default=OUT_OBSERVATIONS)
    args = parser.parse_args()

    curation = load_json(args.curation, {})
    existing, research, observations = split(curation)
    write_json(args.existing_out, payload("existing", str(args.curation), existing))
    write_json(args.research_out, payload("research", str(args.curation), research))
    write_json(args.observations_out, payload("observations", str(args.curation), observations))
    print(
        "split retrospective curation: "
        f"existing={len(existing)} research={len(research)} observations={len(observations)}"
    )


if __name__ == "__main__":
    main()
