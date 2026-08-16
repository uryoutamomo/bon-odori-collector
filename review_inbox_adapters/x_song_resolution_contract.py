"""Frozen-packet contract for E2-S v2 X-song identity decisions.

This module is deliberately read/write split: packet builders only read the
observation ledger and master catalog; result application only appends to the
identity decision ledger. No domain fact is materialized here.
"""

from __future__ import annotations

import hashlib
import json
from difflib import SequenceMatcher
from pathlib import Path

from master_rdb.master_db import json_text, normalize_text, stable_id
from song_processing.song_catalog import _review_state_for_status


RETRIEVAL_ACTIONS = ("match_song", "candidate_missing", "unresolved")
NOVELTY_ACTIONS = ("match_song", "new_song", "unresolved")


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_observation_ledger(path: Path) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("observations"), list):
        raise ValueError("song observation ledger must contain an observations list")
    return payload


def observation_index(ledger: dict) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for value in ledger.get("observations", []):
        if not isinstance(value, dict) or not isinstance(value.get("observation_id"), str):
            raise ValueError("malformed song observation")
        observation_id = value["observation_id"]
        if observation_id in rows:
            raise ValueError(f"duplicate observation_id: {observation_id}")
        rows[observation_id] = value
    return rows


def eligible_observation(row: dict) -> tuple[bool, str]:
    if row.get("observation_schema_version") != 2:
        return False, "legacy_observation"
    if row.get("claim_type") not in {"announced", "observed"}:
        return False, "non_fact_claim"
    if row.get("claim_type_conflict") is not False:
        return False, "claim_type_conflict"
    if not normalize_text(row.get("event_name")) or row.get("event_name_in_text") is not True:
        return False, "insufficient_event_identity"
    if not row.get("url") and not row.get("tweet_id"):
        return False, "missing_source_identity"
    song_name = row.get("song_name")
    quote = row.get("evidence_quote")
    if not isinstance(song_name, str) or not normalize_text(song_name):
        return False, "missing_song_name"
    if not isinstance(quote, str) or normalize_text(song_name) not in normalize_text(quote):
        return False, "invalid_evidence_quote"
    return True, "eligible"


def catalog_snapshot(conn) -> list[dict]:
    aliases: dict[str, list[dict]] = {}
    for row in conn.execute(
        """
        SELECT song_id, alias, normalized_alias, source, confidence
        FROM song_aliases
        ORDER BY song_id, normalized_alias, alias, source
        """
    ):
        aliases.setdefault(row[0], []).append(
            {
                "alias": row[1],
                "normalized_alias": row[2],
                "source": row[3],
                "confidence": row[4],
            }
        )
    return [
        {
            "song_id": row[0],
            "canonical_title": row[1],
            "normalized_title": row[2],
            "status": row[3],
            "review_state": _review_state_for_status(row[3]).value,
            "aliases": aliases.get(row[0], []),
        }
        for row in conn.execute(
            """
            SELECT song_id, canonical_title, normalized_title, status
            FROM songs ORDER BY song_id
            """
        )
    ]


def _match_score(query: str, candidate: str) -> float:
    if not query or not candidate:
        return 0.0
    if query == candidate:
        return 1.0
    ratio = SequenceMatcher(None, query, candidate).ratio()
    if query in candidate or candidate in query:
        ratio = max(ratio, 0.82 * min(len(query), len(candidate)) / max(len(query), len(candidate)))
    return round(ratio, 6)


def retrieval_candidates(song_name: str, snapshot: list[dict], limit: int = 20) -> list[dict]:
    query = normalize_text(song_name)
    scored = []
    for song in snapshot:
        matches = [
            (song["canonical_title"], song["normalized_title"], "canonical")
        ] + [
            (alias["alias"], alias["normalized_alias"], "alias")
            for alias in song["aliases"]
        ]
        matched_text, _normalized, matched_by = max(
            matches,
            key=lambda value: (
                _match_score(query, value[1]),
                value[2] == "canonical",
                value[0],
            ),
        )
        score = _match_score(query, normalize_text(matched_text))
        scored.append(
            {
                **song,
                "matched_by": matched_by,
                "matched_text": matched_text,
                "match_score": score,
            }
        )
    return sorted(
        scored,
        key=lambda row: (-row["match_score"], row["song_id"]),
    )[:limit]


