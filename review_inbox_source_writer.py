#!/usr/bin/env python3
"""Default-off, source-scoped review inbox writer and CAS audit runner.

This module deliberately has no production S3 or workflow wiring.  Callers
must inject an artifact store and explicitly enable both shadow writing and
CAS publication.  B1-3 is the earliest phase allowed to provide real wiring.
"""

from __future__ import annotations

import os
import sqlite3
import string
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from master_db import connect_existing, file_sha256, table_counts
from review_inbox import (
    INBOX_SCHEMA_VERSION,
    inbox_rows,
    inbox_schema_version,
    normalized_item,
    upsert_inbox_items,
)
from review_inbox_parity import build_parity_report, item_payload_hash


INBOX_TABLE = "review_inbox_items"
LIFECYCLE_FIELDS = (
    "status",
    "decision",
    "decided_by",
    "decided_at",
    "closed_at",
    "decision_route",
)
WRITER_FIELDS = (
    "kind",
    "domain",
    "time_scope",
    "priority_label",
    "priority_score",
    "title",
    "event_name",
    "venue",
    "event_year",
    "source_id",
    "source_key",
    "source_url",
    "recommended_action",
)


class SourceWriterError(RuntimeError):
    """A fail-closed runner validation or audit error."""


class CasConflictError(SourceWriterError):
    """The remote artifact changed after Rstart was recorded."""


@dataclass(frozen=True)
class ArtifactState:
    checksum: str
    snapshot_id: str


class ArtifactStore(Protocol):
    """Minimal artifact boundary; implemented by FakeStore in B1-2 tests."""

    def status(self) -> ArtifactState: ...

    def fetch(self, destination: Path) -> None: ...

    def publish(self, source: Path, *, expected_remote_checksum: str) -> ArtifactState: ...


@dataclass(frozen=True)
class SourceWriterFlags:
    dual_write_mode: str = "off"
    cas_publish_enabled: bool = False
    reader_mode: str = "legacy"
    legacy_writer_enabled: bool = True

    @classmethod
    def from_env(cls) -> "SourceWriterFlags":
        return cls(
            dual_write_mode=os.getenv("REVIEW_INBOX_DUAL_WRITE_MODE", "off").strip(),
            cas_publish_enabled=_env_bool("REVIEW_INBOX_CAS_PUBLISH_ENABLED", False),
            reader_mode=os.getenv("REVIEW_INBOX_READER_MODE", "legacy").strip(),
            legacy_writer_enabled=_env_bool("REVIEW_INBOX_LEGACY_WRITER_ENABLED", True),
        )

    def require_shadow_run(self, selection_mode: str) -> None:
        if self.dual_write_mode not in {"off", "canary", "bulk"}:
            raise SourceWriterError(f"unsupported dual-write mode: {self.dual_write_mode}")
        if self.dual_write_mode == "off":
            raise SourceWriterError("review inbox dual-write is off")
        expected_selection = "canary" if self.dual_write_mode == "canary" else "all"
        if selection_mode != expected_selection:
            raise SourceWriterError(
                f"selection mode {selection_mode!r} does not match "
                f"dual-write mode {self.dual_write_mode!r}"
            )
        if not self.cas_publish_enabled:
            raise SourceWriterError("review inbox CAS publication is off")
        if self.reader_mode != "legacy":
            raise SourceWriterError("B1-2 cannot change the review inbox reader")
        if not self.legacy_writer_enabled:
            raise SourceWriterError("B1-2 cannot stop the legacy writer")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise SourceWriterError(f"invalid boolean environment value for {name}: {raw!r}")


def _selection_mode(snapshot: dict[str, Any]) -> str:
    selection = snapshot.get("selection") or {}
    mode = str(selection.get("mode") or "all")
    if mode not in {"canary", "all"}:
        raise SourceWriterError(f"unsupported adapter selection mode: {mode}")
    return mode


