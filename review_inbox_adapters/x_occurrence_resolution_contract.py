"""Frozen occurrence-identity contract for E2-S v2 X song claims."""

from __future__ import annotations

import json
from difflib import SequenceMatcher

from master_rdb.master_db import normalize_text, stable_id
from review_inbox_adapters.local_judgment_contract import IDENTITY_MATCH_NONE
from review_inbox_adapters.x_song_resolution_contract import (
    canonical_json,
    eligible_observation,
    observation_index,
    sha256_json,
)


def occurrence_snapshot(conn) -> list[dict]:
    aliases: dict[str, list[str]] = {}
    for series_id, alias in conn.execute(
        "SELECT series_id, alias FROM event_series_aliases ORDER BY series_id, normalized_alias"
    ):
        aliases.setdefault(series_id, []).append(alias)
    rows = conn.execute(
        """
        SELECT o.occurrence_id, o.origin, o.series_id, o.event_year,
               o.occurrence_sequence, o.display_name, o.venue_id,
               o.date_start, o.date_end, o.date_status, o.lifecycle_status,
               o.current_event_state, o.confidence,
               s.canonical_name, s.normalized_name, s.status,
               v.canonical_name, v.area, v.address, v.review_status
        FROM event_occurrences o
        JOIN event_series s ON s.series_id = o.series_id
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE o.lifecycle_status != 'merged'
        ORDER BY o.occurrence_id
        """
    )
    return [
        {
            "occurrence_id": row[0],
            "origin": row[1],
            "series_id": row[2],
            "event_year": row[3],
            "occurrence_sequence": row[4],
            "display_name": row[5],
            "venue_id": row[6],
            "date_start": row[7],
            "date_end": row[8],
            "date_status": row[9],
            "lifecycle_status": row[10],
            "current_event_state": row[11],
            "confidence": row[12],
            "series_name": row[13],
            "series_normalized_name": row[14],
            "series_status": row[15],
            "series_aliases": aliases.get(row[2], []),
            "venue_name": row[16],
            "venue_area": row[17],
            "venue_address": row[18],
            "venue_review_status": row[19],
        }
        for row in rows
    ]


def _score(query: str, candidate: str) -> float:
    if not query or not candidate:
        return 0.0
    if query == candidate:
        return 1.0
    return SequenceMatcher(None, query, candidate).ratio()


def direct_candidates(observation: dict, snapshot: list[dict], limit: int = 20) -> list[dict]:
    event_query = normalize_text(observation.get("event_name"))
    venue_query = normalize_text(observation.get("event_venue_name"))
    year = None
    date_start = observation.get("event_date_start")
    if isinstance(date_start, str) and len(date_start) >= 4 and date_start[:4].isdigit():
        year = int(date_start[:4])
    scored = []
    for row in snapshot:
        names = [row["display_name"], row["series_name"], *row["series_aliases"]]
        name_score = max(_score(event_query, normalize_text(value)) for value in names if value)
        venue_score = _score(venue_query, normalize_text(row.get("venue_name"))) if venue_query else 0.0
        year_score = 1.0 if year is not None and row["event_year"] == year else 0.0
        total = round(name_score * 0.7 + venue_score * 0.2 + year_score * 0.1, 6)
        scored.append({**row, "match_score": total})
    return sorted(scored, key=lambda row: (-row["match_score"], row["occurrence_id"]))[:limit]


