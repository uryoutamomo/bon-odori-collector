#!/usr/bin/env python3
"""Print evidence snippets for retrospective ready-for-apply event rows."""

import json
from pathlib import Path


DRY_RUN = Path("data/retrospective_occurrence_dry_run.json")
PLAN = Path("data/retrospective_event_apply_plan.json")


def main():
    dry_run = json.loads(DRY_RUN.read_text(encoding="utf-8"))
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    candidates = {row.get("candidate_key"): row for row in dry_run.get("new_event_candidates", [])}
    for row in plan.get("ready_for_apply", []):
        candidate = candidates.get(row.get("candidate_key"), {})
        print()
        print("## " + (row.get("event_name") or ""))
        print(f"venue={row.get('venue') or ''} date={row.get('estimated_date') or ''}")
        for evidence in (candidate.get("evidence") or [])[:3]:
            text = (evidence.get("text") or "").replace("\n", " ")
            print("- " + text[:500])
            if evidence.get("url"):
                print("  " + evidence["url"])


if __name__ == "__main__":
    main()
