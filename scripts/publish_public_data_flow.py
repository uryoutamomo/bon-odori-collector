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


def build_commands(
    python: str, *, target_year: int, today: str, with_guard: bool
) -> list[list[str]]:
    commands = [
        [
            python,
            "export_public_events.py",
            "--target-year",
            str(target_year),
            "--today",
            today,
        ],
        [python, "-m", "public_export_support.build_publication_gap_review"],
        [python, "-m", "public_json_postprocessors.review_missing_occurrence_venues"],
        [python, "-m", "review_console_ops.run_review_console", "--inventory"],
    ]
    if with_guard:
        commands.append(
            [
                python,
                "-m",
                "public_json_postprocessors.guard_public_events_sync",
                "--target-year",
                str(target_year),
                "--today",
                today,
                "--report-only",
            ]
        )
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
        help="also run public_json_postprocessors.guard_public_events_sync --report-only after regeneration",
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
    parser.add_argument("--target-year", type=int, required=True)
    parser.add_argument("--today", required=True, help="YYYY-MM-DD")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_commands(
        build_commands(
            args.python,
            target_year=args.target_year,
            today=args.today,
            with_guard=args.with_guard,
        ),
        ROOT,
        args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