def _packet_payload(packet: dict) -> dict:
    return {key: value for key, value in packet.items() if key not in {"packet_id", "packet_sha256"}}


def _finish_packet(packet: dict) -> dict:
    packet_sha256 = sha256_json(_packet_payload(packet))
    return {
        **packet,
        "packet_sha256": packet_sha256,
        "packet_id": stable_id("xspkt2", packet_sha256),
    }


def _packet_already_decided(conn, packet_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM x_song_resolution_decisions WHERE packet_id=?",
        (packet_id,),
    ).fetchone() is not None


def _plain_song_row(row: dict) -> dict:
    return {
        key: value
        for key, value in row.items()
        if key not in {"matched_by", "matched_text", "match_score"}
    }


def _selected_song_is_current(decision, snapshot: list[dict]) -> bool:
    if not decision["selected_song_id"]:
        return False
    try:
        frozen_rows = json.loads(decision["candidate_rows_json"])
    except (TypeError, ValueError):
        return False
    frozen = next(
        (row for row in frozen_rows if row.get("song_id") == decision["selected_song_id"]),
        None,
    )
    current = next(
        (row for row in snapshot if row.get("song_id") == decision["selected_song_id"]),
        None,
    )
    return bool(frozen and current and _plain_song_row(frozen) == current)


def build_packet_set(conn, ledger: dict, *, phase: str, generated_at: str, limit: int = 20) -> dict:
    if phase not in {"retrieval", "novelty"}:
        raise ValueError("phase must be retrieval or novelty")
    snapshot = catalog_snapshot(conn)
    snapshot_sha = sha256_json(snapshot)
    packets = []
    excluded = []
    for observation_id, row in sorted(observation_index(ledger).items()):
        eligible, reason = eligible_observation(row)
        if not eligible:
            excluded.append({"observation_id": observation_id, "reason": reason})
            continue
        observation_sha = sha256_json(row)
        if conn.execute(
            "SELECT 1 FROM x_song_materializations WHERE observation_id=? AND status='active'",
            (observation_id,),
        ).fetchone():
            excluded.append({"observation_id": observation_id, "reason": "already_materialized"})
            continue

        conn.row_factory = __import__("sqlite3").Row
        active_phase = conn.execute(
            """
            SELECT * FROM x_song_resolution_decisions
            WHERE observation_id=? AND phase=? AND status='active'
            """,
            (observation_id, phase),
        ).fetchone()
        active_phase = dict(active_phase) if active_phase else None
        if active_phase and active_phase["observation_sha256"] == observation_sha:
            terminal = (
                active_phase["action"] == "candidate_missing"
                or (
                    active_phase["action"] == "match_song"
                    and _selected_song_is_current(active_phase, snapshot)
                )
                or (
                    active_phase["action"] == "new_song"
                    and active_phase["catalog_snapshot_sha256"] == snapshot_sha
                )
            )
            if terminal:
                excluded.append(
                    {"observation_id": observation_id, "reason": "identity_already_resolved"}
                )
                continue

        dependency = None
        if phase == "novelty":
            dependency_row = conn.execute(
                """
                SELECT decision_id, action
                FROM x_song_resolution_decisions
                WHERE observation_id=? AND phase='retrieval' AND status='active'
                """,
                (observation_id,),
            ).fetchone()
            if dependency_row is None or dependency_row[1] != "candidate_missing":
                excluded.append({"observation_id": observation_id, "reason": "retrieval_not_candidate_missing"})
                continue
            dependency = dependency_row[0]

        candidates = retrieval_candidates(row["song_name"], snapshot, limit=limit)
        if phase == "novelty":
            # Novelty adjudication must see the entire frozen catalog, not a
            # second small search result whose miss could be mistaken for proof.
            candidates = snapshot
        packet = _finish_packet({
            "schema": "x_song_resolution_packet_v2",
            "phase": phase,
            "observation_id": observation_id,
            "observation_sha256": observation_sha,
            "observation": row,
            "depends_on_decision_id": dependency,
            "candidate_rows": candidates,
            "candidate_set_sha256": sha256_json(candidates),
            "catalog_snapshot_sha256": snapshot_sha,
            "allowed_actions": list(RETRIEVAL_ACTIONS if phase == "retrieval" else NOVELTY_ACTIONS),
        })
        if _packet_already_decided(conn, packet["packet_id"]):
            excluded.append(
                {
                    "observation_id": observation_id,
                    "reason": "already_decided_current_snapshot",
                }
            )
            continue
        packets.append(packet)
    return {
        "schema": "x_song_resolution_packet_set_v2",
        "phase": phase,
        "generated_at": generated_at,
        "catalog_snapshot": snapshot,
        "catalog_snapshot_sha256": snapshot_sha,
        "packets": packets,
        "excluded": excluded,
    }


