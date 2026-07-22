#!/usr/bin/env python3
"""CAS-safe writer for staged review inbox lifecycle decisions."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import string
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from master_rdb.master_db import connect_existing, file_sha256
from review_inbox import (
    DECISIONS,
    DECISION_ROUTES,
    INBOX_SCHEMA_VERSION,
    inbox_rows,
    inbox_schema_version,
    record_inbox_decision,
)
from review_inbox_adapters.source_writer import (
    ArtifactStore,
    CasConflictError,
    SourceWriterError,
    _audit_connection,
    _domain_counts,
    _inbox_only_authorizer,
    _require_healthy,
)


EXPECTED_GENERATOR = "review_inbox_decision_stage.py"
EXPECTED_WRITE_MODE = "staged_only"


@dataclass(frozen=True)
class DecisionWriterFlags:
    decision_write_mode: str = "off"
    cas_publish_enabled: bool = False
    reader_mode: str = "legacy"
    legacy_writer_enabled: bool = True

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "DecisionWriterFlags":
        env = os.environ if environ is None else environ
        return cls(
            decision_write_mode=str(env.get("REVIEW_INBOX_DECISION_WRITE_MODE", "off")).strip(),
            cas_publish_enabled=_env_bool(env, "REVIEW_INBOX_CAS_PUBLISH_ENABLED", False),
            reader_mode=str(env.get("REVIEW_INBOX_READER_MODE", "legacy")).strip(),
            legacy_writer_enabled=_env_bool(env, "REVIEW_INBOX_LEGACY_WRITER_ENABLED", True),
        )

    def require_write(self, update_count: int) -> None:
        if self.decision_write_mode not in {"off", "canary", "bulk"}:
            raise SourceWriterError(
                f"unsupported review inbox decision write mode: {self.decision_write_mode}"
            )
        if self.decision_write_mode == "off":
            raise SourceWriterError("review inbox decision writing is off")
        if self.decision_write_mode == "canary" and update_count != 1:
            raise SourceWriterError("canary decision write requires exactly one update")
        if not self.cas_publish_enabled:
            raise SourceWriterError("review inbox CAS publication is off")
        if self.reader_mode != "legacy":
            raise SourceWriterError("B2-3c cannot change the review inbox reader")
        if not self.legacy_writer_enabled:
            raise SourceWriterError("B2-3c cannot stop the legacy writer")


def _env_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise SourceWriterError(f"invalid boolean environment value for {name}: {raw!r}")


def _require_timestamp(value: Any) -> str:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceWriterError(f"invalid decided_at timestamp: {text!r}") from exc
    if parsed.tzinfo is None:
        raise SourceWriterError("decided_at timestamp must include a timezone")
    return text


def validate_decision_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    if payload.get("schema_version") != 1:
        raise SourceWriterError("decision stage schema_version must be 1")
    if payload.get("generated_by") != EXPECTED_GENERATOR:
        raise SourceWriterError("decision stage generated_by is not trusted")
    if payload.get("write_mode") != EXPECTED_WRITE_MODE:
        raise SourceWriterError("decision stage write_mode must be staged_only")
    updates = payload.get("inbox_decision_updates")
    if not isinstance(updates, list) or not updates:
        raise SourceWriterError("decision stage must contain at least one update")
    if payload.get("decision_count") != len(updates):
        raise SourceWriterError("decision_count does not match staged updates")

    normalized: list[dict[str, str]] = []
    ids: list[str] = []
    for raw in updates:
        if not isinstance(raw, dict):
            raise SourceWriterError("decision update must be an object")
        update = {
            "inbox_id": str(raw.get("inbox_id") or "").strip(),
            "decision": str(raw.get("decision") or "").strip(),
            "decided_by": str(raw.get("decided_by") or "").strip(),
            "decided_at": _require_timestamp(raw.get("decided_at")),
            "decision_route": str(raw.get("decision_route") or "").strip(),
        }
        if not update["inbox_id"]:
            raise SourceWriterError("decision update is missing inbox_id")
        if update["decision"] not in DECISIONS:
            raise SourceWriterError(f"unsupported decision: {update['decision']}")
        if update["decision_route"] not in DECISION_ROUTES:
            raise SourceWriterError(f"unsupported decision route: {update['decision_route']}")
        if not update["decided_by"]:
            raise SourceWriterError("decision update is missing decided_by")
        ids.append(update["inbox_id"])
        normalized.append(update)
    duplicates = sorted({value for value in ids if ids.count(value) > 1})
    if duplicates:
        raise SourceWriterError("duplicate staged decision IDs: " + ", ".join(duplicates))
    return normalized


def load_decision_payload(path: Path) -> tuple[dict[str, Any], str]:
    data = Path(path).read_bytes()
    try:
        payload = json.loads(data)
    except ValueError as exc:
        raise SourceWriterError(f"invalid decision stage JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise SourceWriterError("decision stage root must be an object")
    return payload, hashlib.sha256(data).hexdigest()


def _expected_lifecycle(update: dict[str, str]) -> dict[str, Any]:
    closed_at = update["decided_at"] if update["decision"] in {"accepted", "rejected"} else None
    return {
        "status": update["decision"],
        "decision": update["decision"],
        "decided_by": update["decided_by"],
        "decided_at": update["decided_at"],
        "closed_at": closed_at,
        "decision_route": update["decision_route"],
    }


def _current_lifecycle(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in ("status", "decision", "decided_by", "decided_at", "closed_at", "decision_route")
    }


def _apply_updates(
    conn: sqlite3.Connection,
    updates: list[dict[str, str]],
    expected_targets: Mapping[str, Mapping[str, str]],
) -> dict[str, Any]:
    if inbox_schema_version(conn, ensure_schema=False) != INBOX_SCHEMA_VERSION:
        raise SourceWriterError("review inbox schema v2 is required; decision writer does not migrate")
    rows = {row["inbox_id"]: row for row in inbox_rows(conn, status=None, ensure_schema=False)}
    changed: list[str] = []
    unchanged: list[str] = []
    for update in updates:
        inbox_id = update["inbox_id"]
        row = rows.get(inbox_id)
        if row is None:
            raise SourceWriterError(f"review inbox decision target not found: {inbox_id}")
        expected = expected_targets.get(inbox_id)
        if expected is None:
            raise SourceWriterError(f"decision target was not operator-approved: {inbox_id}")
        for field in ("source_id", "source_key"):
            if str(row.get(field) or "") != str(expected.get(field) or ""):
                raise SourceWriterError(f"decision target {field} mismatch: {inbox_id}")

        wanted = _expected_lifecycle(update)
        current = _current_lifecycle(row)
        if row.get("decision") is not None:
            if current == wanted:
                unchanged.append(inbox_id)
                continue
            raise SourceWriterError(f"competing existing decision for {inbox_id}")
        if current != {
            "status": "pending",
            "decision": None,
            "decided_by": None,
            "decided_at": None,
            "closed_at": None,
            "decision_route": None,
        }:
            raise SourceWriterError(f"partial or non-pending lifecycle for {inbox_id}")
        record_inbox_decision(
            conn,
            inbox_id,
            decision=update["decision"],
            decided_by=update["decided_by"],
            decided_at=update["decided_at"],
            decision_route=update["decision_route"],
            ensure_schema=False,
        )
        changed.append(inbox_id)
    return {"changed_ids": changed, "unchanged_ids": unchanged}


def run_decision_write(
    *,
    store: ArtifactStore,
    staged_payload: dict[str, Any],
    staged_payload_sha256: str,
    expected_targets: Mapping[str, Mapping[str, str]],
    public_projection_digest: Callable[[Path], str],
    expected_rstart_checksum: str,
    flags: DecisionWriterFlags,
    work_dir: Path | None = None,
) -> dict[str, Any]:
    updates = validate_decision_payload(staged_payload)
    flags.require_write(len(updates))
    if len(expected_rstart_checksum) != 64 or any(
        char not in string.hexdigits for char in expected_rstart_checksum
    ):
        raise SourceWriterError("operator-fixed Rstart checksum must be SHA-256")
    if set(expected_targets) != {update["inbox_id"] for update in updates}:
        raise SourceWriterError("expected decision targets do not exactly match staged updates")

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

        public_before = public_projection_digest(working)
        conn = connect_existing(working, isolation_level=None)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            before_audit = _audit_connection(conn)
            _require_healthy(before_audit, label="Rstart")
            if inbox_schema_version(conn, ensure_schema=False) != INBOX_SCHEMA_VERSION:
                raise SourceWriterError("review inbox schema v2 is required; decision writer does not migrate")
            conn.set_authorizer(_inbox_only_authorizer)
            conn.execute("BEGIN IMMEDIATE")
            try:
                result = _apply_updates(conn, updates, expected_targets)
                after_audit = _audit_connection(conn)
                _require_healthy(after_audit, label="candidate")
                if _domain_counts(after_audit) != _domain_counts(before_audit):
                    raise SourceWriterError("decision writer changed non-inbox table counts")
                if result["changed_ids"]:
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
            raise SourceWriterError("decision writer changed the public projection")
        base = {
            "generated_by": "review_inbox_decision_writer.py",
            "flags": asdict(flags),
            "staged_payload_sha256": staged_payload_sha256,
            "decision_count": len(updates),
            "targets": [
                {"inbox_id": update["inbox_id"], **dict(expected_targets[update["inbox_id"]])}
                for update in updates
            ],
            "rstart": asdict(rstart),
            "operator_expected_rstart_checksum": expected_rstart_checksum,
            "decision_write": result,
            "audit": {
                "integrity": after_audit["integrity"],
                "foreign_key_violation_count": len(after_audit["foreign_key_violations"]),
                "domain_table_counts_unchanged": True,
                "public_projection_unchanged": True,
            },
        }
        if not result["changed_ids"]:
            return {**base, "published": False, "no_op": True, "rend": asdict(rstart)}

        candidate_checksum = file_sha256(working)
        if store.status().checksum != rstart.checksum:
            raise CasConflictError("remote checksum changed after Rstart; decision was not published")
        rend = store.publish(working, expected_remote_checksum=rstart.checksum)
        if rend.checksum != candidate_checksum:
            raise SourceWriterError("published artifact checksum does not match decision candidate")
        if store.status() != rend:
            raise SourceWriterError("remote status does not match published decision artifact")
        store.fetch(verified)
        if file_sha256(verified) != rend.checksum:
            raise SourceWriterError("decision verification fetch checksum does not match Rend")
        verify_conn = connect_existing(verified)
        try:
            verify_conn.execute("PRAGMA foreign_keys = ON")
            verify_audit = _audit_connection(verify_conn)
            _require_healthy(verify_audit, label="Rend refetch")
            verified_rows = {
                row["inbox_id"]: row
                for row in inbox_rows(verify_conn, status=None, ensure_schema=False)
            }
        finally:
            verify_conn.close()
        if _domain_counts(verify_audit) != _domain_counts(before_audit):
            raise SourceWriterError("Rend refetch changed non-inbox table counts")
        if public_projection_digest(verified) != public_before:
            raise SourceWriterError("Rend refetch changed the public projection")
        for update in updates:
            if _current_lifecycle(verified_rows[update["inbox_id"]]) != _expected_lifecycle(update):
                raise SourceWriterError("Rend refetch decision lifecycle mismatch")
        return {
            **base,
            "published": True,
            "no_op": False,
            "candidate_checksum": candidate_checksum,
            "rend": asdict(rend),
            "verification_fetch": {
                "checksum": file_sha256(verified),
                "integrity": verify_audit["integrity"],
                "foreign_key_violation_count": len(verify_audit["foreign_key_violations"]),
                "public_projection_unchanged": True,
                "decision_lifecycle_matches": True,
            },
        }
