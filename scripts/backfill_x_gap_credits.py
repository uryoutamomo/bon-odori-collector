#!/usr/bin/env python3
"""One-time/repeatable backfill for the cumulative X gap-credit ledger.

This deliberately reads Git history only when refreshing the small ledger;
the collector itself only reads the resulting JSON file.
"""
from __future__ import annotations

import argparse
import collections
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PATHS = ("data/x_gap_candidates.json", "data/x_review_lanes.json")


def rows(payload):
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("lanes"), dict):
        return [row for lane in payload["lanes"].values() if isinstance(lane, list) for row in lane]
    return payload.get("candidates") or payload.get("items") or []


def build(revision="origin/main"):
    credits, seen = collections.Counter(), set()
    for path in PATHS:
        log = subprocess.run(
            ["git", "log", "--format=%H", revision, "--", path], cwd=REPO,
            text=True, capture_output=True, check=True,
        )
        for commit in log.stdout.split():
            shown = subprocess.run(
                ["git", "show", f"{commit}:{path}"], cwd=REPO, text=True, capture_output=True,
            )
            if shown.returncode:
                continue
            try:
                payload = json.loads(shown.stdout)
            except json.JSONDecodeError:
                continue
            for row in rows(payload):
                if not isinstance(row, dict):
                    continue
                handle = str(row.get("source_author") or "").lstrip("@").lower()
                key = (handle, row.get("source_key"), row.get("candidate_kind"))
                if handle and key not in seen:
                    seen.add(key)
                    credits[handle] += 1
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_revision": revision,
        "credits": dict(sorted(credits.items())),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--revision", default="origin/main")
    parser.add_argument("--out", type=Path, default=REPO / "data/x_gap_credits.json")
    args = parser.parse_args()
    payload = build(args.revision)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"x gap credits: {len(payload['credits'])} accounts -> {args.out}")


if __name__ == "__main__":
    main()