def _json(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _identity_of(conn, decision: dict) -> tuple[dict | None, str | None]:
    payload = _json(decision.get("payload_json"), {})
    required = {"occurrence_match", "series_match", "venue_match"}
    if required <= set(payload):
        return payload, decision["decision_id"]
    prior = decision.get("prior_agent_attempt_id")
    if not prior:
        return None, None
    row = conn.execute(
        "SELECT decision_id, payload_json FROM canonical_decision_ledger WHERE decision_id=?",
        (prior,),
    ).fetchone()
    if not row:
        return None, None
    prior_payload = _json(row[1], {})
    return (prior_payload, row[0]) if required <= set(prior_payload) else (None, None)


def resolve_event_dependency(conn, dependency_key: str, snapshot: list[dict]) -> dict:
    conn.row_factory = __import__("sqlite3").Row
    decisions = conn.execute(
        """
        WITH latest_inbox AS (
          SELECT inbox_id
          FROM review_inbox_items
          WHERE revision_family_key = ?
          ORDER BY revision DESC, updated_at DESC, inbox_id DESC
          LIMIT 1
        )
        SELECT d.*
        FROM canonical_decision_ledger d
        JOIN latest_inbox i ON i.inbox_id = d.inbox_id
        WHERE d.domain = 'event'
          AND d.action = 'accept'
          AND d.queue_state_after = 'closed'
        ORDER BY d.decided_at DESC, d.decision_id DESC
        """,
        (dependency_key,),
    ).fetchall()
    if not decisions:
        return {"action": "dependency_pending", "reason_code": "event_decision_pending"}
    decision = dict(decisions[0])
    identity, identity_decision_id = _identity_of(conn, decision)
    if identity is None:
        return {
            "action": "dependency_pending",
            "reason_code": "event_identity_missing",
            "dependency_decision_id": decision["decision_id"],
        }
    occurrence_ids = {row["occurrence_id"] for row in snapshot}
    occurrence_match = identity["occurrence_match"]
    if occurrence_match != IDENTITY_MATCH_NONE:
        if occurrence_match not in occurrence_ids:
            return {
                "action": "dependency_pending",
                "reason_code": "event_occurrence_unavailable",
                "dependency_decision_id": identity_decision_id,
            }
        return {
            "action": "match_occurrence",
            "selected_occurrence_id": occurrence_match,
            "reason_code": "event_identity_match",
            "dependency_decision_id": identity_decision_id,
        }

    request_id = stable_id("chrq", decision["decision_id"])
    evidence_ids = []
    for evidence_id, raw_json in conn.execute("SELECT evidence_id, raw_json FROM evidence_items"):
        raw = _json(raw_json, {})
        if raw.get("request_id") == request_id:
            evidence_ids.append(evidence_id)
    linked = sorted(
        {
            row[0]
            for evidence_id in evidence_ids
            for row in conn.execute(
                """
                SELECT occurrence_id FROM occurrence_evidence_links
                WHERE evidence_id=? AND link_status='accepted'
                """,
                (evidence_id,),
            )
            if row[0] in occurrence_ids
        }
    )
    if len(linked) == 1:
        return {
            "action": "match_occurrence",
            "selected_occurrence_id": linked[0],
            "reason_code": "event_change_request_applied",
            "dependency_decision_id": decision["decision_id"],
        }
    return {
        "action": "dependency_pending",
        "reason_code": "event_change_request_pending" if not linked else "event_change_request_ambiguous",
        "dependency_decision_id": decision["decision_id"],
    }


def _packet_payload(packet: dict) -> dict:
    return {key: value for key, value in packet.items() if key not in {"packet_id", "packet_sha256"}}


def _finish_packet(packet: dict) -> dict:
    packet_sha = sha256_json(_packet_payload(packet))
    return {**packet, "packet_sha256": packet_sha, "packet_id": stable_id("xopkt2", packet_sha)}


def build_packet_set(conn, ledger: dict, *, generated_at: str, limit: int = 20) -> dict:
    snapshot = occurrence_snapshot(conn)
    snapshot_sha = sha256_json(snapshot)
    packets = []
    machine_results = []
    excluded = []
    for observation_id, row in sorted(observation_index(ledger).items()):
        eligible, reason = eligible_observation(row)
        if not eligible:
            excluded.append({"observation_id": observation_id, "reason": reason})
            continue
        dependency_key = row.get("event_dependency_key")
        if dependency_key:
            resolution_source = "report_dependency"
            dependency = resolve_event_dependency(conn, dependency_key, snapshot)
            selected = dependency.get("selected_occurrence_id")
            candidates = [value for value in snapshot if value["occurrence_id"] == selected]
            allowed = [dependency["action"]]
        else:
            if not (
                row.get("event_context_valid") is True
                and row.get("event_name_in_text") is True
                and normalize_text(row.get("event_name"))
                and (row.get("event_date_start") or normalize_text(row.get("event_venue_name")))
            ):
                excluded.append({"observation_id": observation_id, "reason": "insufficient_event_context"})
                continue
            resolution_source = "direct_candidates"
            dependency = {}
            candidates = direct_candidates(row, snapshot, limit=limit)
            allowed = ["match_occurrence", "unresolved"]
        packet = _finish_packet(
            {
                "schema": "x_occurrence_resolution_packet_v2",
                "resolution_source": resolution_source,
                "observation_id": observation_id,
                "observation_sha256": sha256_json(row),
                "observation": row,
                "event_dependency_key": dependency_key,
                "dependency_decision_id": dependency.get("dependency_decision_id"),
                "candidate_rows": candidates,
                "candidate_set_sha256": sha256_json(candidates),
                "occurrence_snapshot_sha256": snapshot_sha,
                "allowed_actions": allowed,
            }
        )
        packets.append(packet)
        if resolution_source == "report_dependency":
            machine_results.append(
                {
                    "packet_id": packet["packet_id"],
                    "action": dependency["action"],
                    "selected_occurrence_id": dependency.get("selected_occurrence_id"),
                    "reason_code": dependency["reason_code"],
                }
            )
    return {
        "schema": "x_occurrence_resolution_packet_set_v2",
        "generated_at": generated_at,
        "occurrence_snapshot": snapshot,
        "occurrence_snapshot_sha256": snapshot_sha,
        "packets": packets,
        "machine_results": {
            "schema": "x_occurrence_resolution_results_v2",
            "results": machine_results,
        },
        "excluded": excluded,
    }


def validate_packet_set(packet_set: dict) -> None:
    if packet_set.get("schema") != "x_occurrence_resolution_packet_set_v2":
        raise ValueError("unsupported occurrence packet set schema")
    snapshot = packet_set.get("occurrence_snapshot")
    if not isinstance(snapshot, list) or sha256_json(snapshot) != packet_set.get("occurrence_snapshot_sha256"):
        raise ValueError("occurrence snapshot hash mismatch")
    seen = set()
    for packet in packet_set.get("packets", []):
        packet_id = packet.get("packet_id") if isinstance(packet, dict) else None
        if packet_id in seen:
            raise ValueError(f"duplicate occurrence packet_id: {packet_id}")
        seen.add(packet_id)
        expected = sha256_json(_packet_payload(packet))
        if expected != packet.get("packet_sha256") or stable_id("xopkt2", expected) != packet_id:
            raise ValueError(f"occurrence packet hash mismatch: {packet_id}")
        if sha256_json(packet.get("candidate_rows")) != packet.get("candidate_set_sha256"):
            raise ValueError(f"occurrence candidate hash mismatch: {packet_id}")
        if packet.get("occurrence_snapshot_sha256") != packet_set["occurrence_snapshot_sha256"]:
            raise ValueError(f"occurrence snapshot mismatch: {packet_id}")


def apply_results(
    conn, ledger: dict, packet_set: dict, results_payload: dict, *,
    actor_id: str, model_id: str, prompt_sha256: str, decided_at: str,
    commit: bool = True,
) -> dict:
    if not actor_id or not model_id:
        raise ValueError("local actor_id and model_id are required")
    if len(prompt_sha256) != 64 or any(char not in "0123456789abcdef" for char in prompt_sha256):
        raise ValueError("local prompt_sha256 must be 64 lowercase hex characters")
    validate_packet_set(packet_set)
    if results_payload.get("schema") != "x_occurrence_resolution_results_v2":
        raise ValueError("unsupported occurrence result schema")
    packets = {row["packet_id"]: row for row in packet_set["packets"]}
    results = results_payload.get("results")
    if not isinstance(results, list):
        raise ValueError("occurrence results must be a list")
    seen = set()
    applied = no_op = 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        observations = observation_index(ledger)
        current_snapshot = occurrence_snapshot(conn)
        if sha256_json(current_snapshot) != packet_set["occurrence_snapshot_sha256"]:
            raise ValueError("stale occurrence snapshot")
        for result in results:
            packet_id = result.get("packet_id") if isinstance(result, dict) else None
            if packet_id in seen:
                raise ValueError(f"duplicate occurrence result packet_id: {packet_id}")
            seen.add(packet_id)
            packet = packets.get(packet_id)
            if packet is None:
                raise ValueError(f"unknown occurrence packet_id: {packet_id}")
            observation = observations.get(packet["observation_id"])
            if observation is None or sha256_json(observation) != packet["observation_sha256"]:
                raise ValueError(f"stale occurrence observation: {packet['observation_id']}")
            action = result.get("action")
            if action not in packet["allowed_actions"]:
                raise ValueError(f"occurrence action not allowed: {action}")
            selected = result.get("selected_occurrence_id")
            if action == "match_occurrence":
                if selected not in {row["occurrence_id"] for row in packet["candidate_rows"]}:
                    raise ValueError("selected occurrence was not in the frozen candidate set")
            elif selected is not None:
                raise ValueError("selected_occurrence_id is only allowed for match_occurrence")
            if packet["resolution_source"] == "report_dependency":
                current = resolve_event_dependency(conn, packet["event_dependency_key"], current_snapshot)
                if (action, selected) != (current["action"], current.get("selected_occurrence_id")):
                    raise ValueError("event dependency changed after packet build")

            decision_id = stable_id("xodec2", packet_id, action, selected or "")
            existing = conn.execute(
                "SELECT decision_id, action, selected_occurrence_id FROM x_occurrence_resolution_decisions WHERE packet_id=?",
                (packet_id,),
            ).fetchone()
            if existing:
                if tuple(existing) != (decision_id, action, selected):
                    raise ValueError(f"occurrence packet already has another decision: {packet_id}")
                no_op += 1
                continue
            active = conn.execute(
                "SELECT decision_id FROM x_occurrence_resolution_decisions WHERE observation_id=? AND status='active'",
                (packet["observation_id"],),
            ).fetchone()
            supersedes = active[0] if active else None
            if supersedes:
                conn.execute(
                    "UPDATE x_occurrence_resolution_decisions SET status='superseded' WHERE decision_id=?",
                    (supersedes,),
                )
            conn.execute(
                """
                INSERT INTO x_occurrence_resolution_decisions (
                  decision_id, observation_id, observation_sha256, packet_id,
                  packet_sha256, resolution_source, action, selected_occurrence_id,
                  event_dependency_key, dependency_decision_id,
                  candidate_rows_json, candidate_set_sha256,
                  occurrence_snapshot_json, occurrence_snapshot_sha256,
                  reason_code, reason_detail, actor_id, model_id, prompt_sha256,
                  supersedes_decision_id, decided_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id, packet["observation_id"], packet["observation_sha256"], packet_id,
                    packet["packet_sha256"], packet["resolution_source"], action, selected,
                    packet["event_dependency_key"], packet["dependency_decision_id"],
                    canonical_json(packet["candidate_rows"]), packet["candidate_set_sha256"],
                    canonical_json(packet_set["occurrence_snapshot"]), packet_set["occurrence_snapshot_sha256"],
                    str(result.get("reason_code") or action), str(result.get("reason_detail") or "") or None,
                    actor_id, model_id, prompt_sha256,
                    supersedes, decided_at, decided_at,
                ),
            )
            applied += 1
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"applied": applied, "no_op": no_op, "result_count": len(results)}
