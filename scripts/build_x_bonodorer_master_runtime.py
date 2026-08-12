#!/usr/bin/env python3
"""Materialize master song/place/event terms for offline X-account scoring."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import collect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-db", type=Path, default=ROOT / "data/bon_odori_master.sqlite")
    parser.add_argument("--out", type=Path, default=ROOT / "data/x_bonodorer_master_runtime.json")
    args = parser.parse_args()
    runtime = collect._load_x_bonodorer_master_runtime(db_path=args.master_db)
    payload = {
        key: (sorted(values) if isinstance(values, set) else values)
        for key, values in runtime.items()
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"x bonodorer master runtime: songs={len(payload['songs'])} places={len(payload['places'])} events={len(payload['events'])}")


if __name__ == "__main__":
    main()
