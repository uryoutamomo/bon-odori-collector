#!/usr/bin/env python3
"""Build deterministic E2-S packets from X song observations."""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from master_rdb.master_db import MASTER_DB, connect_existing
from report_apply.rdb_apply_support import write_json
from review_inbox_adapters.x_song_identity_contract import (
    PACKET_VERSION,
    candidate_hashes,
    is_eligible,
    observation_sha256,
    occurrence_candidates,
    packet_id,
    song_candidates,
    state_rows,
)


DEFAULT_OBSERVATIONS = Path("data/x_song_observations.json")
DEFAULT_STATE = Path("data/x_song_identity_state.json")
DEFAULT_OUT_DIR = Path("data/x_song_identity_packets")
DEFAULT_REPORT = Path("data/x_song_identity_packets_report.json")


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _observation_rows(ledger: dict[str, Any]) -> list[Any]:
    rows = ledger.get("observations") if isinstance(ledger, dict) else None
    return rows if isinstance(rows, list) else []


def build(
    conn: sqlite3.Connection,
    observation_ledger: dict[str, Any],
    state: dict[str, Any],
    *,
    when: datetime | None = None,
    max_packets: int = 100,
) -> dict[str, Any]:
    """Return packets and issues without mutating the DB or state sidecar."""
    when = when or datetime.now(timezone.utc)
    rows = state_rows(state)
    packets: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    seen: set[str] = set()

    observations = _observation_rows(observation_ledger)
    for index, observation in enumerate(observations):
        if not isinstance(observation, dict):
            issues.append({"issue_type": "malformed_observation", "index": index})
            continue
        observation_id = observation.get("observation_id")
        song_name = observation.get("song_name")
        if not isinstance(observation_id, str) or not observation_id:
            issues.append({"issue_type": "observation_id_missing", "index": index})
            continue
        if observation_id in seen:
            issues.append({"issue_type": "duplicate_observation_id", "observation_id": observation_id})
            continue
        seen.add(observation_id)
        if not isinstance(song_name, str) or not song_name.strip():
            issues.append({"issue_type": "song_name_missing", "observation_id": observation_id})
            continue
        if not is_eligible(rows.get(observation_id), when):
            excluded.append({"observation_id": observation_id, "reason": "not_eligible"})
            continue
        if len(packets) >= max_packets:
            excluded.append({"observation_id": observation_id, "reason": "packet_limit"})
            continue

        songs = song_candidates(conn, song_name)
        occurrences = occurrence_candidates(conn, observation.get("event_name"))
        hashes = candidate_hashes(songs, occurrences)
        frozen_packet_id = packet_id(
            observation_id,
            hashes["song_candidate_set_sha256"],
            hashes["occurrence_candidate_set_sha256"],
        )
        packets.append(
            {
                "packet_version": PACKET_VERSION,
                "packet_id": frozen_packet_id,
                "observation_id": observation_id,
                "generated_at": when.isoformat(),
                "observation_sha256": observation_sha256(observation),
                "observation": observation,
                "song_candidates": songs,
                "occurrence_candidates": occurrences,
                **hashes,
                "answer_contract": {
                    "packet_id": frozen_packet_id,
                    "song_match": "one shown song_id or 'none'",
                    "occurrence_match": "one shown occurrence_id or 'none'",
                    "reason": "short identity rationale",
                },
            }
        )
    return {
        "generated_at": when.isoformat(),
        "observation_count": len(observations),
        "generated": len(packets),
        "packets": packets,
        "issues": issues,
        "excluded": excluded,
    }


def write_batches(
    packets: list[dict[str, Any]], out_dir: Path, when: datetime, *, batch_size: int = 20
) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []
    for start in range(0, len(packets), batch_size):
        number = start // batch_size + 1
        batch_id = f"x_song_identity_{when.strftime('%Y%m%d')}_{number:02d}"
        batch_packets = []
        for packet in packets[start : start + batch_size]:
            batch_packets.append({**packet, "judgment_batch_id": batch_id})
        path = out_dir / f"batch_{when.strftime('%Y%m%d')}_{number:02d}.json"
        write_json(path, {"batch_id": batch_id, "packets": batch_packets})
        outputs.append(str(path))
    return outputs


def run(args: argparse.Namespace) -> dict[str, Any]:
    when = datetime.now(timezone.utc)
    observations = load_json(args.observations, {"observations": []})
    state = load_json(args.state, {})
    with connect_existing(args.db) as conn:
        conn.row_factory = sqlite3.Row
        report = build(conn, observations, state, when=when, max_packets=args.max_packets)
    outputs = write_batches(report.pop("packets"), args.out_dir, when, batch_size=args.batch_size)
    report["batches"] = outputs
    report["state_write"] = False
    write_json(args.report_json, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=MASTER_DB)
    parser.add_argument("--observations", type=Path, default=DEFAULT_OBSERVATIONS)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-json", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--max-packets", type=int, default=100)
    args = parser.parse_args()
    report = run(args)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
