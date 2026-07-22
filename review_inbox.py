#!/usr/bin/env python3
"""Shared review inbox storage and JSON projection.

The inbox is the consolidation point for new review items. It does not replace
source-specific apply scripts; it gives the review console one place to read
new pending work by kind while downstream application remains explicit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from master_rdb.master_db import MASTER_DB, connect_existing, stable_id


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT_JSON = DATA / "review_inbox.json"

INBOX_SCHEMA_VERSION = 2
TIME_SCOPES = {"future", "historical", "reference"}
DECISIONS = {"accepted", "rejected", "hold", "needs_research"}
DECISION_ROUTES = {"change_request", "domain_stage", "research_followup", "no_apply"}
FUTURE_KINDS = {
    "current_year_confirmation",
    "predicted_date",
    "official_source",
    "source_url",
    "venue_review",
    "occurrence_creation",
    "rare_signal",
}
HISTORICAL_KINDS = {"historical_reference", "historical_quality", "youtube_evidence"}

V2_COLUMNS = {
    "time_scope": "TEXT NOT NULL DEFAULT 'reference'",
    "decision": "TEXT",
    "decided_by": "TEXT",
    "decided_at": "TEXT",
    "closed_at": "TEXT",
    "decision_route": "TEXT",
    "source_payload_hash": "TEXT NOT NULL DEFAULT ''",
    "last_seen_at": "TEXT NOT NULL DEFAULT ''",
}

INBOX_SCHEMA = """
CREATE TABLE IF NOT EXISTS review_inbox_items (
  inbox_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  domain TEXT NOT NULL,
  time_scope TEXT NOT NULL DEFAULT 'reference',
  priority_label TEXT,
  priority_score REAL,
  title TEXT NOT NULL,
  event_name TEXT,
  venue TEXT,
  event_year INTEGER,
  source_id TEXT NOT NULL,
  source_key TEXT NOT NULL,
  source_url TEXT,
  recommended_action TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  decision TEXT,
  decided_by TEXT,
  decided_at TEXT,
  closed_at TEXT,
  decision_route TEXT,
  source_payload_hash TEXT NOT NULL DEFAULT '',
  last_seen_at TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_review_inbox_status
ON review_inbox_items(status, kind, priority_score);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_inbox_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(INBOX_SCHEMA)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(review_inbox_items)")}
    if "time_scope" in columns:
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_review_inbox_scope_status
            ON review_inbox_items(time_scope, status, priority_score)
            """
        )


def inbox_columns(conn: sqlite3.Connection, *, ensure_schema: bool = True) -> set[str]:
    if ensure_schema:
        ensure_inbox_schema(conn)
    return {row[1] for row in conn.execute("PRAGMA table_info(review_inbox_items)")}


def inbox_schema_version(conn: sqlite3.Connection, *, ensure_schema: bool = True) -> int:
    return INBOX_SCHEMA_VERSION if set(V2_COLUMNS).issubset(
        inbox_columns(conn, ensure_schema=ensure_schema)
    ) else 1


def payload_hash(payload_json: str) -> str:
    try:
        payload = json.loads(payload_json or "{}")
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except ValueError:
        canonical = payload_json or ""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def infer_time_scope(kind: str) -> str:
    if kind in FUTURE_KINDS:
        return "future"
    if kind in HISTORICAL_KINDS:
        return "historical"
    return "reference"


def migrate_inbox_schema_v2(conn: sqlite3.Connection) -> bool:
    """Explicitly migrate an existing inbox table to v2.

    Callers must own the surrounding transaction and approval/backup boundary.
    Ordinary reads and exports intentionally do not invoke this migration.
    """
    columns = inbox_columns(conn)
    changed = False
    added_time_scope = "time_scope" not in columns
    for name, declaration in V2_COLUMNS.items():
        if name in columns:
            continue
        conn.execute(f"ALTER TABLE review_inbox_items ADD COLUMN {name} {declaration}")
        changed = True

    conn.execute(
        """
        UPDATE review_inbox_items
        SET last_seen_at = COALESCE(NULLIF(last_seen_at, ''), updated_at),
            time_scope = COALESCE(NULLIF(time_scope, ''), 'reference')
        """
    )
    if added_time_scope:
        for inbox_id, kind in conn.execute("SELECT inbox_id, kind FROM review_inbox_items"):
            conn.execute(
                "UPDATE review_inbox_items SET time_scope = ? WHERE inbox_id = ?",
                (infer_time_scope(kind), inbox_id),
            )
    for inbox_id, payload_json in conn.execute(
        "SELECT inbox_id, payload_json FROM review_inbox_items WHERE source_payload_hash = ''"
    ):
        conn.execute(
            "UPDATE review_inbox_items SET source_payload_hash = ? WHERE inbox_id = ?",
            (payload_hash(payload_json), inbox_id),
        )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_review_inbox_scope_status
        ON review_inbox_items(time_scope, status, priority_score)
        """
    )
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone():
        conn.execute(
            """
            INSERT OR IGNORE INTO schema_migrations(version, name, applied_at)
            VALUES (?, ?, ?)
            """,
            (INBOX_SCHEMA_VERSION, "review_inbox_v2", now_iso()),
        )
    return changed


