#!/usr/bin/env python3
"""CAS-safe, source-scoped writer for reviewed song_candidate finite actions.

Consumes a ``reviewed_finite_actions`` payload (see
``song_candidate_finite_actions.py``) and applies it to the ``songs`` /
``song_aliases`` tables of a fetched copy of the master RDB. Never writes to
Notion, never touches ``review_inbox_items``, ``occurrence_songs``,
``evidence_items``, event tables, or ``notion_sync_jobs``.

Dry-run is the default: it fetches Rstart, plans/executes the finite actions
against a temporary working copy, audits it, and reports without publishing.
``apply=True`` additionally CAS-publishes the working copy (fail-closed on any
remote drift) and refetches to verify the published artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import string
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from master_rdb.master_db import connect_existing, file_sha256, normalize_text, stable_id, table_counts
from review_inbox import inbox_rows
from review_inbox_adapters.source_writer import (
    ArtifactStore,
    CasConflictError,
    SourceWriterError,
    _audit_connection,
    _require_healthy,
)
from song_candidate_finite_actions import (
    ReviewedSongDecision,
    validate_reviewed_payload,
)
from song_processing.song_catalog import SongReviewState, _review_state_for_status


ROOT = Path(__file__).resolve().parent
DEFAULT_BACKUP_DIR = ROOT / "data" / "song_candidate_apply_backups"

WRITABLE_TABLES = {"songs", "song_aliases"}
STATUS_ACTIVE = "active"
STATUS_INACTIVE = "無効"
LINEAGE_SOURCE = "review_inbox:song_candidate"

EXPECTED_DELTA = {
    "inserted": {"songs": 1, "song_aliases": 1},
    "promoted": {"songs": 0, "song_aliases": 0},
    "alias_inserted": {"songs": 0, "song_aliases": 1},
    "no_op": {"songs": 0, "song_aliases": 0},
    "tombstoned": {"songs": 1, "song_aliases": 0},
    "tombstoned_existing": {"songs": 0, "song_aliases": 0},
    "held": {"songs": 0, "song_aliases": 0},
}
EXPECTED_STATUS_AFTER = {
    "inserted": STATUS_ACTIVE,
    "promoted": STATUS_ACTIVE,
    "tombstoned": STATUS_INACTIVE,
    "tombstoned_existing": STATUS_INACTIVE,
}


def _status_class(status: str) -> SongReviewState:
    """Classify an existing songs.status value using the P1 canonical mapping
    (song_processing.song_catalog): active/有効 -> verified, 候補 -> candidate,
    無効 -> rejected, anything else/empty -> unknown. UNKNOWN is never folded
    into candidate; callers must fail closed on it."""

    return _review_state_for_status(status)


def _song_only_authorizer(
    action: int,
    object_name: str | None,
    _column: str | None,
    _database: str | None,
    _trigger: str | None,
) -> int:
    write_actions = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}
    if action in write_actions and object_name not in WRITABLE_TABLES:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _non_song_counts(audit: dict[str, Any]) -> dict[str, int]:
    return {
        table: count
        for table, count in audit["table_counts"].items()
        if table not in WRITABLE_TABLES
    }


def _table_count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608 (fixed table name from a closed set)


def _lookup_song(conn: sqlite3.Connection, normalized_title: str):
    canonical_row = conn.execute(
        "SELECT song_id, status FROM songs WHERE normalized_title = ?", (normalized_title,)
    ).fetchone()
    alias_song_ids = sorted(
        {
            row[0]
            for row in conn.execute(
                "SELECT song_id FROM song_aliases WHERE normalized_alias = ?", (normalized_title,)
            ).fetchall()
        }
    )
    return canonical_row, alias_song_ids


def _fetch_inbox_row(conn: sqlite3.Connection, inbox_id: str) -> dict[str, Any] | None:
    for row in inbox_rows(conn, status=None, ensure_schema=False):
        if row["inbox_id"] == inbox_id:
            return row
    return None


def _lineage_memo(decision: ReviewedSongDecision) -> str:
    """Deterministic memo suffix so a new songs row keeps a trail back to the
    reviewed decision that created it, without inventing a new column. Only
    used on INSERT paths; UPDATE paths never touch memo so it cannot grow on
    retries or on rows this consumer did not create."""

    lineage = (
        f"[song_candidate_finite_actions] source_inbox_id={decision.source_inbox_id} "
        f"source_key={decision.source_key} reviewed_by={decision.reviewed_by}"
    )
    return f"{decision.note}\n{lineage}" if decision.note else lineage


def _check_lifecycle(conn: sqlite3.Connection, decision: ReviewedSongDecision) -> None:
    """Read-only guard: verify the reviewed action matches the review inbox
    row's identity, staged payload content, and decision lifecycle. This
    consumer never writes to review_inbox_items.

    ``kind`` (not ``domain``) is the identity anchor: the real B4 song
    adapter (review_inbox_adapters/low_priority_adapters.py DailySongAdapter)
    stages rows with domain="曲・用語・低緊急度", kind="song" -- domain text
    is presentation-facing and not a stable contract.

    A reviewed row's action="reject_song" is validated against
    decision="rejected" + decision_route="no_apply": review_inbox_adapters/
    decision_stage.py routes every rejected decision to "no_apply"
    (canonical_route()), never "domain_stage", so a reject can only ever be
    staged as an operator-approved rejected+no_apply lifecycle on the same
    song inbox row -- there is no accepted/domain_stage packet for rejects.
    """

    row = _fetch_inbox_row(conn, decision.source_inbox_id)
    if row is None:
        raise SourceWriterError(f"source inbox row not found: {decision.source_inbox_id}")
    if row.get("kind") != "song":
        raise SourceWriterError(f"source inbox row is not kind=song: {decision.source_inbox_id}")
    if str(row.get("source_id") or "") != decision.source_id:
        raise SourceWriterError(f"source_id mismatch for {decision.source_inbox_id}")
    if str(row.get("source_key") or "") != decision.source_key:
        raise SourceWriterError(f"source_key mismatch for {decision.source_inbox_id}")

    payload = row.get("payload") or {}
    inbox_title = str(payload.get("canonical_song_name") or payload.get("term") or "")
    if normalize_text(inbox_title) != normalize_text(decision.candidate_title):
        raise SourceWriterError(
            f"candidate_title does not match the staged inbox payload for {decision.source_inbox_id}"
        )

    if decision.action in {"register_song", "add_song_alias"}:
        expected = ("accepted", "domain_stage")
    elif decision.action == "reject_song":
        expected = ("rejected", "no_apply")
    else:
        expected = ("hold", "no_apply")
    actual = (row.get("decision"), row.get("decision_route"))
    if actual != expected:
        raise SourceWriterError(
            f"decision lifecycle mismatch for {decision.source_inbox_id}: "
            f"expected {expected}, got {actual}"
        )

    if str(row.get("decided_by") or "") != decision.reviewed_by:
        raise SourceWriterError(f"reviewed_by does not match inbox decided_by for {decision.source_inbox_id}")
    if str(row.get("decided_at") or "") != decision.reviewed_at:
        raise SourceWriterError(f"reviewed_at does not match inbox decided_at for {decision.source_inbox_id}")

    inbox_source_url = str(row.get("source_url") or "")
    if decision.source_url != inbox_source_url:
        raise SourceWriterError(
            f"source_url does not match the staged inbox row for {decision.source_inbox_id}"
        )


def _apply_register_song(conn: sqlite3.Connection, decision: ReviewedSongDecision) -> dict[str, Any]:
    title = decision.candidate_title.strip()
    normalized = normalize_text(title)
    canonical_row, alias_song_ids = _lookup_song(conn, normalized)

    if canonical_row is None:
        if len(alias_song_ids) > 1:
            raise SourceWriterError(f"register_song ambiguous alias for {decision.source_inbox_id}")
        if alias_song_ids:
            raise SourceWriterError(f"register_song alias hit for {decision.source_inbox_id}")
        song_id = stable_id("song", title)
        collision = conn.execute(
            "SELECT normalized_title FROM songs WHERE song_id = ?", (song_id,)
        ).fetchone()
        if collision is not None:
            raise SourceWriterError(f"register_song song_id collision for {decision.source_inbox_id}")
        conn.execute(
            """
            INSERT INTO songs(
              song_id, canonical_title, normalized_title, category, status, prior_tier,
              target_area, evidence_count, source_url, memo, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                song_id,
                title,
                normalized,
                "",
                STATUS_ACTIVE,
                "",
                "",
                None,
                decision.source_url,
                _lineage_memo(decision),
                decision.reviewed_at,
                decision.reviewed_at,
            ),
        )
        conn.execute(
            "INSERT INTO song_aliases VALUES (?, ?, ?, ?, ?)",
            (song_id, title, normalized, LINEAGE_SOURCE, "manual"),
        )
        return {"result": "inserted", "song_id": song_id}

    song_id, status = canonical_row
    status_class = _status_class(status)
    if status_class == SongReviewState.VERIFIED:
        return {"result": "no_op", "song_id": song_id}
    if status_class == SongReviewState.REJECTED:
        raise SourceWriterError(f"register_song blocked: rejected exact for {decision.source_inbox_id}")
    if status_class == SongReviewState.UNKNOWN:
        raise SourceWriterError(
            f"register_song blocked: unknown existing status {status!r} for {decision.source_inbox_id}"
        )
    conn.execute(
        "UPDATE songs SET status = ?, updated_at = ? WHERE song_id = ?",
        (STATUS_ACTIVE, decision.reviewed_at, song_id),
    )
    return {"result": "promoted", "song_id": song_id}


