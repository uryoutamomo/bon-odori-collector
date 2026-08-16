"""Explicit, evidence-scoped retraction for E2-S v2 song materializations."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from master_rdb.master_db import MASTER_DB, stable_id
from report_apply.x_song_apply_safety import run_guarded


CONFIRM_TEXT = "RETRACT X SONG MATERIALIZATIONS V2"


def _row(conn, query, params=()):
    conn.row_factory = __import__("sqlite3").Row
    value = conn.execute(query, params).fetchone()
    return dict(value) if value else None


def _song_is_shared(conn, materialization: dict) -> bool:
    other_active = conn.execute(
        """
        SELECT 1 FROM x_song_materializations
        WHERE song_id=? AND materialization_id!=? AND status='active'
        LIMIT 1
        """,
        (materialization["song_id"], materialization["materialization_id"]),
    ).fetchone()
    if other_active:
        return True
    other_fact = conn.execute(
        """
        SELECT 1 FROM occurrence_songs os
        WHERE os.song_id=? AND os.occurrence_song_id!=?
          AND (
            os.origin != 'observed_x_post'
            OR EXISTS (
              SELECT 1 FROM occurrence_song_evidence_links link
              WHERE link.occurrence_song_id=os.occurrence_song_id
                AND link.link_status='accepted'
            )
          )
        LIMIT 1
        """,
        (materialization["song_id"], materialization["occurrence_song_id"]),
    ).fetchone()
    if other_fact:
        return True
    accepted = conn.execute(
        """
        SELECT 1 FROM occurrence_song_evidence_links
        WHERE occurrence_song_id=? AND link_status='accepted'
        LIMIT 1
        """,
        (materialization["occurrence_song_id"],),
    ).fetchone()
    return bool(accepted)


def _cleanup_song_change(conn, materialization: dict, *, shared: bool, now: str) -> str:
    """Undo the matching X-owned create/promotion after the final use disappears.

    The cleanup owner is found by its CAS timestamp rather than by retraction
    order. Later materializations of the same song usually record `none`; the
    final one must still be able to undo the earlier create/promotion.
    """
    song = _row(
        conn,
        "SELECT status, updated_at FROM songs WHERE song_id=?",
        (materialization["song_id"],),
    )
    if shared or not song:
        return "retained_shared_or_changed"
    owner = _row(
        conn,
        """
        SELECT song_change_kind, song_status_before, song_updated_at_after
        FROM x_song_materializations
        WHERE song_id=?
          AND song_change_kind IN ('created', 'promoted_candidate')
          AND song_updated_at_after=?
        ORDER BY materialized_at DESC, materialization_id DESC
        LIMIT 1
        """,
        (materialization["song_id"], song["updated_at"]),
    )
    if not owner:
        return "no_change" if materialization["song_change_kind"] == "none" else "retained_shared_or_changed"
    if owner["song_change_kind"] == "created":
        conn.execute(
            "UPDATE songs SET status='無効', updated_at=? WHERE song_id=?",
            (now, materialization["song_id"]),
        )
        return "tombstoned_created"
    conn.execute(
        "UPDATE songs SET status=?, updated_at=? WHERE song_id=?",
        (owner["song_status_before"], now, materialization["song_id"]),
    )
    return "restored_candidate"


def retract(
    conn,
    materialization_ids: list[str],
    *,
    actor_id: str,
    reason_code: str,
    reason_detail: str | None,
    now: str,
    commit: bool = True,
) -> dict:
    if not materialization_ids:
        raise ValueError("at least one materialization_id is required")
    if len(set(materialization_ids)) != len(materialization_ids):
        raise ValueError("duplicate materialization_id")
    retracted = []
    no_op = []
    conn.execute("BEGIN IMMEDIATE")
    try:
        for materialization_id in materialization_ids:
            materialization = _row(
                conn,
                "SELECT * FROM x_song_materializations WHERE materialization_id=?",
                (materialization_id,),
            )
            if not materialization:
                raise ValueError(f"materialization not found: {materialization_id}")
            prior = _row(
                conn,
                "SELECT * FROM x_song_retractions WHERE materialization_id=?",
                (materialization_id,),
            )
            if prior:
                no_op.append(materialization_id)
                continue
            if materialization["status"] != "active":
                raise ValueError(f"inactive materialization has no retraction record: {materialization_id}")

            cursor = conn.execute(
                """
                UPDATE occurrence_song_evidence_links
                SET link_status='retracted'
                WHERE occurrence_song_id=? AND evidence_id=? AND link_status='accepted'
                """,
                (materialization["occurrence_song_id"], materialization["evidence_id"]),
            )
            evidence_action = "retracted" if cursor.rowcount == 1 else "already_not_accepted"
            shared = _song_is_shared(conn, materialization)
            song_action = _cleanup_song_change(conn, materialization, shared=shared, now=now)

            remaining_evidence = conn.execute(
                """
                SELECT 1 FROM occurrence_song_evidence_links
                WHERE occurrence_song_id=? AND link_status='accepted' LIMIT 1
                """,
                (materialization["occurrence_song_id"],),
            ).fetchone()
            occurrence_song_action = (
                "retained_shared_evidence" if remaining_evidence else "hidden_no_accepted_evidence"
            )
            conn.execute(
                """
                UPDATE x_song_materializations
                SET status='retracted', retracted_at=?
                WHERE materialization_id=? AND status='active'
                """,
                (now, materialization_id),
            )
            retraction_id = stable_id("xsret2", materialization_id)
            conn.execute(
                """
                INSERT INTO x_song_retractions (
                  retraction_id, materialization_id, observation_id,
                  evidence_link_action, occurrence_song_action, song_action,
                  reason_code, reason_detail, actor_id, retracted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    retraction_id, materialization_id, materialization["observation_id"],
                    evidence_action, occurrence_song_action, song_action,
                    reason_code, reason_detail, actor_id, now,
                ),
            )
            retracted.append(
                {
                    "materialization_id": materialization_id,
                    "retraction_id": retraction_id,
                    "evidence_link_action": evidence_action,
                    "occurrence_song_action": occurrence_song_action,
                    "song_action": song_action,
                }
            )
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"retracted": retracted, "no_op": no_op}


