#!/usr/bin/env python3
"""Check human-labelled X accounts against the prospective two-roster result.

This is deliberately a dry-run of roster membership: S3a must not switch the
live collection roster.  A high score alone is not a failure for a negative
example when the final roster correctly excludes it as a bot, reviewed
exclusion, or paused account.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import collect

ANNOUNCE_LIMIT = 180
RECORD_LIMIT = 60


def _load_manual_statuses(path):
    try:
        rows = json.loads(Path(path).read_text(encoding="utf-8")).get("accounts", [])
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}
    return {
        collect._norm_handle(row.get("handle")): row.get("manual_status") or ""
        for row in rows if collect._norm_handle(row.get("handle"))
    }


def _rank(accounts, field):
    return sorted(
        accounts.items(),
        key=lambda item: (
            -item[1].get(field, 0),
            -item[1].get("gap_credits", 0),
            -item[1].get("bon23_count", 0),
            -item[1].get("recent_posts_seen", 0),
            item[0],
        ),
    )


def build_rosters(accounts, manual_statuses=None, exclusions=None):
    """Return prospective rosters and the reason each account is or is not eligible."""
    manual_statuses = manual_statuses or {}
    exclusions = exclusions or {}
    eligibility = {}
    eligible = {}
    manual_included = set()
    for handle, row in accounts.items():
        status = manual_statuses.get(handle, "")
        if status == "休止":
            eligibility[handle] = "manual_paused"
        elif handle in exclusions:
            eligibility[handle] = "reviewed_exclusion"
        elif row.get("is_area_bot"):
            eligibility[handle] = "area_bot"
        else:
            eligibility[handle] = "eligible"
            eligible[handle] = row
            if status in {"優先", "通常"}:
                manual_included.add(handle)

    announce = set(manual_included)
    record = set(manual_included)
    announce.update(handle for handle, _row in _rank(eligible, "announce_score")[:ANNOUNCE_LIMIT])
    record.update(handle for handle, _row in _rank(eligible, "record_score")[:RECORD_LIMIT])
    return {
        "announce": announce,
        "record": record,
        "eligibility": eligibility,
        "manual_included": manual_included,
    }


def check(voices, gold, cfg=None, *, roster_path=None, exclusions_path=None):
    accounts = collect._build_x_account_scores(voices, cfg or {}).get("accounts", {})
    manual_statuses = _load_manual_statuses(roster_path or ROOT / "data/x_collection_roster.json")
    exclusions = collect._load_x_roster_exclusions(exclusions_path)
    rosters = build_rosters(accounts, manual_statuses, exclusions)
    result = {"positive": {}, "negative": {}, "rosters": {
        "announce_count": len(rosters["announce"]),
        "record_count": len(rosters["record"]),
        "manual_included_count": len(rosters["manual_included"]),
    }, "passed": True}
    for row in gold["positive"]:
        handle = row["handle"].lstrip("@").lower()
        membership = {"announce": handle in rosters["announce"], "record": handle in rosters["record"]}
        result["positive"][handle] = membership
        result["passed"] &= any(membership.values())
    for row in gold["negative"]:
        handle = row["handle"].lstrip("@").lower()
        membership = {"announce": handle in rosters["announce"], "record": handle in rosters["record"]}
        result["negative"][handle] = {**membership, "excluded_by": rosters["eligibility"].get(handle, "not_seen")}
        result["passed"] &= not any(membership.values())
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--voices", type=Path, default=ROOT / "data/voices.json")
    parser.add_argument("--gold", type=Path, default=ROOT / "data/x_bonodorer_gold.json")
    parser.add_argument("--roster", type=Path, default=ROOT / "data/x_collection_roster.json")
    parser.add_argument("--exclusions", type=Path, default=ROOT / "data/x_roster_exclusions.json")
    args = parser.parse_args()
    result = check(
        json.loads(args.voices.read_text(encoding="utf-8")),
        json.loads(args.gold.read_text(encoding="utf-8")),
        collect._load_x_config() or {},
        roster_path=args.roster,
        exclusions_path=args.exclusions,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