def _apply_add_song_alias(conn: sqlite3.Connection, decision: ReviewedSongDecision) -> dict[str, Any]:
    target_row = conn.execute(
        "SELECT song_id, status, normalized_title FROM songs WHERE song_id = ?",
        (decision.target_song_id,),
    ).fetchone()
    if target_row is None:
        raise SourceWriterError(f"add_song_alias target not found for {decision.source_inbox_id}")
    target_song_id, target_status, target_normalized_title = target_row
    if _status_class(target_status) != SongReviewState.VERIFIED:
        raise SourceWriterError(f"add_song_alias target is not active for {decision.source_inbox_id}")

    alias_title = decision.candidate_title.strip()
    normalized = normalize_text(alias_title)
    if normalized == target_normalized_title:
        raise SourceWriterError(
            f"add_song_alias canonical normalized collision for {decision.source_inbox_id}"
        )
    other_song = conn.execute(
        "SELECT song_id FROM songs WHERE normalized_title = ? AND song_id != ?",
        (normalized, target_song_id),
    ).fetchone()
    if other_song is not None:
        raise SourceWriterError(
            f"add_song_alias would collide with another song's canonical title for {decision.source_inbox_id}"
        )

    existing = conn.execute(
        "SELECT song_id FROM song_aliases WHERE normalized_alias = ?", (normalized,)
    ).fetchall()
    if existing:
        parents = sorted({row[0] for row in existing})
        if parents == [target_song_id]:
            return {"result": "no_op", "song_id": target_song_id}
        raise SourceWriterError(f"add_song_alias ambiguous/foreign alias for {decision.source_inbox_id}")

    conn.execute(
        "INSERT INTO song_aliases VALUES (?, ?, ?, ?, ?)",
        (target_song_id, alias_title, normalized, LINEAGE_SOURCE, "manual"),
    )
    return {"result": "alias_inserted", "song_id": target_song_id}


