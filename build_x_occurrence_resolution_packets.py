#!/usr/bin/env python3
"""Build E2-S v2 occurrence packets and trusted dependency results."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from master_rdb.master_db import MASTER_DB, connect_existing
from review_inbox_adapters.x_occurrence_resolution_contract import build_packet_set
from review_inbox_adapters.x_song_resolution_contract import load_observation_ledger


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=MASTER_DB)
    parser.add_argument("--observations", type=Path, default=Path("data/x_song_observations.json"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--machine-results-out", type=Path)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--generated-at")
    args = parser.parse_args(argv)
    ledger = load_observation_ledger(args.observations)
    with connect_existing(args.db) as conn:
        packet_set = build_packet_set(
            conn,
            ledger,
            generated_at=args.generated_at or datetime.now(timezone.utc).isoformat(),
            limit=args.limit,
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(packet_set, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.machine_results_out:
        args.machine_results_out.parent.mkdir(parents=True, exist_ok=True)
        args.machine_results_out.write_text(
            json.dumps(packet_set["machine_results"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "schema": packet_set["schema"],
                "packet_count": len(packet_set["packets"]),
                "machine_result_count": len(packet_set["machine_results"]["results"]),
                "excluded_count": len(packet_set["excluded"]),
                "out": str(args.out),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