def inbox_id_for(item: dict[str, Any]) -> str:
    return item.get("inbox_id") or stable_id(
        "inbox",
        item.get("kind") or "",
        item.get("source_id") or "",
        item.get("source_key") or "",
    )


def normalized_item(item: dict[str, Any], now: str) -> dict[str, Any]:
    inbox_id = inbox_id_for(item)
    payload = item.get("payload")
    if payload is None:
        payload = {
            key: value
            for key, value in item.items()
            if key not in {"payload", "created_at", "updated_at"}
        }
    time_scope = item.get("time_scope") or infer_time_scope(item.get("kind") or "")
    if time_scope not in TIME_SCOPES:
        raise ValueError(f"unsupported review inbox time_scope: {time_scope}")
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return {
        "inbox_id": inbox_id,
        "kind": item["kind"],
        "domain": item.get("domain") or "その他",
        "time_scope": time_scope,
        "priority_label": item.get("priority_label") or "",
        "priority_score": item.get("priority_score"),
        "title": item["title"],
        "event_name": item.get("event_name") or "",
        "venue": item.get("venue") or "",
        "event_year": item.get("event_year"),
        "source_id": item["source_id"],
        "source_key": item["source_key"],
        "source_url": item.get("source_url") or "",
        "recommended_action": item.get("recommended_action") or "",
        "status": item.get("status") or "pending",
        "source_payload_hash": payload_hash(payload_json),
        "last_seen_at": now,
        "payload_json": payload_json,
        "created_at": item.get("created_at") or now,
        "updated_at": item.get("updated_at") or now,
    }


def upsert_inbox_items(
    conn: sqlite3.Connection,
    items: list[dict[str, Any]],
    *,
    ensure_schema: bool = True,
) -> list[dict[str, Any]]:
    """Upsert items, optionally trusting a caller-owned schema/transaction boundary."""
    if ensure_schema:
        ensure_inbox_schema(conn)
    now = now_iso()
    normalized = [normalized_item(item, now) for item in items]
    is_v2 = inbox_schema_version(conn, ensure_schema=False) == INBOX_SCHEMA_VERSION
    for item in normalized:
        if not is_v2:
            conn.execute(
                """
                INSERT INTO review_inbox_items(
                  inbox_id, kind, domain, priority_label, priority_score, title,
                  event_name, venue, event_year, source_id, source_key, source_url,
                  recommended_action, status, payload_json, created_at, updated_at
                ) VALUES (
                  :inbox_id, :kind, :domain, :priority_label, :priority_score, :title,
                  :event_name, :venue, :event_year, :source_id, :source_key, :source_url,
                  :recommended_action, :status, :payload_json, :created_at, :updated_at
                )
                ON CONFLICT(inbox_id) DO UPDATE SET
                  kind = excluded.kind,
                  domain = excluded.domain,
                  priority_label = excluded.priority_label,
                  priority_score = excluded.priority_score,
                  title = excluded.title,
                  event_name = excluded.event_name,
                  venue = excluded.venue,
                  event_year = excluded.event_year,
                  source_id = excluded.source_id,
                  source_key = excluded.source_key,
                  source_url = excluded.source_url,
                  recommended_action = excluded.recommended_action,
                  status = CASE
                    WHEN review_inbox_items.status = 'pending' THEN excluded.status
                    ELSE review_inbox_items.status
                  END,
                  payload_json = excluded.payload_json,
                  updated_at = excluded.updated_at
                """,
                item,
            )
            continue
        conn.execute(
            """
            INSERT INTO review_inbox_items(
              inbox_id, kind, domain, time_scope, priority_label, priority_score, title,
              event_name, venue, event_year, source_id, source_key, source_url,
              recommended_action, status, source_payload_hash, last_seen_at,
              payload_json, created_at, updated_at
            ) VALUES (
              :inbox_id, :kind, :domain, :time_scope, :priority_label, :priority_score, :title,
              :event_name, :venue, :event_year, :source_id, :source_key, :source_url,
              :recommended_action, :status, :source_payload_hash, :last_seen_at,
              :payload_json, :created_at, :updated_at
            )
            ON CONFLICT(inbox_id) DO UPDATE SET
              kind = excluded.kind,
              domain = excluded.domain,
              time_scope = excluded.time_scope,
              priority_label = excluded.priority_label,
              priority_score = excluded.priority_score,
              title = excluded.title,
              event_name = excluded.event_name,
              venue = excluded.venue,
              event_year = excluded.event_year,
              source_id = excluded.source_id,
              source_key = excluded.source_key,
              source_url = excluded.source_url,
              recommended_action = excluded.recommended_action,
              status = CASE
                WHEN review_inbox_items.status = 'pending' THEN excluded.status
                ELSE review_inbox_items.status
              END,
              source_payload_hash = excluded.source_payload_hash,
              last_seen_at = excluded.last_seen_at,
              payload_json = excluded.payload_json,
              updated_at = excluded.updated_at
            """,
            item,
        )
    return normalized


