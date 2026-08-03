"""Adapt the bounded, gap-driven X queue into review-inbox items.

The adapter is intentionally snapshot-only.  Production dual-write remains
behind the existing shadow/CAS gate; this keeps a machine-selected X post from
becoming an unreviewed database change.
"""
from __future__ import annotations

import argparse
import copy
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT=Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from review_inbox_adapters.source_adapter import load_adapted_source, write_adapted_snapshot

DEFAULT_INPUT=ROOT / "data" / "x_gap_candidates.json"
DEFAULT_OUTPUT=ROOT / "data" / "review_inbox_adapted" / "x_gap.json"

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
        action={"missing_date":"confirm_current_year_date", "date_range_conflict":"review_date_range_conflict", "informal_new_event":"review_new_event"}.get(kind, "review_schedule_change")
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

def main()->None:
    p=argparse.ArgumentParser(); p.add_argument("--input",type=Path,default=DEFAULT_INPUT); p.add_argument("--output",type=Path,default=DEFAULT_OUTPUT); a=p.parse_args()
    snapshot=build_snapshot(a.input); write_adapted_snapshot(snapshot,a.output); print(f"x gap snapshot: items={snapshot['item_count']} -> {a.output}")

if __name__ == "__main__": main()
