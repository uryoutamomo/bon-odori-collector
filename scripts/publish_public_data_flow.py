#!/usr/bin/env python3
"""Run the collector-side public data publication preparation flow.

This script deliberately stops before site sync or deploy. Public web deploys
still require separate operator approval.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def build_commands(python: str, with_guard: bool) -> list[list[str]]:
    commands = [
        [python, "export_public_events.py"],
        [python, "build_publication_gap_review.py"],
        [python, "review_missing_occurrence_venues.py"],
        [python, "run_review_console.py", "--inventory"],
    ]
    if with_guard:
        commands.append([python, "guard_public_events_sync.py", "--report-only"])
    return commands


def run_commands(commands: list[list[str]], cwd: Path, dry_run: bool) -> None:
    for command in commands:
        print("+ " + " ".join(command), flush=True)
        if dry_run:
            continue
        subprocess.run(command, cwd=cwd, check=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare collector public JSON and review inventories without deploying."
    )
    parser.add_argument(
        "--with-guard",
        action="store_true",
        help="also run guard_public_events_sync.py --report-only after regeneration",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the commands without executing them",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used for child commands",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_commands(build_commands(args.python, args.with_guard), ROOT, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
