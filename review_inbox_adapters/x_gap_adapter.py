"""Adapt the gap-driven X queue or durable backlog into review-inbox items.

The adapter is pure and snapshot-only.  The scheduled writer consumes a
five-item ``cohort`` snapshot behind explicit environment and CAS gates; this
keeps a machine-selected X post from becoming an unreviewed database change.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT=Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from review_inbox_adapters.source_adapter import (
    adapt_source_payload,
    input_sha256,
    load_adapted_source,
    write_adapted_snapshot,
)
from x_candidate_backlog import BacklogError, select_daily_cohort

DEFAULT_INPUT=ROOT / "data" / "x_gap_candidates.json"
DEFAULT_OUTPUT=ROOT / "data" / "review_inbox_adapted" / "x_gap.json"
DEFAULT_LANES_INPUT=ROOT / "data" / "x_review_lanes.json"
DEFAULT_BACKLOG_INPUT=ROOT / "data" / "x_candidate_backlog.json"
CANARY_LANES=("lane2_operator_review","lane3_user_review")
DAILY_COHORT_MAX=5

class XGapAdapter:
    source_id="x_gap"

    def adapt(self, payload: Any) -> Iterable[Mapping[str, Any]]:
        if not isinstance(payload,dict) or not isinstance(payload.get("candidates"),list):
            raise ValueError("x gap payload requires candidates list")
        if len(payload["candidates"]) > 30:
            raise ValueError("x gap input exceeds the 30-item daily contract")
        return [self.adapt_row(row) for row in payload["candidates"]]

    def adapt_row(self,row: Any) -> dict[str,Any]:
        if not isinstance(row,dict): raise TypeError("x gap candidate must be an object")
        match=row.get("matched_occurrence") or {}
        event_name=str(match.get("event_name") or "").strip()
        title=event_name or str(row.get("source_text") or "").strip()[:80]
        source_key=str(row.get("source_key") or "").strip()
        if not source_key: raise ValueError("x gap candidate requires stable source_key")
        officiality=row.get("source_officiality") or {}
        official=officiality.get("classification") == "registered_official_social"
        kind=str(row.get("candidate_kind") or "")
        action={
            "missing_date":"confirm_current_year_date",
            "date_range_conflict":"review_date_range_conflict",
            "official_new_event":"review_new_event",
            "informal_new_event":"review_new_event",
            "past_event_report":"review_historical_event",
            "schedule_change":"review_schedule_change",
        }.get(kind, "review_x_event_evidence")
        payload=copy.deepcopy(row)
        # The existing change-request bridge consumes this compact date text
        # format.  Keep the original X text alongside it as evidence.
        if action == "confirm_current_year_date":
            date_text=first_date_hint(row.get("date_hints") or [])
            if date_text:
                payload["event_date_text"]=f"{row.get('event_year')}\n{date_text}"
            occurrence_id=str(match.get("occurrence_id") or "")
            if occurrence_id:
                payload["observed_candidate"]={"candidate_key":occurrence_id}
        return {"kind":"x_gap", "domain":"X", "time_scope":"future", "priority_label":"P0" if official else "P1",
                "priority_score":row.get("priority_score"), "title":title, "event_name":event_name,
                "venue":str(match.get("venue") or ""), "event_year":row.get("event_year"),
                "source_key":source_key, "source_url":str(row.get("source_url") or ""),
                "recommended_action":action, "payload":payload}

def first_date_hint(hints: list[Any]) -> str:
    for hint in hints:
        match=re.search(r"(?:20\d{2}[/-])?(\d{1,2})月(\d{1,2})日?",str(hint))
        if match:
            return f"{match.group(1)}/{match.group(2)}"
    return ""

def build_snapshot(input_path:Path)->dict[str,Any]:
    snapshot=load_adapted_source(XGapAdapter(),input_path)
    snapshot["write_mode"]="snapshot_only_default_off"
    snapshot["upstream_boundary"]="bounded_gap_driven_x_candidates"
    return snapshot


def build_daily_cohort_snapshot(
    backlog_path: Path, *, max_items: int = DAILY_COHORT_MAX
) -> dict[str, Any]:
    """Freeze up to five unprocessed backlog rows as an explicit partial cohort.

    ``selection.mode=cohort`` is intentionally distinct from ``all``.  The
    review console may use absence from a complete ``all`` snapshot as an
    auto-resolution signal; absence from this five-row sample proves nothing.
    """
    backlog_path = Path(backlog_path)
    raw = backlog_path.read_bytes()
    backlog = json.loads(raw)
    try:
        selected = select_daily_cohort(backlog, max_items=max_items)
    except BacklogError as exc:
        raise ValueError(str(exc)) from exc
    candidates = [copy.deepcopy(row["candidate"]) for row in selected]
    items = adapt_source_payload(XGapAdapter(), {"candidates": candidates})
    source_keys = [item["source_key"] for item in items]
    return {
        "source_id": XGapAdapter.source_id,
        "input_path": str(backlog_path),
        "input_sha256": input_sha256(raw),
        "input_size_bytes": len(raw),
        "item_count": len(items),
        "items": items,
        "selection": {
            "mode": "cohort",
            "cohort": "daily_canary",
            "max_items": max_items,
            "source_keys": source_keys,
        },
        "write_mode": "snapshot_only_default_off",
        "upstream_boundary": "durable_x_candidate_backlog_unprocessed_only",
    }


def build_canary_snapshot(input_path: Path, *, canary_source_key: str) -> dict[str, Any]:
    """Freeze exactly one reviewable x_gap lane row for an explicit canary.

    The lane artifact is the selection boundary: lane1 plans and archived rows
    are intentionally not review-inbox inputs.
    """
    source_key = str(canary_source_key or "").strip()
    if not source_key:
        raise ValueError("x gap canary source key must not be empty")
    raw = Path(input_path).read_bytes()
    payload = json.loads(raw)
    lanes = payload.get("lanes") if isinstance(payload, dict) else None
    if not isinstance(lanes, dict):
        raise ValueError("x gap canary input requires lanes object")
    selected = []
    for lane_name in CANARY_LANES:
        rows = lanes.get(lane_name)
        if not isinstance(rows, list):
            raise ValueError(f"x gap canary input requires {lane_name} list")
        selected.extend(
            row for row in rows
            if isinstance(row, dict) and str(row.get("source_key") or "") == source_key
        )
    if len(selected) != 1:
        raise ValueError(
            "x gap canary source key must select exactly one lane2/lane3 item: "
            + source_key
        )
    items = adapt_source_payload(XGapAdapter(), {"candidates": selected})
    return {
        "source_id": XGapAdapter.source_id,
        "input_path": str(input_path),
        "input_sha256": input_sha256(raw),
        "input_size_bytes": len(raw),
        "item_count": 1,
        "items": items,
        "selection": {"mode": "canary", "source_keys": [source_key]},
        "write_mode": "snapshot_only_default_off",
        "upstream_boundary": "x_gap_lane2_lane3_only",
        "lane": str(selected[0].get("lane") or ""),
    }

def main()->None:
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,default=DEFAULT_INPUT)
    p.add_argument("--backlog",type=Path)
    p.add_argument("--daily-limit",type=int,default=DAILY_COHORT_MAX)
    p.add_argument("--output",type=Path,default=DEFAULT_OUTPUT)
    a=p.parse_args()
    snapshot=(
        build_daily_cohort_snapshot(a.backlog,max_items=a.daily_limit)
        if a.backlog
        else build_snapshot(a.input)
    )
    write_adapted_snapshot(snapshot,a.output)
    print(
        f"x gap snapshot: mode={snapshot.get('selection',{}).get('mode','all')} "
        f"items={snapshot['item_count']} -> {a.output}"
    )

if __name__ == "__main__": main()