def validate_packet_set(packet_set: dict) -> None:
    if packet_set.get("schema") != "x_song_resolution_packet_set_v2":
        raise ValueError("unsupported song packet set schema")
    phase = packet_set.get("phase")
    if phase not in {"retrieval", "novelty"}:
        raise ValueError("invalid song packet phase")
    snapshot = packet_set.get("catalog_snapshot")
    if not isinstance(snapshot, list) or sha256_json(snapshot) != packet_set.get("catalog_snapshot_sha256"):
        raise ValueError("catalog snapshot hash mismatch")
    seen = set()
    for packet in packet_set.get("packets", []):
        if not isinstance(packet, dict):
            raise ValueError("malformed song packet")
        packet_id = packet.get("packet_id")
        if packet_id in seen:
            raise ValueError(f"duplicate packet_id: {packet_id}")
        seen.add(packet_id)
        expected_sha = sha256_json(_packet_payload(packet))
        if expected_sha != packet.get("packet_sha256"):
            raise ValueError(f"packet hash mismatch: {packet_id}")
        if stable_id("xspkt2", expected_sha) != packet_id:
            raise ValueError(f"packet id mismatch: {packet_id}")
        if packet.get("phase") != phase:
            raise ValueError(f"packet phase mismatch: {packet_id}")
        if packet.get("catalog_snapshot_sha256") != packet_set.get("catalog_snapshot_sha256"):
            raise ValueError(f"packet catalog snapshot mismatch: {packet_id}")
        if sha256_json(packet.get("candidate_rows")) != packet.get("candidate_set_sha256"):
            raise ValueError(f"candidate set hash mismatch: {packet_id}")


def load_packet_sets(paths: list[Path]) -> tuple[list[dict], dict[str, dict]]:
    packet_sets = []
    by_id = {}
    for path in paths:
        packet_set = json.loads(Path(path).read_text(encoding="utf-8"))
        validate_packet_set(packet_set)
        packet_sets.append(packet_set)
        for packet in packet_set["packets"]:
            packet_id = packet["packet_id"]
            if packet_id in by_id:
                raise ValueError(f"duplicate packet_id across input files: {packet_id}")
            by_id[packet_id] = {"packet": packet, "packet_set": packet_set}
    return packet_sets, by_id


def _validate_result(result: dict, packet: dict, packet_set: dict, current_observation: dict, current_snapshot: list[dict]) -> dict:
    if not isinstance(result, dict):
        raise ValueError("malformed song result")
    if sha256_json(current_observation) != packet["observation_sha256"]:
        raise ValueError(f"stale observation: {packet['observation_id']}")
    if sha256_json(current_snapshot) != packet_set["catalog_snapshot_sha256"]:
        raise ValueError(f"stale song catalog: {packet['packet_id']}")
    action = result.get("action")
    if action not in packet["allowed_actions"]:
        raise ValueError(f"action not allowed: {action}")
    selected_song_id = result.get("selected_song_id")
    if action == "match_song":
        allowed_ids = {row["song_id"] for row in packet["candidate_rows"]}
        if not isinstance(selected_song_id, str) or selected_song_id not in allowed_ids:
            raise ValueError("selected song was not in the frozen candidate set")
    elif selected_song_id is not None:
        raise ValueError("selected_song_id is only allowed for match_song")
    proposed = current_observation["song_name"] if action == "new_song" else None
    return {
        "action": action,
        "selected_song_id": selected_song_id,
        "proposed_canonical_title": proposed,
        "reason_code": str(result.get("reason_code") or action),
        "reason_detail": str(result.get("reason_detail") or "") or None,
    }


