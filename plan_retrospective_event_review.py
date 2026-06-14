#!/usr/bin/env python3
"""Build a dry-run apply plan from retrospective event review decisions."""

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_DRY_RUN = Path("data/retrospective_occurrence_dry_run.json")
DEFAULT_DECISIONS = Path("data/retrospective_event_review_decisions.json")
DEFAULT_OUT = Path("data/retrospective_event_apply_plan.json")

DECISION_STATUS = {
    "登録": "ready_for_apply",
    "要調査": "needs_research",
    "不採用": "rejected",
    "保留": "hold",
}


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


def decision_map(decisions):
    rows = decisions.get("rows") if isinstance(decisions, dict) else decisions
    if not isinstance(rows, list):
        return {}
    return {
        str(row.get("key") or ""): {
            "decision": row.get("decision") or "",
            "note": row.get("note") or "",
        }
        for row in rows
        if isinstance(row, dict) and row.get("key")
    }


def plan_row(candidate, review):
    decision = review.get("decision") or ""
    status = DECISION_STATUS.get(decision, "undecided")
    venue = candidate.get("venue_match_name") or candidate.get("venue") or ""
    evidence_urls = candidate.get("evidence_urls") or []
    return {
        "candidate_key": candidate.get("candidate_key"),
        "decision": decision,
        "status": status,
        "note": review.get("note") or "",
        "event_name": candidate.get("display_name") or "",
        "normalized_event": candidate.get("normalized_event") or "",
        "venue": venue,
        "venue_matched": bool(candidate.get("venue_matched")),
        "year": candidate.get("year"),
        "estimated_date": candidate.get("estimated_date") or "",
        "month": candidate.get("month") or "",
        "score": candidate.get("score"),
        "review_priority": candidate.get("review_priority") or "",
        "review_flags": candidate.get("review_flags") or [],
        "evidence_count": candidate.get("evidence_count") or 0,
        "source_url": evidence_urls[0] if evidence_urls else "",
        "evidence_urls": evidence_urls,
        "source": "retrospective_harvest",
    }


def build_plan(dry_run, decisions, generated_at=None):
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    reviews = decision_map(decisions)
    candidates = dry_run.get("new_event_candidates") or []
    rows = [plan_row(candidate, reviews.get(candidate.get("candidate_key"), {})) for candidate in candidates]
    counts = Counter(row["status"] for row in rows)
    decision_counts = Counter(row["decision"] or "未判定" for row in rows)
    ready = [row for row in rows if row["status"] == "ready_for_apply"]
    return {
        "generated_by": "plan_retrospective_event_review.py",
        "generated_at": generated_at,
        "source": str(DEFAULT_DRY_RUN),
        "decisions_source": str(DEFAULT_DECISIONS),
        "mode": "dry_run",
        "apply_performed": False,
        "candidate_count": len(candidates),
        "reviewed_count": sum(1 for row in rows if row["decision"]),
        "ready_for_apply_count": len(ready),
        "counts": {
            "by_status": dict(sorted(counts.items())),
            "by_decision": dict(sorted(decision_counts.items())),
        },
        "ready_for_apply": ready,
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", type=Path, default=DEFAULT_DRY_RUN)
    parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    output = build_plan(load_json(args.dry_run, {}), load_json(args.decisions, {}))
    output["source"] = str(args.dry_run)
    output["decisions_source"] = str(args.decisions)
    write_json(args.out, output)
    print(
        "retrospective event apply plan: "
        f"candidates={output['candidate_count']} "
        f"reviewed={output['reviewed_count']} "
        f"ready_for_apply={output['ready_for_apply_count']} -> {args.out}"
    )


if __name__ == "__main__":
    main()
