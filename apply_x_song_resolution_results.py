#!/usr/bin/env python3
"""Validate E2-S v2 song decisions and append them to the identity ledger."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from master_rdb.master_db import MASTER_DB
from report_apply.x_song_apply_safety import run_guarded
from review_inbox_adapters.x_song_resolution_contract import (
    apply_results,
    load_observation_ledger,
    load_packet_sets,
)


CONFIRM_TEXT = "APPLY X SONG RESOLUTIONS V2"


def run(
    *,
    db_path,
    observation_path,
    packet_paths,
    result_path,
    actor_id,
    model_id,
    prompt_sha256,
    decided_at,
    execute=False,
    confirm=None,
):
    if execute and confirm != CONFIRM_TEXT:
        raise ValueError(f"--execute requires --confirm {CONFIRM_TEXT!r}")
    ledger = load_observation_ledger(observation_path)
    _packet_sets, entries = load_packet_sets(packet_paths)
    results = json.loads(Path(result_path).read_text(encoding="utf-8"))

    guarded = run_guarded(
        db_path=db_path,
        execute=execute,
        timestamp=decided_at,
        temp_prefix="x-song-resolution-v2-",
        operation=lambda conn: apply_results(
            conn,
            ledger,
            entries,
            results,
            actor_id=actor_id,
            model_id=model_id,
            prompt_sha256=prompt_sha256,
            decided_at=decided_at,
            commit=False,
        ),
    )
    report = guarded["report"]
    return {
        "schema": "x_song_resolution_apply_report_v2",
        "mode": "execute" if execute else "dry_run",
        **report,
        "integrity_check": guarded["integrity_check"],
        "foreign_key_issue_count": guarded["foreign_key_issue_count"],
        "backup_db": guarded["backup_db"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=MASTER_DB)
    parser.add_argument("--observations", type=Path, default=Path("data/x_song_observations.json"))
    parser.add_argument("--packets", type=Path, action="append", required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--prompt-sha256", required=True)
    parser.add_argument("--decided-at")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm")
    args = parser.parse_args(argv)
    report = run(
        db_path=args.db,
        observation_path=args.observations,
        packet_paths=args.packets,
        result_path=args.results,
        actor_id=args.actor_id,
        model_id=args.model_id,
        prompt_sha256=args.prompt_sha256,
        decided_at=args.decided_at or datetime.now(timezone.utc).isoformat(),
        execute=args.execute,
        confirm=args.confirm,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
