#!/usr/bin/env python3
"""Stage review console decisions for downstream apply scripts.

This script intentionally does not mutate Master RDB, Notion, public JSON, or
S3 artifacts. It materializes reviewed decisions into per-source JSON files so
the existing domain-specific apply scripts can consume them deliberately.
"""

from __future__ import annotations

import argparse

from review_console import data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="write staged files under data/review_console/staged")
    args = parser.parse_args()

    result = data.stage_apply(write=args.write)
    mode = "write" if args.write else "dry-run"
    print(f"review console stage apply ({mode})")
    print(f"- decision_count: {result['decision_count']}")
    for row in result["staged_files"]:
        print(f"- {row['source_id']}: {row['decision_count']} -> {row['path']}")
    print(f"- note: {result['note']}")


if __name__ == "__main__":
    main()
