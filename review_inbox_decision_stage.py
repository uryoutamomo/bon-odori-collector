#!/usr/bin/env python3
"""Stage review-console inbox decisions without applying operational data."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


CONSOLE_DECISIONS = {
    "accept": "accepted",
    "reject": "rejected",
    "hold": "hold",
    "needs_research": "needs_research",
}
CHANGE_REQUEST_TYPES = {
    "confirm_current_date": "confirm_current_year_date",
    "promote_historical_reference": "add_historical_reference",
    "fill_venue": "update_venue",
}
DOMAIN_STAGE_KINDS = {"song", "term", "youtube_evidence", "song_research"}
ROUTES = ("change_request", "domain_stage", "research_followup", "no_apply")
UPDATES_FILE = "review_inbox_decision_updates.json"


def canonical_route(decision: str, apply_value: str, raw: dict[str, Any]) -> str:
    if decision in {"rejected", "hold"}:
        return "no_apply"
    if decision == "needs_research":
        return "research_followup"
    if apply_value in CHANGE_REQUEST_TYPES:
        return "change_request"
    if str(raw.get("kind") or "") in DOMAIN_STAGE_KINDS:
        return "domain_stage"
    if apply_value in {"fill_source_url", "needs_research"}:
        return "research_followup"
    raise ValueError(
        f"accepted review inbox decision has no safe route: {apply_value or raw.get('kind') or 'unknown'}"
    )


def stage_row(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("raw")
    if not isinstance(raw, dict):
        raise ValueError("review inbox console decision is missing raw item")
    inbox_id = str(raw.get("inbox_id") or "")
    if not inbox_id:
        raise ValueError("review inbox console decision is missing inbox_id")
    console_decision = str(row.get("decision") or "")
    if console_decision not in CONSOLE_DECISIONS:
        raise ValueError(f"unsupported review inbox console decision: {console_decision}")
    decision = CONSOLE_DECISIONS[console_decision]
    apply_value = str(row.get("apply_value") or "")
    route = canonical_route(decision, apply_value, raw)
    reviewer = str(row.get("reviewer") or "").strip()
    reviewed_at = str(row.get("reviewed_at") or "").strip()
    if not reviewer or not reviewed_at:
        raise ValueError("review inbox decision requires reviewer and reviewed_at")
    update = {
        "inbox_id": inbox_id,
        "decision": decision,
        "decided_by": reviewer,
        "decided_at": reviewed_at,
        "decision_route": route,
    }
    staged = {
        "inbox_update": update,
        "apply_value": apply_value,
        "note": str(row.get("note") or ""),
        "source_item": raw,
    }
    change_type = CHANGE_REQUEST_TYPES.get(apply_value)
    if route == "change_request" and change_type:
        staged["change_type"] = change_type
    return staged


def build_decision_stage(export_payload: dict[str, Any]) -> dict[str, Any]:
    rows = [
        stage_row(row)
        for row in export_payload.get("rows") or []
        if row.get("source_id") == "review_inbox"
    ]
    inbox_ids = [row["inbox_update"]["inbox_id"] for row in rows]
    duplicates = sorted({inbox_id for inbox_id in inbox_ids if inbox_ids.count(inbox_id) > 1})
    if duplicates:
        raise ValueError("duplicate review inbox decision updates: " + ", ".join(duplicates))
    by_route = {
        route: [row for row in rows if row["inbox_update"]["decision_route"] == route]
        for route in ROUTES
    }
    return {
        "schema_version": 1,
        "generated_by": "review_inbox_decision_stage.py",
        "write_mode": "staged_only",
        "decision_count": len(rows),
        "route_counts": {route: len(route_rows) for route, route_rows in by_route.items()},
        "inbox_decision_updates": [row["inbox_update"] for row in rows],
        "by_route": by_route,
        "note": "packets only: Master RDB and domain data were not modified",
    }


def write_decision_stage(stage: dict[str, Any], staged_dir: Path) -> list[dict[str, Any]]:
    staged_dir = Path(staged_dir)
    staged_dir.mkdir(parents=True, exist_ok=True)
    updates_path = staged_dir / UPDATES_FILE
    updates_payload = {
        key: value for key, value in stage.items() if key != "by_route"
    }
    write_json_atomic(updates_path, updates_payload)
    staged_files = []
    for route, rows in stage["by_route"].items():
        if not rows:
            continue
        payload = {
            "schema_version": 1,
            "generated_by": "review_inbox_decision_stage.py",
            "source_id": "review_inbox",
            "decision_route": route,
            "write_mode": "staged_only",
            "decision_count": len(rows),
            "rows": rows,
        }
        path = staged_dir / f"review_inbox_{route}_decisions.json"
        write_json_atomic(path, payload)
        staged_files.append(
            {
                "source_id": f"review_inbox:{route}",
                "path": str(path),
                "decision_count": len(rows),
                "decision_route": route,
            }
        )
    return staged_files


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    os.replace(temp_path, path)
