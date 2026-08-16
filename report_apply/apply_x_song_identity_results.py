#!/usr/bin/env python3
"""Validate frozen E2-S answers and apply them through the shared song helper.

The default mode writes only to a copied SQLite database.  Production mode is
guarded by an explicit confirmation, a preflight copy, backup, and RDB audit.
"""
from __future__ import annotations

import argparse
import copy
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import operation_safety.manual_apply_guards as manual_apply_guards
from master_rdb.master_db import (
    MASTER_DB,
    connect_existing,
    file_sha256,
    refresh_manifest_database_state,
    stable_id,
    table_counts,
)
from report_apply.event_report_helpers import upsert_evidence_item, upsert_occurrence_song
from report_apply.rdb_apply_support import audit_db, backup_db, copy_db, write_json
from review_inbox_adapters.x_song_identity_contract import (
    NONE,
    PACKET_VERSION,
    candidate_hashes,
    candidate_ids_sha256,
    observation_sha256,
    occurrence_candidates,
    packet_id,
    song_candidates,
    state_rows,
)


DEFAULT_OBSERVATIONS = Path("data/x_song_observations.json")
DEFAULT_STATE = Path("data/x_song_identity_state.json")
DEFAULT_OUT_DB = Path("data/x_song_identity_apply_dry_run.sqlite")
DEFAULT_REPORT_JSON = Path("data/x_song_identity_apply_report.json")
DEFAULT_REPORT_MD = Path("data/x_song_identity_apply_report.md")
DEFAULT_BACKUP_DIR = Path("data/backups")
DEFAULT_PREFLIGHT_DB = Path("data/x_song_identity_apply_preflight.sqlite")
CONFIRMATION = "APPLY X SONG IDENTITY RESULTS"
ORIGIN_CONTRACT = {
    "events": ("announced", "prediction"),
    "observations": ("observed", "result"),
}


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _observation_index(ledger: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = ledger.get("observations") if isinstance(ledger, dict) else None
    if not isinstance(rows, list):
        return {}
    return {
        row["observation_id"]: row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("observation_id"), str)
    }


def load_packets(paths: list[Path]) -> dict[str, dict[str, Any]]:
    packets: dict[str, dict[str, Any]] = {}
    for path in paths:
        payload = load_json(path, {})
        for packet in payload.get("packets", []) if isinstance(payload, dict) else []:
            if isinstance(packet, dict) and isinstance(packet.get("packet_id"), str):
                packets[packet["packet_id"]] = packet
    return packets


def load_results(paths: list[Path]) -> list[Any]:
    results: list[Any] = []
    for path in paths:
        payload = load_json(path, {})
        rows = payload.get("results") if isinstance(payload, dict) else None
        results.extend(rows if isinstance(rows, list) else [])
    return results


def _packet_problem(packet: dict[str, Any], observation: dict[str, Any]) -> str | None:
    if packet.get("packet_version") != PACKET_VERSION:
        return "packet_version_mismatch"
    if packet.get("observation_id") != observation.get("observation_id"):
        return "observation_id_mismatch"
    if packet.get("observation_sha256") != observation_sha256(observation):
        return "observation_changed"
    if packet.get("observation") != observation:
        return "packet_observation_mismatch"
    song_rows = packet.get("song_candidates")
    occurrence_rows = packet.get("occurrence_candidates")
    if not isinstance(song_rows, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("song_id"), str) or not row.get("song_id")
        for row in song_rows
    ):
        return "song_candidate_packet_tampered"
    if not isinstance(occurrence_rows, list) or any(
        not isinstance(row, dict)
        or not isinstance(row.get("occurrence_id"), str)
        or not row.get("occurrence_id")
        for row in occurrence_rows
    ):
        return "occurrence_candidate_packet_tampered"
    song_ids = [row["song_id"] for row in song_rows]
    occurrence_ids = [row["occurrence_id"] for row in occurrence_rows]
    if len(song_ids) != len(set(song_ids)) or candidate_ids_sha256(song_ids) != packet.get(
        "song_candidate_set_sha256"
    ):
        return "song_candidate_packet_tampered"
    if len(occurrence_ids) != len(set(occurrence_ids)) or candidate_ids_sha256(occurrence_ids) != packet.get(
        "occurrence_candidate_set_sha256"
    ):
        return "occurrence_candidate_packet_tampered"
    expected = packet_id(
        packet["observation_id"],
        packet["song_candidate_set_sha256"],
        packet["occurrence_candidate_set_sha256"],
    )
    return None if packet.get("packet_id") == expected else "packet_id_mismatch"