def inbox_rows(
    conn: sqlite3.Connection,
    status: str | None = None,
    *,
    ensure_schema: bool = True,
) -> list[dict[str, Any]]:
    if ensure_schema:
        ensure_inbox_schema(conn)
    conn.row_factory = sqlite3.Row
    if inbox_schema_version(conn, ensure_schema=False) == INBOX_SCHEMA_VERSION:
        lifecycle_columns = """
               time_scope, decision, decided_by, decided_at, closed_at,
               decision_route, source_payload_hash, last_seen_at,
        """
    else:
        lifecycle_columns = """
               'reference' AS time_scope, NULL AS decision, NULL AS decided_by,
               NULL AS decided_at, NULL AS closed_at, NULL AS decision_route,
               '' AS source_payload_hash, updated_at AS last_seen_at,
        """
    query = """
        SELECT inbox_id, kind, domain, priority_label, priority_score, title,
               event_name, venue, event_year, source_id, source_key, source_url,
               recommended_action, status,
    """ + lifecycle_columns + """
               payload_json, created_at, updated_at
        FROM review_inbox_items
    """
    params: tuple[Any, ...] = ()
    if status:
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY COALESCE(priority_score, 0) DESC, updated_at DESC, inbox_id"
    rows = []
    for row in conn.execute(query, params):
        item = dict(row)
        try:
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
        except ValueError:
            item["payload"] = {}
        rows.append(item)
    return rows


def record_inbox_decision(
    conn: sqlite3.Connection,
    inbox_id: str,
    *,
    decision: str,
    decided_by: str,
    decision_route: str,
    decided_at: str | None = None,
    ensure_schema: bool = True,
) -> dict[str, Any]:
    if inbox_schema_version(conn, ensure_schema=ensure_schema) != INBOX_SCHEMA_VERSION:
        raise RuntimeError("review inbox schema v2 migration is required before recording decisions")
    if decision not in DECISIONS:
        raise ValueError(f"unsupported review inbox decision: {decision}")
    if decision_route not in DECISION_ROUTES:
        raise ValueError(f"unsupported review inbox decision_route: {decision_route}")
    if not decided_by.strip():
        raise ValueError("decided_by is required")
    timestamp = decided_at or now_iso()
    closed_at = timestamp if decision in {"accepted", "rejected"} else None
    cursor = conn.execute(
        """
        UPDATE review_inbox_items
        SET status = ?, decision = ?, decided_by = ?, decided_at = ?,
            closed_at = ?, decision_route = ?, updated_at = ?
        WHERE inbox_id = ?
        """,
        (decision, decision, decided_by, timestamp, closed_at, decision_route, timestamp, inbox_id),
    )
    if cursor.rowcount != 1:
        raise KeyError(f"review inbox item not found: {inbox_id}")
    return next(
        row
        for row in inbox_rows(conn, status=None, ensure_schema=ensure_schema)
        if row["inbox_id"] == inbox_id
    )


def clear_inbox_decision(conn: sqlite3.Connection, inbox_id: str) -> dict[str, Any]:
    if inbox_schema_version(conn) != INBOX_SCHEMA_VERSION:
        raise RuntimeError("review inbox schema v2 migration is required before clearing decisions")
    timestamp = now_iso()
    cursor = conn.execute(
        """
        UPDATE review_inbox_items
        SET status = 'pending', decision = NULL, decided_by = NULL,
            decided_at = NULL, closed_at = NULL, decision_route = NULL,
            updated_at = ?
        WHERE inbox_id = ?
        """,
        (timestamp, inbox_id),
    )
    if cursor.rowcount != 1:
        raise KeyError(f"review inbox item not found: {inbox_id}")
    return next(row for row in inbox_rows(conn, status=None) if row["inbox_id"] == inbox_id)


def export_inbox_json(
    db_path: Path = MASTER_DB,
    out_json: Path = OUT_JSON,
    status: str | None = "pending",
) -> dict[str, Any]:
    conn = connect_existing(db_path)
    try:
        rows = inbox_rows(conn, status=status)
    finally:
        conn.close()
    payload = {
        "generated_by": "review_inbox.py",
        "generated_at": now_iso(),
        "source": "master_rdb.review_inbox_items",
        "status_filter": status,
        "items": rows,
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-db", type=Path, default=MASTER_DB)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--status", default="pending")
    args = parser.parse_args()
    payload = export_inbox_json(args.master_db, args.out_json, status=args.status or None)
    print(f"review inbox export: {len(payload['items'])} items -> {args.out_json}")


if __name__ == "__main__":
    main()
