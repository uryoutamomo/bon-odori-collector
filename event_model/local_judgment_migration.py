"""Additive, idempotent schema migration for J0 local-judgment ledgers."""

from __future__ import annotations

from datetime import datetime, timezone


MIGRATION_VERSION = 1
MIGRATION_NAME = "local_judgment_contract_v1"
TABLES = {
    "canonical_decision_ledger",
    "review_queue_state_ledger",
    "review_hold_ledger",
    "local_judgment_schema_migrations",
}

DDL = """
CREATE TABLE IF NOT EXISTS canonical_decision_ledger (
  decision_id TEXT PRIMARY KEY, inbox_id TEXT NOT NULL, source_id TEXT NOT NULL,
  source_key TEXT NOT NULL, action TEXT NOT NULL, actor_type TEXT NOT NULL,
  actor_id TEXT NOT NULL, decision_channel TEXT NOT NULL, queue_state_before TEXT NOT NULL,
  queue_state_after TEXT NOT NULL, reason_code TEXT, hold_mode TEXT,
  next_eligible_at TEXT, packet_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_queue_state_ledger (
  inbox_id TEXT PRIMARY KEY, queue_state TEXT NOT NULL, decision_id TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_hold_ledger (
  hold_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL UNIQUE, inbox_id TEXT NOT NULL,
  reason_code TEXT NOT NULL, hold_mode TEXT NOT NULL, status TEXT NOT NULL,
  next_eligible_at TEXT, hold_packet_json TEXT, opened_at TEXT NOT NULL, closed_at TEXT
);
CREATE TABLE IF NOT EXISTS local_judgment_schema_migrations (
  version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_local_judgment_decision_inbox ON canonical_decision_ledger(inbox_id);
CREATE INDEX IF NOT EXISTS idx_local_judgment_hold_open ON review_hold_ledger(inbox_id, status);
"""


def migrate_local_judgment_contract(conn):
    """Create only new J0 tables.  It never alters review_inbox_items or domain rows."""
    before = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.executescript(DDL)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO local_judgment_schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
        (MIGRATION_VERSION, MIGRATION_NAME, now),
    )
    after = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return {"migration_version": MIGRATION_VERSION, "migration_name": MIGRATION_NAME, "tables_added": sorted(TABLES - before), "legacy_review_inbox_changed": False, "tables_present": sorted(TABLES & after)}
