#!/usr/bin/env python3
"""Stage review-console inbox decisions without applying operational data."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


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
ROUTES = ("change_request", "domain_stage", "research_followup", "no_apply")
UPDATES_FILE = "review_inbox_decision_updates.json"
RARE_SIGNAL_ACCEPT_ACTION = "stage_registration_candidate"
RARE_SIGNAL_DOMAIN_STAGE_TYPE = "rare_signal_registration_candidate"
YOUTUBE_ACCEPT_ACTION = "add_song_evidence"
YOUTUBE_DOMAIN_STAGE_TYPE = "youtube_song_evidence"
B4_ACCEPT_ACTIONS = {
    "song": ("stage_song_candidate", "song_candidate", "daily_song_candidate"),
    "term": ("stage_term_candidate", "term_candidate", "daily_term_candidate"),
    "song_research": ("stage_song_venue_evidence", "song_venue_evidence", "daily_term_candidate"),
    "venue_candidate": ("stage_venue_candidate", "venue_candidate", "accepted_venue_song_missing_venue"),
}
URL_RE = re.compile(r"https?://[^\s、，。)）\]}＞>\"']+")
X_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "t.co"}
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
RARE_SIGNAL_PROMOTION_TARGETS = {"event", "song", "venue", "existing_evidence"}


def clean_url(value: Any) -> str:
    return str(value or "").strip().rstrip(".,")


def is_x_url(value: str) -> bool:
    try:
        host = (urlsplit(value).hostname or "").casefold()
        return any(host == domain or host.endswith("." + domain) for domain in X_HOSTS)
    except ValueError:
        return False


def is_http_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return parsed.scheme.casefold() in {"http", "https"} and bool(parsed.netloc)
    except ValueError:
        return False


def youtube_video_id(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    host = (parsed.hostname or "").casefold()
    if host not in YOUTUBE_HOSTS:
        return ""
    if host == "youtu.be":
        return parsed.path.strip("/").split("/", 1)[0]
    if parsed.path.startswith("/shorts/"):
        return parsed.path.split("/shorts/", 1)[1].split("/", 1)[0]
    for part in parsed.query.split("&"):
        key, _, value = part.partition("=")
        if key == "v":
            return value
    return ""


def nested_values(value: Any, key: str) -> list[Any]:
    if not isinstance(value, dict):
        return []
    found = value.get(key)
    if found is None and isinstance(value.get("payload"), dict):
        found = value["payload"].get(key)
    if found is None:
        return []
    return found if isinstance(found, list) else [found]


def rare_signal_confirmation_urls(row: dict[str, Any], raw: dict[str, Any]) -> list[str]:
    values: list[Any] = URL_RE.findall(str(row.get("note") or ""))
    values.extend(nested_values(raw, "confirmed_source_urls"))
    values.extend(nested_values(raw, "confirmed_source_url"))
    urls: list[str] = []
    for value in values:
        url = clean_url(value)
        if url and is_http_url(url) and not is_x_url(url) and url not in urls:
            urls.append(url)
    return urls


def canonical_route(decision: str, apply_value: str, raw: dict[str, Any]) -> str:
    if decision in {"rejected", "hold"}:
        return "no_apply"
    if decision == "needs_research":
        return "research_followup"
    if str(raw.get("kind") or "") == "rare_signal":
        if apply_value == RARE_SIGNAL_ACCEPT_ACTION:
            return "domain_stage"
        raise ValueError(
            "accepted rare signal decision must stage a registration candidate"
        )
    if str(raw.get("kind") or "") == "youtube_evidence":
        if apply_value == YOUTUBE_ACCEPT_ACTION:
            return "domain_stage"
        raise ValueError(
            "accepted YouTube evidence decision must stage add_song_evidence"
        )
    kind = str(raw.get("kind") or "")
    if kind in B4_ACCEPT_ACTIONS:
        expected_action, _, _ = B4_ACCEPT_ACTIONS[kind]
        if apply_value == expected_action:
            return "domain_stage"
        raise ValueError(f"accepted {kind} decision must use {expected_action}")
    if kind == "historical_quality" and apply_value == "keep_historical_reference":
        return "no_apply"
    if apply_value in CHANGE_REQUEST_TYPES:
        return "change_request"
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
    if str(raw.get("kind") or "") == "rare_signal" and decision == "accepted":
        if str(raw.get("source_id") or "") != "rare_signal":
            raise ValueError("accepted rare signal decision requires rare_signal source_id")
        confirmed_source_urls = rare_signal_confirmation_urls(row, raw)
        if not confirmed_source_urls:
            raise ValueError(
                "accepted rare signal decision requires a non-X confirmation URL"
            )
        payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
        promotion_target = str(payload.get("promotion_target") or "")
        if promotion_target not in RARE_SIGNAL_PROMOTION_TARGETS:
            raise ValueError(
                f"accepted rare signal decision has unsupported promotion target: {promotion_target or 'missing'}"
            )
        staged["domain_stage_type"] = RARE_SIGNAL_DOMAIN_STAGE_TYPE
        staged["registration_candidate"] = {
            "source_inbox_id": inbox_id,
            "source_id": str(raw.get("source_id") or ""),
            "source_key": str(raw.get("source_key") or ""),
            "promotion_target": promotion_target,
            "event_name": str(raw.get("event_name") or payload.get("possible_event_name") or ""),
            "venue": str(raw.get("venue") or payload.get("possible_venue") or ""),
            "event_year": raw.get("event_year"),
            "confirmed_source_urls": confirmed_source_urls,
            "write_mode": "staged_only",
        }
    if str(raw.get("kind") or "") == "youtube_evidence" and decision == "accepted":
        if str(raw.get("source_id") or "") != "youtube_evidence":
            raise ValueError("accepted YouTube evidence requires youtube_evidence source_id")
        payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
        video_id = str(payload.get("video_id") or "").strip()
        source_url = str(raw.get("source_url") or payload.get("video_url") or "").strip()
        if not video_id or youtube_video_id(source_url) != video_id:
            raise ValueError("accepted YouTube evidence requires video_id and source URL")
        staged["domain_stage_type"] = YOUTUBE_DOMAIN_STAGE_TYPE
        staged["youtube_evidence"] = {
            "source_inbox_id": inbox_id,
            "source_id": str(raw.get("source_id") or ""),
            "source_key": str(raw.get("source_key") or ""),
            "video_id": video_id,
            "video_url": source_url,
            "event_name": str(raw.get("event_name") or ""),
            "venue": str(raw.get("venue") or ""),
            "event_year": raw.get("event_year"),
            "legacy_action": str(payload.get("action") or ""),
            "title_song_candidates": payload.get("title_song_candidates") or [],
            "write_mode": "staged_only",
        }
    kind = str(raw.get("kind") or "")
    if kind in B4_ACCEPT_ACTIONS and decision == "accepted":
        expected_action, stage_type, expected_source = B4_ACCEPT_ACTIONS[kind]
        if apply_value != expected_action or str(raw.get("source_id") or "") != expected_source:
            raise ValueError(f"accepted {kind} decision has invalid action or source")
        payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
        if not str(raw.get("source_key") or "").strip():
            raise ValueError(f"accepted {kind} candidate requires source_key")
        required = {
            "song": ("canonical_song_name", "term"),
            "term": ("term",),
            "song_research": ("song_name", "venue"),
            "venue_candidate": ("suggested_venue",),
        }[kind]
        if kind == "song":
            if not any(str(payload.get(field) or "").strip() for field in required):
                raise ValueError("accepted song candidate requires a song name")
        elif any(not str(payload.get(field) or "").strip() for field in required):
            raise ValueError(f"accepted {kind} candidate is missing required identity")
        staged["domain_stage_type"] = stage_type
        staged["domain_candidate"] = {
            "source_inbox_id": inbox_id,
            "source_id": expected_source,
            "source_key": str(raw.get("source_key") or ""),
            "kind": kind,
            "payload": payload,
            "write_mode": "staged_only",
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