def _validate_snapshot(snapshot: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    source_id = str(snapshot.get("source_id") or "").strip()
    if not source_id:
        raise SourceWriterError("adapted snapshot is missing source_id")
    input_sha = str(snapshot.get("input_sha256") or "")
    if len(input_sha) != 64 or any(char not in string.hexdigits for char in input_sha):
        raise SourceWriterError("adapted snapshot has invalid input_sha256")
    items = list(snapshot.get("items") or [])
    ids: list[str] = []
    for item in items:
        if item.get("source_id") != source_id:
            raise SourceWriterError(f"adapted item source_id mismatch for {source_id}")
        inbox_id = str(item.get("inbox_id") or "")
        if not inbox_id:
            raise SourceWriterError(f"adapted item is missing inbox_id for {source_id}")
        ids.append(inbox_id)
    if len(ids) != len(set(ids)):
        raise SourceWriterError(f"adapted snapshot contains duplicate stable IDs: {source_id}")
    return source_id, items


def _semantic_value(item: dict[str, Any], field: str) -> Any:
    value = item.get(field)
    if field in {"priority_score", "event_year"}:
        return value
    return "" if value is None else value


def _same_source_content(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    if any(
        _semantic_value(expected, field) != _semantic_value(actual, field)
        for field in WRITER_FIELDS
    ):
        return False
    return item_payload_hash(expected) == item_payload_hash(actual)


def _lifecycle(row: dict[str, Any]) -> dict[str, Any]:
    return {field: row.get(field) for field in LIFECYCLE_FIELDS}


def _audit_connection(conn: sqlite3.Connection) -> dict[str, Any]:
    integrity_rows = [row[0] for row in conn.execute("PRAGMA integrity_check")]
    fk_rows = [list(row) for row in conn.execute("PRAGMA foreign_key_check")]
    return {
        "integrity": integrity_rows,
        "foreign_key_violations": fk_rows,
        "table_counts": table_counts(conn),
    }


def _require_healthy(audit: dict[str, Any], *, label: str) -> None:
    if audit["integrity"] != ["ok"]:
        raise SourceWriterError(f"{label} integrity_check failed: {audit['integrity']}")
    if audit["foreign_key_violations"]:
        raise SourceWriterError(f"{label} foreign_key_check failed")


def _domain_counts(audit: dict[str, Any]) -> dict[str, int]:
    return {
        table: count
        for table, count in audit["table_counts"].items()
        if table != INBOX_TABLE
    }


def _inbox_only_authorizer(
    action: int,
    object_name: str | None,
    _column: str | None,
    _database: str | None,
    _trigger: str | None,
) -> int:
    write_actions = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}
    if action in write_actions and object_name != INBOX_TABLE:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _reconcile_in_transaction(
    conn: sqlite3.Connection,
    snapshot: dict[str, Any],
    *,
    observation_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    source_id, items = _validate_snapshot(snapshot)
    if inbox_schema_version(conn, ensure_schema=False) != INBOX_SCHEMA_VERSION:
        raise SourceWriterError("review inbox schema v2 is required; B1-2 does not migrate schema")

    rows_before = inbox_rows(conn, status=None, ensure_schema=False)
    by_id_before = {row["inbox_id"]: row for row in rows_before}
    source_before = [row for row in rows_before if row["source_id"] == source_id]
    lifecycle_before = {row["inbox_id"]: _lifecycle(row) for row in source_before}

    expected_by_id: dict[str, dict[str, Any]] = {}
    changed_ids: list[str] = []
    unchanged_ids: list[str] = []
    for item in items:
        expected = normalized_item(item, observation_id)
        expected_by_id[expected["inbox_id"]] = expected
        existing = by_id_before.get(expected["inbox_id"])
        if existing and existing["source_id"] != source_id:
            raise SourceWriterError(
                f"stable ID collision across sources: {expected['inbox_id']}"
            )
        if existing and _same_source_content(expected, existing):
            unchanged_ids.append(expected["inbox_id"])
        else:
            changed_ids.append(expected["inbox_id"])

    if changed_ids:
        changed_items = [item for item in items if item["inbox_id"] in set(changed_ids)]
        upsert_inbox_items(conn, changed_items, ensure_schema=False)
        conn.executemany(
            "UPDATE review_inbox_items SET last_seen_at = ? WHERE inbox_id = ?",
            [(observation_id, inbox_id) for inbox_id in changed_ids],
        )

    rows_after = inbox_rows(conn, status=None, ensure_schema=False)
    source_after = [row for row in rows_after if row["source_id"] == source_id]
    seen_ids = set(expected_by_id)
    current = [row for row in source_after if row["inbox_id"] in seen_ids]
    stale_candidates = [
        {
            "inbox_id": row["inbox_id"],
            "status": row["status"],
            "reason": "not_seen_in_observation",
        }
        for row in source_after
        if row["inbox_id"] not in seen_ids and row["status"] == "pending"
    ]
    lifecycle_retained = [
        {
            "inbox_id": row["inbox_id"],
            "status": row["status"],
            "reason": "lifecycle_retained_after_source_absence",
        }
        for row in source_after
        if row["inbox_id"] not in seen_ids and row["status"] != "pending"
    ]
    classified_ids = {row["inbox_id"] for row in current}
    classified_ids.update(row["inbox_id"] for row in stale_candidates)
    classified_ids.update(row["inbox_id"] for row in lifecycle_retained)
    unmapped = sorted({row["inbox_id"] for row in source_after} - classified_ids)

    lifecycle_after = {row["inbox_id"]: _lifecycle(row) for row in source_after}
    lifecycle_mismatches = [
        inbox_id
        for inbox_id, before in lifecycle_before.items()
        if lifecycle_after.get(inbox_id) != before
    ]
    if lifecycle_mismatches:
        raise SourceWriterError(
            "source reconciliation changed lifecycle fields: " + ", ".join(lifecycle_mismatches)
        )
    if unmapped:
        raise SourceWriterError("source reconciliation left unmapped rows: " + ", ".join(unmapped))

    parity = build_parity_report(
        [snapshot],
        {
            "source": f"master_rdb.review_inbox_items.current:{observation_id}",
            "items": current,
        },
    )
    if not parity["summary"]["parity"]:
        raise SourceWriterError("source-scoped parity failed")

    reconciliation = {
        "source_id": source_id,
        "observation_id": observation_id,
        "selection_mode": _selection_mode(snapshot),
        "seen_ids": sorted(seen_ids),
        "changed_ids": sorted(changed_ids),
        "unchanged_ids": sorted(unchanged_ids),
        "stale_candidates": stale_candidates,
        "lifecycle_retained": lifecycle_retained,
        "summary": {
            "seen_count": len(seen_ids),
            "changed_count": len(changed_ids),
            "unchanged_count": len(unchanged_ids),
            "stale_candidate_count": len(stale_candidates),
            "lifecycle_retained_count": len(lifecycle_retained),
            "unmapped_count": len(unmapped),
        },
    }
    return reconciliation, parity


def run_source_shadow(
    *,
    store: ArtifactStore,
    adapted_snapshot: dict[str, Any],
    observation_id: str,
    public_projection_digest: Callable[[Path], str],
    flags: SourceWriterFlags | None = None,
    work_dir: Path | None = None,
    expected_rstart_checksum: str | None = None,
) -> dict[str, Any]:
    """Apply one frozen adapted snapshot to a temporary DB and CAS-publish it."""

    flags = flags or SourceWriterFlags.from_env()
    if not observation_id.strip():
        raise SourceWriterError("observation_id is required")
    selection_mode = _selection_mode(adapted_snapshot)
    flags.require_shadow_run(selection_mode)
    _validate_snapshot(adapted_snapshot)

    rstart = store.status()
    if len(rstart.checksum) != 64 or any(
        char not in string.hexdigits for char in rstart.checksum
    ):
        raise SourceWriterError("artifact status returned an invalid Rstart checksum")
    if expected_rstart_checksum and rstart.checksum != expected_rstart_checksum:
        raise SourceWriterError(
            "Rstart checksum does not match the operator-fixed expectation: "
            f"expected={expected_rstart_checksum} actual={rstart.checksum}"
        )

    if work_dir is not None:
        Path(work_dir).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work_dir) as tmp:
        tmp_path = Path(tmp)
        working_db = tmp_path / "working.sqlite"
        verified_db = tmp_path / "verified.sqlite"
        store.fetch(working_db)
        if file_sha256(working_db) != rstart.checksum:
            raise SourceWriterError("fetched database checksum does not match Rstart")

        public_before = public_projection_digest(working_db)
        conn = connect_existing(working_db, isolation_level=None)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            before_audit = _audit_connection(conn)
            _require_healthy(before_audit, label="Rstart")
            if inbox_schema_version(conn) != INBOX_SCHEMA_VERSION:
                raise SourceWriterError(
                    "review inbox schema v2 is required; B1-2 does not migrate schema"
                )
            conn.set_authorizer(_inbox_only_authorizer)
            conn.execute("BEGIN IMMEDIATE")
            try:
                reconciliation, parity = _reconcile_in_transaction(
                    conn,
                    adapted_snapshot,
                    observation_id=observation_id,
                )
                after_audit = _audit_connection(conn)
                _require_healthy(after_audit, label="candidate")
                if _domain_counts(after_audit) != _domain_counts(before_audit):
                    raise SourceWriterError("source writer changed non-inbox table counts")
                if reconciliation["changed_ids"]:
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

        public_after = public_projection_digest(working_db)
        if public_after != public_before:
            raise SourceWriterError("source writer changed the public projection")

        base_report = {
            "generated_by": "review_inbox_source_writer.py",
            "flags": asdict(flags),
            "rstart": asdict(rstart),
            "operator_expected_rstart_checksum": expected_rstart_checksum or "",
            "observation_id": observation_id,
            "lineage": {
                "source_id": adapted_snapshot["source_id"],
                "input_path": adapted_snapshot.get("input_path") or "",
                "input_sha256": adapted_snapshot["input_sha256"],
                "input_size_bytes": adapted_snapshot.get("input_size_bytes"),
                "adapter_snapshot_path": adapted_snapshot.get("adapter_snapshot_path") or "",
                "adapter_snapshot_sha256": adapted_snapshot.get("adapter_snapshot_sha256") or "",
                "selection": adapted_snapshot.get("selection") or {"mode": selection_mode},
                "stable_ids": reconciliation["seen_ids"],
            },
            "reconciliation": reconciliation,
            "parity": parity,
            "audit": {
                "integrity": after_audit["integrity"],
                "foreign_key_violation_count": len(after_audit["foreign_key_violations"]),
                "domain_table_counts_unchanged": True,
                "public_projection_unchanged": True,
            },
        }
        if not reconciliation["changed_ids"]:
            return {
                **base_report,
                "published": False,
                "no_op": True,
                "rend": asdict(rstart),
            }

        candidate_checksum = file_sha256(working_db)
        remote_before_publish = store.status()
        if remote_before_publish.checksum != rstart.checksum:
            raise CasConflictError(
                "remote checksum changed after Rstart; candidate was not published"
            )
        rend = store.publish(working_db, expected_remote_checksum=rstart.checksum)
        if rend.checksum != candidate_checksum:
            raise SourceWriterError("published artifact checksum does not match the candidate")
        final_status = store.status()
        if final_status != rend:
            raise SourceWriterError("remote status does not match the published artifact")

        store.fetch(verified_db)
        if file_sha256(verified_db) != rend.checksum:
            raise SourceWriterError("verification fetch checksum does not match Rend")
        verify_conn = connect_existing(verified_db)
        try:
            verify_conn.execute("PRAGMA foreign_keys = ON")
            verify_audit = _audit_connection(verify_conn)
            _require_healthy(verify_audit, label="Rend refetch")
        finally:
            verify_conn.close()
        if _domain_counts(verify_audit) != _domain_counts(before_audit):
            raise SourceWriterError("Rend refetch changed non-inbox table counts")
        if public_projection_digest(verified_db) != public_before:
            raise SourceWriterError("Rend refetch changed the public projection")

        return {
            **base_report,
            "published": True,
            "no_op": False,
            "candidate_checksum": candidate_checksum,
            "rend": asdict(rend),
            "verification_fetch": {
                "checksum": file_sha256(verified_db),
                "integrity": verify_audit["integrity"],
                "foreign_key_violation_count": len(verify_audit["foreign_key_violations"]),
                "public_projection_unchanged": True,
            },
        }
