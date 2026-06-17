#!/usr/bin/env python3
"""Scan registered official/semi-official event source pages for current-year updates."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from proactive_search import (
    DEFAULT_CONFIG,
    DEFAULT_OFFICIAL_CANDIDATES,
    load_targets,
    parse_months,
    scan_official_sources,
    select_due_targets,
    select_targets_for_run,
)


ROOT = Path(__file__).resolve().parent
VENUE_MASTER = ROOT / "data/venue_master.json"


def read_json(path: Path):
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--out", default=DEFAULT_OFFICIAL_CANDIDATES)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--lead-months", type=int, default=None)
    parser.add_argument("--all", action="store_true", help="check all targets with official_sources")
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()

    venue_master = read_json(VENUE_MASTER) or []
    targets, config = load_targets(venue_master, args.config)
    targets = [target for target in targets if target.get("official_sources")]
    lead_months = args.lead_months
    if lead_months is None:
        lead_months = int(config.get("lead_months", 2))
    if not args.all:
        targets = select_due_targets(targets, lead_months=lead_months)
        targets = select_targets_for_run(
            targets,
            {},
            limit=args.limit or int(config.get("max_targets_per_run", 36)),
        )
    elif args.limit:
        targets = targets[:args.limit]

    rows = []
    for target in targets:
        rows.extend(scan_official_sources(target, args.year, timeout=args.timeout))

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "check_official_sources.py",
        "year": args.year,
        "target_count": len(targets),
        "confirmed_count": sum(1 for row in rows if row.get("status") == "confirmed"),
        "candidates": rows,
    }
    write_json(ROOT / args.out, output)
    print(
        "official source check: "
        f"targets={output['target_count']} "
        f"candidates={len(rows)} "
        f"confirmed={output['confirmed_count']} -> {ROOT / args.out}"
    )


if __name__ == "__main__":
    main()