def apply_results(
    conn,
    ledger: dict,
    packet_entries: dict[str, dict],
    results_payload: dict,
    *,
    actor_id: str,
    model_id: str,
    prompt_sha256: str,
    decided_at: str,
    commit: bool = True,
) -> dict:
    if not actor_id or not model_id:
        raise ValueError("local actor_id and model_id are required")
    if len(prompt_sha256) != 64 or any(char not in "0123456789abcdef" for char in prompt_sha256):
        raise ValueError("local prompt_sha256 must be 64 lowercase hex characters")
    validated_sets = set()
    for packet_id, entry in packet_entries.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("packet_set"), dict):
            raise ValueError(f"malformed packet entry: {packet_id}")
        identity = id(entry["packet_set"])
        if identity not in validated_sets:
            validate_packet_set(entry["packet_set"])
            validated_sets.add(identity)
        if entry.get("packet", {}).get("packet_id") != packet_id:
            raise ValueError(f"packet entry key mismatch: {packet_id}")
    if results_payload.get("schema") != "x_song_resolution_results_v2":
        raise ValueError("unsupported song result schema")
    results = results_payload.get("results")
    if not isinstance(results, list):
        raise ValueError("song results must be a list")
    seen = set()
    applied = 0
    no_op = 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        observations = observation_index(ledger)
        current_snapshot = catalog_snapshot(conn)
        for result in results:
            packet_id = result.get("packet_id") if isinstance(result, dict) else None
            if packet_id in seen:
                raise ValueError(f"duplicate result packet_id: {packet_id}")
            seen.add(packet_id)
            entry = packet_entries.get(packet_id)
            if entry is None:
                raise ValueError(f"unknown packet_id: {packet_id}")
            packet = entry["packet"]
            packet_set = entry["packet_set"]
            observation = observations.get(packet["observation_id"])
            if observation is None:
                raise ValueError(f"observation disappeared: {packet['observation_id']}")
            value = _validate_result(result, packet, packet_set, observation, current_snapshot)
            proposed = value["proposed_canonical_title"]
            decision_id = stable_id(
                "xsdec2", packet_id, value["action"], value["selected_song_id"] or "", proposed or ""
            )
            existing_packet = conn.execute(
                """
                SELECT decision_id, action, selected_song_id, proposed_canonical_title
                FROM x_song_resolution_decisions WHERE packet_id=?
                """,
                (packet_id,),
            ).fetchone()
            expected = (decision_id, value["action"], value["selected_song_id"], proposed)
            if existing_packet is not None:
                if tuple(existing_packet) != expected:
                    raise ValueError(f"packet already has a different decision: {packet_id}")
                no_op += 1
                continue

            active = conn.execute(
                """
                SELECT decision_id FROM x_song_resolution_decisions
                WHERE observation_id=? AND phase=? AND status='active'
                """,
                (packet["observation_id"], packet["phase"]),
            ).fetchone()
            supersedes = active[0] if active else None
            if supersedes:
                conn.execute(
                    "UPDATE x_song_resolution_decisions SET status='superseded' WHERE decision_id=?",
                    (supersedes,),
                )
            conn.execute(
                """
                INSERT INTO x_song_resolution_decisions (
                  decision_id, observation_id, observation_sha256, packet_id,
                  packet_sha256, phase, action, selected_song_id,
                  proposed_canonical_title, depends_on_decision_id,
                  candidate_rows_json, candidate_set_sha256,
                  catalog_snapshot_json, catalog_snapshot_sha256,
                  reason_code, reason_detail, actor_id, model_id, prompt_sha256,
                  supersedes_decision_id, decided_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    packet["observation_id"],
                    packet["observation_sha256"],
                    packet_id,
                    packet["packet_sha256"],
                    packet["phase"],
                    value["action"],
                    value["selected_song_id"],
                    proposed,
                    packet["depends_on_decision_id"],
                    canonical_json(packet["candidate_rows"]),
                    packet["candidate_set_sha256"],
                    canonical_json(packet_set["catalog_snapshot"]),
                    packet_set["catalog_snapshot_sha256"],
                    value["reason_code"],
                    value["reason_detail"],
                    actor_id,
                    model_id,
                    prompt_sha256,
                    supersedes,
                    decided_at,
                    decided_at,
                ),
            )
            applied += 1
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"applied": applied, "no_op": no_op, "result_count": len(results)}