def _apply_reject_song(conn: sqlite3.Connection, decision: ReviewedSongDecision) -> dict[str, Any]:
    title = decision.candidate_title.strip()
    normalized = normalize_text(title)
    canonical_row, alias_song_ids = _lookup_song(conn, normalized)

    if canonical_row is None:
        if len(alias_song_ids) > 1:
            raise SourceWriterError(f"reject_song ambiguous alias for {decision.source_inbox_id}")
        if alias_song_ids:
            raise SourceWriterError(f"reject_song alias hit for {decision.source_inbox_id}")
        song_id = stable_id("song", title)
        collision = conn.execute(
            "SELECT normalized_title FROM songs WHERE song_id = ?", (song_id,)
        ).fetchone()
        if collision is not None:
            raise SourceWriterError(f"reject_song song_id collision for {decision.source_inbox_id}")
        conn.execute(
            """
            INSERT INTO songs(
              song_id, canonical_title, normalized_title, category, status, prior_tier,
              target_area, evidence_count, source_url, memo, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                song_id,
                title,
                normalized,
                "",
                STATUS_INACTIVE,
                "",
                "",
                None,
                decision.source_url,
                _lineage_memo(decision),
                decision.reviewed_at,
                decision.reviewed_at,
            ),
        )
        return {"result": "tombstoned", "song_id": song_id}

    song_id, status = canonical_row
    status_class = _status_class(status)
    if status_class == SongReviewState.VERIFIED:
        raise SourceWriterError(f"reject_song blocked: verified exact for {decision.source_inbox_id}")
    if status_class == SongReviewState.REJECTED:
        return {"result": "no_op", "song_id": song_id}
    if status_class == SongReviewState.UNKNOWN:
        raise SourceWriterError(
            f"reject_song blocked: unknown existing status {status!r} for {decision.source_inbox_id}"
        )
    conn.execute(
        "UPDATE songs SET status = ?, updated_at = ? WHERE song_id = ?",
        (STATUS_INACTIVE, decision.reviewed_at, song_id),
    )
    return {"result": "tombstoned_existing", "song_id": song_id}


def _action_summary(action_results: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for result in action_results:
        summary[result["result"]] = summary.get(result["result"], 0) + 1
    return dict(sorted(summary.items()))


def _verify_action_results(conn: sqlite3.Connection, action_results: list[dict[str, Any]]) -> None:
    """Re-check, against the Rend refetch, that every changed action's target
    song/alias actually landed the way it was planned -- not just that
    checksums and table-level audit counts line up."""

    for result in action_results:
        outcome = result["result"]
        song_id = result.get("song_id")
        expected_status = EXPECTED_STATUS_AFTER.get(outcome)
        if expected_status is not None:
            row = conn.execute("SELECT status FROM songs WHERE song_id = ?", (song_id,)).fetchone()
            if row is None or row[0] != expected_status:
                raise SourceWriterError(
                    f"Rend refetch song status mismatch for {result['source_inbox_id']}: "
                    f"expected {expected_status!r}, got {row[0] if row else None!r}"
                )
        if outcome in {"inserted", "alias_inserted"}:
            # "inserted" (register_song NO_MATCH) also creates a canonical
            # song_aliases row alongside the songs row; verify both landed.
            normalized = normalize_text(str(result["candidate_title"]).strip())
            alias_row = conn.execute(
                "SELECT 1 FROM song_aliases WHERE song_id = ? AND normalized_alias = ?",
                (song_id, normalized),
            ).fetchone()
            if alias_row is None:
                raise SourceWriterError(f"Rend refetch alias missing for {result['source_inbox_id']}")


_DISPATCH: dict[str, Callable[[sqlite3.Connection, ReviewedSongDecision], dict[str, Any]]] = {
    "register_song": _apply_register_song,
    "add_song_alias": _apply_add_song_alias,
    "reject_song": _apply_reject_song,
}


def _apply_decisions(conn: sqlite3.Connection, decisions: list[ReviewedSongDecision]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for decision in decisions:
        before_songs = _table_count(conn, "songs")
        before_aliases = _table_count(conn, "song_aliases")
        if decision.action == "hold":
            outcome = {"result": "held", "song_id": None}
        else:
            outcome = _DISPATCH[decision.action](conn, decision)
        after_songs = _table_count(conn, "songs")
        after_aliases = _table_count(conn, "song_aliases")
        actual_delta = {"songs": after_songs - before_songs, "song_aliases": after_aliases - before_aliases}
        expected_delta = EXPECTED_DELTA[outcome["result"]]
        if actual_delta != expected_delta:
            raise SourceWriterError(
                f"unexplained delta for {decision.source_inbox_id}: "
                f"expected {expected_delta} actual {actual_delta}"
            )
        results.append(
            {
                "source_inbox_id": decision.source_inbox_id,
                "action": decision.action,
                "candidate_title": decision.candidate_title,
                "target_song_id": decision.target_song_id,
                **outcome,
            }
        )
    return results


def run_song_candidate_apply(
    *,
    store: ArtifactStore,
    reviewed_payload: dict[str, Any],
    reviewed_payload_sha256: str,
    expected_rstart_checksum: str,
    public_projection_digest: Callable[[Path], str],
    apply: bool = False,
    backup_dir: Path = DEFAULT_BACKUP_DIR,
    work_dir: Path | None = None,
) -> dict[str, Any]:
    decisions = validate_reviewed_payload(reviewed_payload)
    if len(expected_rstart_checksum) != 64 or any(
        char not in string.hexdigits for char in expected_rstart_checksum
    ):
        raise SourceWriterError("operator-fixed Rstart checksum must be SHA-256")

    rstart = store.status()
    if rstart.checksum != expected_rstart_checksum:
        raise SourceWriterError(
            "Rstart checksum does not match the operator-fixed expectation: "
            f"expected={expected_rstart_checksum} actual={rstart.checksum}"
        )

    if work_dir is not None:
        Path(work_dir).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work_dir) as tmp:
        root = Path(tmp)
        working = root / "working.sqlite"
        verified = root / "verified.sqlite"
        store.fetch(working)
        if file_sha256(working) != rstart.checksum:
            raise SourceWriterError("fetched database checksum does not match Rstart")

        backup_dir = Path(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"song_candidate_apply_rstart_{rstart.checksum}.sqlite"
        if backup_path.exists():
            if file_sha256(backup_path) != rstart.checksum:
                raise SourceWriterError(f"backup path exists with different content: {backup_path}")
        else:
            shutil.copy2(working, backup_path)

        public_before = public_projection_digest(working)
        conn = connect_existing(working, isolation_level=None)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            before_audit = _audit_connection(conn)
            _require_healthy(before_audit, label="Rstart")
            for decision in decisions:
                _check_lifecycle(conn, decision)

            conn.set_authorizer(_song_only_authorizer)
            conn.execute("BEGIN IMMEDIATE")
            try:
                action_results = _apply_decisions(conn, decisions)
                after_audit = _audit_connection(conn)
                _require_healthy(after_audit, label="candidate")
                if _non_song_counts(after_audit) != _non_song_counts(before_audit):
                    raise SourceWriterError("song candidate writer changed tables outside songs/song_aliases")
                changed = any(r["result"] not in {"no_op", "held"} for r in action_results)
                if changed:
                    conn.commit()
                else:
                    conn.rollback()
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                raise
            finally:
                conn.set_authorizer(None)
        finally:
            conn.close()

        public_after = public_projection_digest(working)
        if public_after != public_before:
            raise SourceWriterError("song candidate writer changed the public projection")

        base_report = {
            "generated_by": "apply_song_candidate_finite_actions.py",
            "apply": apply,
            "reviewed_payload_sha256": reviewed_payload_sha256,
            "decision_count": len(decisions),
            "backup_path": str(backup_path),
            "rstart": asdict(rstart),
            "operator_expected_rstart_checksum": expected_rstart_checksum,
            "actions": action_results,
            "action_summary": _action_summary(action_results),
            "audit": {
                "integrity": after_audit["integrity"],
                "foreign_key_violation_count": len(after_audit["foreign_key_violations"]),
                "non_song_table_counts_unchanged": True,
                "public_projection_unchanged": True,
            },
        }

        if not apply:
            return {**base_report, "dry_run": True, "published": False}

        if not changed:
            return {**base_report, "dry_run": False, "published": False, "no_op": True, "rend": asdict(rstart)}

        candidate_checksum = file_sha256(working)
        if store.status().checksum != rstart.checksum:
            raise CasConflictError("remote checksum changed after Rstart; song candidate apply was not published")
        rend = store.publish(working, expected_remote_checksum=rstart.checksum)
        if rend.checksum != candidate_checksum:
            raise SourceWriterError("published artifact checksum does not match the candidate")
        if store.status() != rend:
            raise SourceWriterError("remote status does not match the published song candidate artifact")

        store.fetch(verified)
        if file_sha256(verified) != rend.checksum:
            raise SourceWriterError("verification fetch checksum does not match Rend")
        verify_conn = connect_existing(verified)
        try:
            verify_conn.execute("PRAGMA foreign_keys = ON")
            verify_audit = _audit_connection(verify_conn)
            _require_healthy(verify_audit, label="Rend refetch")
            _verify_action_results(verify_conn, action_results)
        finally:
            verify_conn.close()
        if _non_song_counts(verify_audit) != _non_song_counts(before_audit):
            raise SourceWriterError("Rend refetch changed tables outside songs/song_aliases")
        if public_projection_digest(verified) != public_before:
            raise SourceWriterError("Rend refetch changed the public projection")

        return {
            **base_report,
            "dry_run": False,
            "published": True,
            "no_op": False,
            "candidate_checksum": candidate_checksum,
            "rend": asdict(rend),
            "verification_fetch": {
                "checksum": file_sha256(verified),
                "integrity": verify_audit["integrity"],
                "foreign_key_violation_count": len(verify_audit["foreign_key_violations"]),
                "public_projection_unchanged": True,
                "action_results_match_plan": True,
            },
        }


def _load_reviewed_payload(path: Path) -> tuple[dict[str, Any], str]:
    data = Path(path).read_bytes()
    try:
        payload = json.loads(data)
    except ValueError as exc:
        raise SourceWriterError(f"invalid reviewed song payload JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise SourceWriterError("reviewed song payload root must be an object")
    return payload, hashlib.sha256(data).hexdigest()


def _build_store(bucket: str, prefix: str) -> ArtifactStore:
    from review_inbox_adapters.production_wiring import MasterDbS3ArtifactStore

    return MasterDbS3ArtifactStore(bucket=bucket, prefix=prefix)


def _build_public_projection_digest(target_year: int, today: str) -> Callable[[Path], str]:
    from review_inbox_adapters.production_wiring import public_projection_digest as _digest

    return lambda db_path: _digest(db_path, target_year=target_year, today=today)


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewed-payload", type=Path, required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--expect-rstart-checksum", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--target-year", type=int, required=True)
    parser.add_argument("--today", required=True, help="fixed JST date, YYYY-MM-DD")
    parser.add_argument("--out-json", type=Path, default=None)
    args = parser.parse_args(argv)

    from review_inbox_adapters.shadow_execution_gate import validate_public_today

    validate_public_today(args.today)

    if args.apply:
        import operation_safety.manual_apply_guards as manual_apply_guards

        manual_apply_guards.require_confirmation(
            args.apply,
            args.confirm,
            manual_apply_guards.SONG_CANDIDATE_FINITE_ACTIONS_CONFIRMATION,
            "apply_song_candidate_finite_actions.py --apply",
        )

    payload, payload_sha256 = _load_reviewed_payload(args.reviewed_payload)
    store = _build_store(args.bucket, args.prefix)
    digest_fn = _build_public_projection_digest(args.target_year, args.today)

    result = run_song_candidate_apply(
        store=store,
        reviewed_payload=payload,
        reviewed_payload_sha256=payload_sha256,
        expected_rstart_checksum=args.expect_rstart_checksum,
        public_projection_digest=digest_fn,
        apply=args.apply,
        backup_dir=args.backup_dir,
        work_dir=args.work_dir,
    )

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out_json:
        args.out_json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
