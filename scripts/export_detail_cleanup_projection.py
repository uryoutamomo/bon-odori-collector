#!/usr/bin/env python3
"""Export a Master-RDB snapshot for the bounded detail-repair diff check."""

import argparse
import json
import sys
from pathlib import Path

# `python scripts/...` puts only scripts/ on sys.path.  Keep this direct CLI
# usable from the repository root, like the repair workflow invokes it.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from export_public_events import build_public_events_from_master, project_public_events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--events-out", type=Path, required=True)
    parser.add_argument("--source-map-out", type=Path, required=True)
    parser.add_argument("--target-year", type=int, required=True)
    parser.add_argument("--today", required=True)
    args = parser.parse_args()
    events, _, _, _ = build_public_events_from_master(args.db, target_year=args.target_year)
    projection = project_public_events(events, target_year=args.target_year, db_path=args.db, today=args.today)
    for path, payload in ((args.events_out, projection["public_events"]), (args.source_map_out, projection["source_map"])):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
