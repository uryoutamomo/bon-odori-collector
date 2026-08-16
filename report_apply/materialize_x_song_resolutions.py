"""Materialize fully resolved E2-S v2 X song claims into master facts."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from master_rdb.master_db import MASTER_DB, normalize_text, stable_id
from report_apply.event_report_helpers import (
    link_resolved_occurrence_song,
    upsert_evidence_item,
)
from report_apply.x_song_apply_safety import run_guarded
from review_inbox_adapters.x_occurrence_resolution_contract import occurrence_snapshot
from review_inbox_adapters.x_song_resolution_contract import (
    catalog_snapshot,
    eligible_observation,
    load_observation_ledger,
    observation_index,
    sha256_json,
)


CONFIRM_TEXT = "MATERIALIZE X SONG RESOLUTIONS V2"


def _row(conn, query, params=()):
    conn.row_factory = __import__("sqlite3").Row
    value = conn.execute(query, params).fetchone()
    return dict(value) if value else None


def _final_song_decision(conn, observation_id: str):
    retrieval = _row(
        conn,
        """
        SELECT * FROM x_song_resolution_decisions
        WHERE observation_id=? AND phase='retrieval' AND status='active'
        """,
        (observation_id,),
    )
    if not retrieval:
        return None, "song_retrieval_missing"
    if retrieval["action"] == "match_song":
        return retrieval, None
    if retrieval["action"] != "candidate_missing":
        return None, f"song_{retrieval['action']}"
    novelty = _row(
        conn,
        """
        SELECT * FROM x_song_resolution_decisions
        WHERE observation_id=? AND phase='novelty' AND status='active'
        """,
        (observation_id,),
    )
    if not novelty:
        return None, "song_novelty_missing"
    if novelty["depends_on_decision_id"] != retrieval["decision_id"]:
        return None, "song_novelty_dependency_stale"
    if novelty["action"] not in {"match_song", "new_song"}:
        return None, f"song_{novelty['action']}"
    return novelty, None


def build_plan(conn, ledger: dict) -> dict:
    current_catalog_sha = sha256_json(catalog_snapshot(conn))
    current_occurrence_snapshot = occurrence_snapshot(conn)
    current_occurrence_sha = sha256_json(current_occurrence_snapshot)
    current_occurrence_ids = {row["occurrence_id"] for row in current_occurrence_snapshot}
    ready = []
    held = []
    for observation_id, observation in sorted(observation_index(ledger).items()):
        eligible, reason = eligible_observation(observation)
        if not eligible:
            held.append({"observation_id": observation_id, "reason": reason})
            continue
        song_decision, reason = _final_song_decision(conn, observation_id)
        if not song_decision:
            held.append({"observation_id": observation_id, "reason": reason})
            continue
        occurrence_decision = _row(
            conn,
            """
            SELECT * FROM x_occurrence_resolution_decisions
            WHERE observation_id=? AND status='active'
            """,
            (observation_id,),
        )
        if not occurrence_decision or occurrence_decision["action"] != "match_occurrence":
            held.append({"observation_id": observation_id, "reason": "occurrence_unresolved"})
            continue
        if (
            occurrence_decision["occurrence_snapshot_sha256"] != current_occurrence_sha
            or occurrence_decision["selected_occurrence_id"] not in current_occurrence_ids
        ):
            held.append({"observation_id": observation_id, "reason": "occurrence_snapshot_stale"})
            continue
        observation_sha = sha256_json(observation)
        if (
            song_decision["observation_sha256"] != observation_sha
            or occurrence_decision["observation_sha256"] != observation_sha
        ):
            held.append({"observation_id": observation_id, "reason": "observation_stale"})
            continue
        if song_decision["catalog_snapshot_sha256"] != current_catalog_sha:
            held.append({"observation_id": observation_id, "reason": "song_catalog_stale"})
            continue
        existing = _row(
            conn,
            "SELECT * FROM x_song_materializations WHERE observation_id=? AND status='active'",
            (observation_id,),
        )
        if existing:
            reason = "already_materialized" if existing["observation_sha256"] == observation_sha else "prior_revision_active"
            held.append({"observation_id": observation_id, "reason": reason})
            continue
        ready.append(
            {
                "observation_id": observation_id,
                "observation_sha256": observation_sha,
                "observation": observation,
                "song_decision": song_decision,
                "occurrence_decision": occurrence_decision,
            }
        )
    return {"ready": ready, "held": held}


def _prepare_song(conn, item: dict, now: str) -> dict:
    decision = item["song_decision"]
    observation = item["observation"]
    if decision["action"] == "new_song":
        title = decision["proposed_canonical_title"]
        if normalize_text(title) != normalize_text(observation["song_name"]):
            raise ValueError("new-song title no longer matches the observation")
        normalized = normalize_text(title)
        canonical = _row(conn, "SELECT song_id FROM songs WHERE normalized_title=?", (normalized,))
        alias = _row(conn, "SELECT song_id FROM song_aliases WHERE normalized_alias=?", (normalized,))
        if canonical or alias:
            raise ValueError("new-song decision now collides with the catalog")
        song_id = stable_id("xsongmaster2", item["observation_id"], item["observation_sha256"])
        conn.execute(
            """
            INSERT INTO songs (
              song_id, canonical_title, normalized_title, status, evidence_count,
              source_url, memo, created_at, updated_at
            ) VALUES (?, ?, ?, 'active', 1, ?, ?, ?, ?)
            """,
            (
                song_id,
                title,
                normalized,
                observation.get("url"),
                f"[x_song_identity_v2] observation_id={item['observation_id']} decision_id={decision['decision_id']}",
                now,
                now,
            ),
        )
        return {
            "song_id": song_id,
            "canonical_title": title,
            "change_kind": "created",
            "status_before": None,
            "updated_at_after": now,
        }

    song = _row(
        conn,
        "SELECT song_id, canonical_title, status, updated_at FROM songs WHERE song_id=?",
        (decision["selected_song_id"],),
    )
    if not song:
        raise ValueError("selected song disappeared")
    if song["status"] in {"active", "有効"}:
        return {
            "song_id": song["song_id"],
            "canonical_title": song["canonical_title"],
            "change_kind": "none",
            "status_before": song["status"],
            "updated_at_after": song["updated_at"],
        }
    if song["status"] != "候補":
        raise ValueError("selected song is neither active nor a promotable candidate")
    conn.execute(
        "UPDATE songs SET status='active', updated_at=? WHERE song_id=? AND status='候補'",
        (now, song["song_id"]),
    )
    return {
        "song_id": song["song_id"],
        "canonical_title": song["canonical_title"],
        "change_kind": "promoted_candidate",
        "status_before": song["status"],
        "updated_at_after": now,
    }


def materialize(conn, ledger: dict, *, actor_id: str, now: str, commit: bool = True) -> dict:
    applied = []
    conn.execute("BEGIN IMMEDIATE")
    try:
        plan = build_plan(conn, ledger)
        for item in plan["ready"]:
            observation = item["observation"]
            claim_type = observation["claim_type"]
            role, evidence_status = {
                "announced": ("setlist", "announced"),
                "observed": ("result", "observed"),
            }[claim_type]
            song = _prepare_song(conn, item, now)
            evidence_id = stable_id(
                "evid", "x_song_claim_v2", item["observation_id"], item["observation_sha256"]
            )
            raw = {
                "observation": observation,
                "observation_sha256": item["observation_sha256"],
                "song_decision_id": item["song_decision"]["decision_id"],
                "occurrence_decision_id": item["occurrence_decision"]["decision_id"],
                "materialized_by": actor_id,
            }
            upsert_evidence_item(
                conn,
                evidence_id,
                platform="x",
                evidence_type="x_song_claim_v2",
                source_key=item["observation_id"],
                account_key=observation.get("account"),
                title=observation.get("event_name") or observation["song_name"],
                text_excerpt=observation["evidence_quote"],
                url=observation.get("url"),
                event_date=observation.get("event_date_start"),
                raw_json_extra=raw,
                now=now,
            )
            linked = link_resolved_occurrence_song(
                conn,
                item["occurrence_decision"]["selected_occurrence_id"],
                song["song_id"],
                song["canonical_title"],
                evidence_id,
                role=role,
                evidence_status=evidence_status,
                evidence_note=f"X claim {item['observation_id']}",
                now=now,
            )
            materialization_id = stable_id(
                "xsmat2", item["observation_id"], item["observation_sha256"]
            )
            conn.execute(
                """
                INSERT INTO x_song_materializations (
                  materialization_id, observation_id, observation_sha256,
                  song_decision_id, occurrence_decision_id, song_id,
                  occurrence_id, occurrence_song_id, evidence_id,
                  claim_type, role, evidence_status, song_change_kind,
                  song_status_before, song_updated_at_after,
                  created_occurrence_song, materialized_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    materialization_id, item["observation_id"], item["observation_sha256"],
                    item["song_decision"]["decision_id"], item["occurrence_decision"]["decision_id"],
                    song["song_id"], item["occurrence_decision"]["selected_occurrence_id"],
                    linked["occurrence_song_id"], evidence_id, claim_type, role,
                    evidence_status, song["change_kind"], song["status_before"],
                    song["updated_at_after"], int(linked["created"]), now,
                ),
            )
            applied.append(
                {
                    "materialization_id": materialization_id,
                    "observation_id": item["observation_id"],
                    "song_id": song["song_id"],
                    "occurrence_id": item["occurrence_decision"]["selected_occurrence_id"],
                    "song_change_kind": song["change_kind"],
                }
            )
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"applied": applied, "held": plan["held"]}


def run(*, db_path, observation_path, actor_id, now, execute=False, confirm=None):
    if execute and confirm != CONFIRM_TEXT:
        raise ValueError(f"--execute requires --confirm {CONFIRM_TEXT!r}")
    ledger = load_observation_ledger(observation_path)
    guarded = run_guarded(
        db_path=db_path,
        execute=execute,
        timestamp=now,
        temp_prefix="x-song-materialize-v2-",
        operation=lambda conn: materialize(
            conn, ledger, actor_id=actor_id, now=now, commit=False
        ),
    )
    report = guarded["report"]
    return {
        "schema": "x_song_materialization_report_v2",
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
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--now")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm")
    args = parser.parse_args(argv)
    report = run(
        db_path=args.db,
        observation_path=args.observations,
        actor_id=args.actor_id,
        now=args.now or datetime.now(timezone.utc).isoformat(),
        execute=args.execute,
        confirm=args.confirm,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
