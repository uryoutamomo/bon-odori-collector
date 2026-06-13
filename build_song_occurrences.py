#!/usr/bin/env python3
"""Build yearly event-song occurrence and prediction JSON files."""

import argparse
import json
from pathlib import Path

from song_occurrences import (
    OUT_OCCURRENCES,
    OUT_PUBLIC,
    OUT_SNAPSHOT,
    build_occurrences,
    prediction_snapshot,
    public_rows,
)


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-year", type=int, default=None)
    parser.add_argument("--out", type=Path, default=OUT_OCCURRENCES)
    parser.add_argument("--public-out", type=Path, default=OUT_PUBLIC)
    parser.add_argument("--snapshot-out", type=Path, default=OUT_SNAPSHOT)
    args = parser.parse_args()

    occurrence_data = build_occurrences(target_year=args.target_year)
    write_json(args.out, occurrence_data)
    write_json(args.public_out, {
        "generated_by": occurrence_data["generated_by"],
        "generated_at": occurrence_data["generated_at"],
        "target_year": occurrence_data["target_year"],
        "occurrences": public_rows(occurrence_data),
    })
    write_json(args.snapshot_out, prediction_snapshot(occurrence_data))
    print(
        "曲 occurrence 生成完了: "
        f"occurrences={occurrence_data['occurrence_count']} "
        f"relations={occurrence_data['song_relation_count']} -> {args.out}"
    )


if __name__ == "__main__":
    main()