def _answer_problem(result: dict[str, Any], packet: dict[str, Any]) -> str | None:
    if result.get("observation_id") != packet.get("observation_id"):
        return "result_observation_id_mismatch"
    song_match = result.get("song_match")
    occurrence_match = result.get("occurrence_match")
    if not isinstance(song_match, str) or not song_match:
        return "song_match_missing"
    if not isinstance(occurrence_match, str) or not occurrence_match:
        return "occurrence_match_missing"
    song_ids = {row["song_id"] for row in packet["song_candidates"]}
    occurrence_ids = {row["occurrence_id"] for row in packet["occurrence_candidates"]}
    if song_match != NONE and song_match not in song_ids:
        return "song_match_not_a_candidate"
    if occurrence_match != NONE and occurrence_match not in occurrence_ids:
        return "occurrence_match_not_a_candidate"
    return None


def _effective_url(observation: dict[str, Any]) -> tuple[str, bool]:
    url = str(observation.get("url") or "").strip()
    if url:
        return url, False
    tweet_id = str(observation.get("tweet_id") or "").strip()
    return (f"https://x.com/i/status/{tweet_id}", True) if tweet_id else ("", True)


def _lineage_memo(observation: dict[str, Any], reconstructed_url: bool) -> str:
    memo = (
        "[x_song_identity] "
        f"observation_id={observation.get('observation_id')} "
        f"batch_id={observation.get('batch_id') or ''}"
    )
    if reconstructed_url:
        memo += " url=reconstructed_from_tweet_id"
    return memo


def _state_row(packet: dict[str, Any], observation: dict[str, Any], outcome: str, when: datetime) -> dict[str, Any]:
    row: dict[str, Any] = {
        "issued_at": packet.get("generated_at") or when.isoformat(),
        "batch_id": observation.get("batch_id") or packet.get("judgment_batch_id") or "",
        "applied_at": when.isoformat() if outcome == "applied" else None,
        "outcome": outcome,
    }
    if outcome == "deferred":
        row["next_eligible_at"] = (when + timedelta(days=30)).isoformat()
    return row


