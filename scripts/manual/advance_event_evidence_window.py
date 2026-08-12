#!/usr/bin/env python3
"""Advance the X event evidence pilot to the next review window."""

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


STATE_PATH = Path("data/x_event_evidence_state.json")
CONFIG_PATH = Path("x_queries.json")
OUT_PATH = Path("data/x_event_evidence_advance_result.json")


def load_json(path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_datetime(value):
    if not value:
        raise ValueError("missing datetime value")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def next_window(state, days):
    start_value = state.get("covered_until") or state.get("window_end")
    start = parse_datetime(start_value)
    end = start + timedelta(days=days)
    return start, end


def build_next_state(state, days, note):
    start, end = next_window(state, days)
    now = datetime.now(timezone.utc).isoformat()
    history = list(state.get("window_history") or [])
    history.append(
        {
            "window_start": state.get("window_start"),
            "window_end": state.get("window_end"),
            "covered_until": state.get("covered_until"),
            "completed_at": state.get("completed_at"),
            "reviewed_at": now,
            "review_note": note,
            "pages_completed": state.get("pages_completed", 0),
            "tweets_scanned": state.get("tweets_scanned", 0),
            "evidence_detected": state.get("evidence_detected", 0),
        }
    )
    next_state = {
        **state,
        "status": "in_progress",
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "batch_index": 0,
        "batch_cursors": {},
        "completed_batches": [],
        "pages_completed": 0,
        "tweets_scanned": 0,
        "evidence_detected": 0,
        "pending_evidence": [],
        "started_at": now,
        "updated_at": now,
        "window_history": history,
        "previous_covered_until": state.get("covered_until") or state.get("window_end"),
    }
    for key in ("completed_at", "covered_until", "pending_cleared_at", "last_error"):
        next_state.pop(key, None)
    return next_state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=STATE_PATH)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    parser.add_argument("--days", type=int)
    parser.add_argument("--note", default="pilot review cleared; advance to next window")
    parser.add_argument("--allow-pending", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    state = load_json(args.state, {})
    if not state:
        raise SystemExit(f"state file not found or empty: {args.state}")
    if state.get("status") != "awaiting_review":
        raise SystemExit(f"state is not awaiting_review: {state.get('status')}")
    pending = state.get("pending_evidence") or []
    if pending and not args.allow_pending:
        raise SystemExit(f"pending_evidence is not empty: {len(pending)} rows")

    config = load_json(args.config, {})
    evidence_cfg = config.get("event_evidence", {})
    days = args.days or int(evidence_cfg.get(
        "lookback_window_days",
        evidence_cfg.get("initial_window_days", 14),
    ))
    next_state = build_next_state(state, days, args.note)
    result = {
        "dry_run": not args.apply,
        "state": str(args.state),
        "days": days,
        "from_window": {
            "window_start": state.get("window_start"),
            "window_end": state.get("window_end"),
            "covered_until": state.get("covered_until"),
        },
        "to_window": {
            "window_start": next_state.get("window_start"),
            "window_end": next_state.get("window_end"),
        },
        "selected_handle_count": len(next_state.get("selected_handles") or []),
        "note": args.note,
    }
    write_json(args.out, result)
    if args.apply:
        write_json(args.state, next_state)
    print(
        "advance event evidence window: {old} -> {new} dry_run={dry_run}".format(
            old=result["from_window"]["covered_until"] or result["from_window"]["window_end"],
            new=result["to_window"]["window_end"],
            dry_run=result["dry_run"],
        )
    )
    print(f"wrote {args.out}")
    if args.apply:
        print(f"updated {args.state}")


if __name__ == "__main__":
    main()