def run(
    *, db_path, materialization_ids, actor_id, reason_code, reason_detail,
    now, execute=False, confirm=None,
):
    if execute and confirm != CONFIRM_TEXT:
        raise ValueError(f"--execute requires --confirm {CONFIRM_TEXT!r}")
    guarded = run_guarded(
        db_path=db_path,
        execute=execute,
        timestamp=now,
        temp_prefix="x-song-retract-v2-",
        operation=lambda conn: retract(
            conn,
            list(materialization_ids),
            actor_id=actor_id,
            reason_code=reason_code,
            reason_detail=reason_detail,
            now=now,
            commit=False,
        ),
    )
    report = guarded["report"]
    return {
        "schema": "x_song_retraction_report_v2",
        "mode": "execute" if execute else "dry_run",
        **report,
        "integrity_check": guarded["integrity_check"],
        "foreign_key_issue_count": guarded["foreign_key_issue_count"],
        "backup_db": guarded["backup_db"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=MASTER_DB)
    parser.add_argument("--materialization-id", action="append", required=True)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--reason-code", required=True)
    parser.add_argument("--reason-detail")
    parser.add_argument("--now")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm")
    args = parser.parse_args(argv)
    report = run(
        db_path=args.db,
        materialization_ids=args.materialization_id,
        actor_id=args.actor_id,
        reason_code=args.reason_code,
        reason_detail=args.reason_detail,
        now=args.now or datetime.now(timezone.utc).isoformat(),
        execute=args.execute,
        confirm=args.confirm,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