def apply_results(
    conn: sqlite3.Connection,
    packets: dict[str, dict[str, Any]],
    results: list[Any],
    observation_ledger: dict[str, Any],
    state: dict[str, Any],
    *,
    when: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply valid siblings and return a state preview; the caller owns commit."""
    when = when or datetime.now(timezone.utc)
    now_text = when.isoformat()
    observations = _observation_index(observation_ledger)
    next_state = copy.deepcopy(state) if isinstance(state, dict) else {}
    next_rows = state_rows(next_state)
    if next_rows is not next_state and "observations" not in next_state:
        next_state = {}
        next_rows = next_state
    report: dict[str, Any] = {
        "processed": 0,
        "applied": 0,
        "deferred": 0,
        "stale": 0,
        "rejected_result": 0,
        "issues": [],
        "entries": [],
    }
    planned: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    seen_packets: set[str] = set()

    # Validate every frozen set against the same DB snapshot before any new
    # song can alter the candidate set for a later result in this batch.
    for index, raw_result in enumerate(results):
        if not isinstance(raw_result, dict):
            report["rejected_result"] += 1
            report["issues"].append({"issue_type": "malformed_result", "index": index})
            continue
        packet = packets.get(raw_result.get("packet_id"))
        if not packet:
            report["rejected_result"] += 1
            report["issues"].append({"issue_type": "packet_missing", "index": index})
            continue
        observation_id = packet.get("observation_id")
        observation = observations.get(observation_id)
        if observation is None:
            problem = "observation_missing"
        elif packet["packet_id"] in seen_packets:
            problem = "duplicate_packet_result"
        else:
            problem = _packet_problem(packet, observation) or _answer_problem(raw_result, packet)
        seen_packets.add(packet["packet_id"])
        if problem:
            report["rejected_result"] += 1
            report["issues"].append(
                {"issue_type": problem, "packet_id": packet["packet_id"], "observation_id": observation_id}
            )
            if observation is not None:
                next_rows[observation_id] = _state_row(packet, observation, "issue", when)
            continue

        current_songs = song_candidates(conn, observation["song_name"])
        current_occurrences = occurrence_candidates(conn, observation.get("event_name"))
        current_hashes = candidate_hashes(current_songs, current_occurrences)
        changed = [
            key
            for key, value in current_hashes.items()
            if value != packet.get(key)
        ]
        if changed:
            report["stale"] += 1
            report["issues"].append(
                {
                    "issue_type": "candidate_set_stale",
                    "packet_id": packet["packet_id"],
                    "observation_id": observation_id,
                    "changed": changed,
                }
            )
            next_rows[observation_id] = _state_row(packet, observation, "stale", when)
            continue
        if raw_result["occurrence_match"] == NONE:
            report["processed"] += 1
            report["deferred"] += 1
            next_rows[observation_id] = _state_row(packet, observation, "deferred", when)
            report["entries"].append(
                {"observation_id": observation_id, "outcome": "deferred", "reason": raw_result.get("reason")}
            )
            continue
        if observation.get("origin") not in ORIGIN_CONTRACT:
            report["rejected_result"] += 1
            report["issues"].append(
                {"issue_type": "observation_origin_invalid", "observation_id": observation_id}
            )
            next_rows[observation_id] = _state_row(packet, observation, "issue", when)
            continue
        source_url, reconstructed = _effective_url(observation)
        if not source_url:
            report["rejected_result"] += 1
            report["issues"].append(
                {"issue_type": "source_url_unrecoverable", "observation_id": observation_id}
            )
            next_rows[observation_id] = _state_row(packet, observation, "issue", when)
            continue
        planned.append((packet, raw_result, {"observation": observation, "source_url": source_url,
                                             "reconstructed": reconstructed}))

    for packet, result, context in planned:
        observation = context["observation"]
        evidence_status, role = ORIGIN_CONTRACT[observation["origin"]]
        selected_song_id = None if result["song_match"] == NONE else result["song_match"]
        if selected_song_id is None:
            song_title = observation["song_name"]
        else:
            row = conn.execute(
                "SELECT canonical_title FROM songs WHERE song_id = ?", (selected_song_id,)
            ).fetchone()
            if row is None:
                # This can only happen through concurrent mutation after the
                # frozen-set check.  SQLite will keep the transaction safe.
                report["rejected_result"] += 1
                report["issues"].append(
                    {"issue_type": "selected_song_disappeared", "observation_id": observation["observation_id"]}
                )
                next_rows[observation["observation_id"]] = _state_row(packet, observation, "issue", when)
                continue
            song_title = row[0]

        evidence_id = stable_id("ev", "x_song", observation["observation_id"])
        upsert_evidence_item(
            conn,
            evidence_id,
            platform="x",
            evidence_type=evidence_status,
            source_key="x_song_observation",
            source_id=observation.get("tweet_id") or "",
            account_key=observation.get("account") or "",
            text_excerpt=str(observation.get("text") or "")[:280],
            url=context["source_url"],
            published_at=observation.get("posted_at") or "",
            observed_at=now_text,
            raw_status=role,
            raw_json_extra={
                key: observation.get(key)
                for key in ("observation_id", "batch_id", "song_name", "event_name", "origin", "score")
            },
            now=now_text,
        )
        applied = upsert_occurrence_song(
            conn,
            result["occurrence_match"],
            song_title,
            evidence_id,
            role=role,
            evidence_status=evidence_status,
            basis_key="x_song_identity",
            evidence_note="X投稿の曲名観測をLLM同一性判定で開催回へ接続。",
            song_id=selected_song_id,
            origin="observed_x_post",
            song_source_url=context["source_url"],
            song_memo=_lineage_memo(observation, context["reconstructed"]),
            uncertain=False,
            now=now_text,
        )
        report["processed"] += 1
        report["applied"] += 1
        next_rows[observation["observation_id"]] = _state_row(packet, observation, "applied", when)
        report["entries"].append(
            {
                "observation_id": observation["observation_id"],
                "outcome": "applied",
                "evidence_id": evidence_id,
                **applied,
            }
        )

    foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_keys:
        report["issues"].append(
            {"issue_type": "foreign_key_check_failed", "severity": "high", "count": len(foreign_keys)}
        )
    return report, next_state


def _render_markdown(result: dict[str, Any]) -> str:
    report = result["result"]
    lines = [
        "# X song identity apply report",
        "",
        f"- mode: {result['mode']}",
        f"- applied: {report['applied']}",
        f"- deferred: {report['deferred']}",
        f"- stale: {report['stale']}",
        f"- rejected_result: {report['rejected_result']}",
        f"- master_checksum_unchanged: {result['master_checksum_unchanged']}",
        f"- state_write: {result['state_write']}",
        "",
        "## Issues",
        "",
    ]
    lines.extend(f"- {json.dumps(issue, ensure_ascii=False, sort_keys=True)}" for issue in report["issues"])
    return "\n".join(lines) + "\n"


def _apply_once(
    db_path: Path,
    packets: dict[str, dict[str, Any]],
    results: list[Any],
    observations: dict[str, Any],
    state: dict[str, Any],
    when: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    with closing(connect_existing(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        report, next_state = apply_results(conn, packets, results, observations, state, when=when)
        if any(issue.get("severity") == "high" for issue in report["issues"]):
            conn.rollback()
            report["rolled_back"] = True
        else:
            conn.commit()
            report["rolled_back"] = False
        report["table_counts"] = table_counts(conn)
    return report, next_state


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.apply:
        manual_apply_guards.require_confirmation(
            True, args.confirm, CONFIRMATION, "apply_x_song_identity_results.py --apply"
        )
    when = datetime.now(timezone.utc)
    master_before = file_sha256(args.db)
    packets = load_packets(args.packets)
    results = load_results(args.results)
    observations = load_json(args.observations, {"observations": []})
    state = load_json(args.state, {})
    backup_path = ""

    if args.apply:
        copy_db(args.db, args.preflight_db)
        preflight_report, _ = _apply_once(
            args.preflight_db, packets, results, observations, state, when
        )
        preflight_audit = audit_db(
            args.preflight_db,
            args.preflight_db.with_suffix(".audit.json"),
            args.preflight_db.with_suffix(".audit.md"),
        )
        if preflight_report["rolled_back"] or preflight_audit["issues_by_severity"].get("high"):
            raise ValueError("preflight refused high-severity issues")
        backup_path = str(backup_db(args.db, when.isoformat(), args.backup_dir))
        target_db = args.db
    else:
        if args.out_db.resolve() == args.db.resolve():
            raise ValueError("dry-run --out-db must differ from --db")
        copy_db(args.db, args.out_db)
        target_db = args.out_db

    report, next_state = _apply_once(target_db, packets, results, observations, state, when)
    audit = audit_db(target_db, args.report_json.with_suffix(".audit.json"), args.report_md.with_suffix(".audit.md"))
    if args.apply and audit["issues_by_severity"].get("high"):
        raise ValueError(f"post-apply audit has high issues: {audit['issues_by_severity']}")
    state_write = bool(args.apply and not report["rolled_back"])
    if state_write:
        write_json(args.state, next_state)
        refresh_manifest_database_state(args.db, updated_at=when.isoformat())
    master_after = file_sha256(args.db)
    output = {
        "generated_at": when.isoformat(),
        "mode": "apply" if args.apply else "dry_run",
        "target_db": str(target_db),
        "backup_db": backup_path,
        "master_checksum_before": master_before,
        "master_checksum_after": master_after,
        "master_checksum_unchanged": master_before == master_after,
        "state_write": state_write,
        "state_preview": next_state,
        "result": report,
        "audit": {
            "issue_count": audit["issue_count"],
            "issues_by_severity": audit["issues_by_severity"],
            "issues_by_type": audit["issues_by_type"],
        },
    }
    write_json(args.report_json, output)
    args.report_md.parent.mkdir(parents=True, exist_ok=True)
    args.report_md.write_text(_render_markdown(output), encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=MASTER_DB)
    parser.add_argument("--observations", type=Path, default=DEFAULT_OBSERVATIONS)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--packets", type=Path, action="append", required=True)
    parser.add_argument("--results", type=Path, action="append", required=True)
    parser.add_argument("--out-db", type=Path, default=DEFAULT_OUT_DB)
    parser.add_argument("--report-json", type=Path, default=DEFAULT_REPORT_JSON)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD)
    parser.add_argument("--preflight-db", type=Path, default=DEFAULT_PREFLIGHT_DB)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    output = run(args)
    print(json.dumps(output, ensure_ascii=False))
    return 1 if output["result"]["rolled_back"] or output["audit"]["issues_by_severity"].get("high") else 0


if __name__ == "__main__":
    raise SystemExit(main())
