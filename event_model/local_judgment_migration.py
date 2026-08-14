"""Additive, idempotent schema migration for local-judgment contract v1."""

from __future__ import annotations

from datetime import datetime, timezone


MIGRATION_VERSION = 1
MIGRATION_NAME = "local_judgment_contract_v1"
EVENT_INBOX_MIGRATION_VERSION = 2
EVENT_INBOX_MIGRATION_NAME = "event_inbox_candidate_v1"
CLAIM_MIGRATION_VERSION = 3
CLAIM_MIGRATION_NAME = "review_claim_ledger_v1"
TABLES = {
    "canonical_decision_ledger", "review_queue_state_ledger",
    "review_hold_ledger", "local_judgment_schema_migrations",
}

DDL = """
CREATE TABLE IF NOT EXISTS canonical_decision_ledger (
  decision_id TEXT PRIMARY KEY,
  schema_version INTEGER NOT NULL,
  packet_id TEXT NOT NULL,
  packet_sha256 TEXT NOT NULL,
  inbox_id TEXT NOT NULL,
  domain TEXT NOT NULL,
  lane TEXT NOT NULL,
  source_id TEXT NOT NULL,
  source_key TEXT NOT NULL,
  source_payload_hash TEXT NOT NULL,
  action TEXT NOT NULL,
  queue_state_before TEXT NOT NULL,
  queue_state_after TEXT NOT NULL,
  reason_code TEXT,
  hold_mode TEXT,
  next_eligible_at TEXT,
  hold_packet_json TEXT,
  payload_json TEXT NOT NULL,
  actor_type TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  decision_channel TEXT NOT NULL,
  decided_at TEXT NOT NULL,
  prior_agent_attempt_id TEXT,
  open_hold_id TEXT,
  adjudication_batch_id TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_queue_state_ledger (
  inbox_id TEXT PRIMARY KEY,
  domain TEXT NOT NULL,
  lane TEXT NOT NULL,
  queue_state TEXT NOT NULL,
  decision_id TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_hold_ledger (
  hold_id TEXT PRIMARY KEY,
  decision_id TEXT NOT NULL UNIQUE,
  inbox_id TEXT NOT NULL,
  domain TEXT NOT NULL,
  lane TEXT NOT NULL,
  hold_mode TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  reason_detail TEXT,
  required_resolution_type TEXT,
  allowed_actions TEXT NOT NULL,
  candidate_ids TEXT,
  candidate_set_sha256 TEXT,
  prior_agent_attempt_id TEXT NOT NULL,
  grouping_fingerprint TEXT NOT NULL,
  status TEXT NOT NULL,
  queue_state TEXT NOT NULL,
  next_eligible_at TEXT,
  hold_packet_json TEXT,
  opened_at TEXT NOT NULL,
  expires_at TEXT,
  closed_at TEXT,
  resolved_by_decision_id TEXT
);
CREATE TABLE IF NOT EXISTS local_judgment_schema_migrations (
  version INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  applied_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_local_judgment_decision_inbox
ON canonical_decision_ledger(inbox_id);
CREATE INDEX IF NOT EXISTS idx_local_judgment_hold_open
ON review_hold_ledger(inbox_id, status);
"""

EVENT_INBOX_COLUMNS = {
    "contract_domain": "TEXT",
    "contract_lane": "TEXT",
    "first_eligible_at": "TEXT",
    "expires_at": "TEXT",
    "superseded_by_inbox_id": "TEXT",
    "depends_on_inbox_id": "TEXT",
    "revision_family_key": "TEXT",
    "revision": "INTEGER",
}


def migrate_local_judgment_contract(conn):
    """Create J0 tables only; never alter review_inbox_items or domain rows."""
    before = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.executescript(DDL)
    conn.execute(
        """
        INSERT OR IGNORE INTO local_judgment_schema_migrations(version, name, applied_at)
        VALUES (?, ?, ?)
        """,
        (MIGRATION_VERSION, MIGRATION_NAME, datetime.now(timezone.utc).isoformat()),
    )
    after = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return {
        "migration_version": MIGRATION_VERSION,
        "migration_name": MIGRATION_NAME,
        "tables_added": sorted(TABLES - before),
        "tables_present": sorted(TABLES & after),
    }


def migrate_event_inbox_candidate(conn):
    """Add E0 columns without changing any pre-existing inbox values."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(review_inbox_items)")}
    if not columns:
        raise ValueError("review_inbox_items is required before event inbox migration")
    added = []
    for name, declaration in EVENT_INBOX_COLUMNS.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE review_inbox_items ADD COLUMN {name} {declaration}")
            added.append(name)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_review_inbox_contract_lane "
        "ON review_inbox_items(contract_domain, contract_lane, status, expires_at)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO local_judgment_schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
        (EVENT_INBOX_MIGRATION_VERSION, EVENT_INBOX_MIGRATION_NAME, datetime.now(timezone.utc).isoformat()),
    )
    return {"migration_version": EVENT_INBOX_MIGRATION_VERSION, "migration_name": EVENT_INBOX_MIGRATION_NAME, "columns_added": added}


def migrate_review_claim_ledger(conn):
    """Add the operational claim table without changing contract state."""
    conn.execute("""CREATE TABLE IF NOT EXISTS review_claim_ledger (
      inbox_id TEXT PRIMARY KEY, claimed_by TEXT NOT NULL, claim_kind TEXT NOT NULL,
      claimed_at TEXT NOT NULL, expires_at TEXT NOT NULL, batch_id TEXT)""")
    conn.execute("INSERT OR IGNORE INTO local_judgment_schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                 (CLAIM_MIGRATION_VERSION, CLAIM_MIGRATION_NAME, datetime.now(timezone.utc).isoformat()))
    return {"migration_version": CLAIM_MIGRATION_VERSION, "migration_name": CLAIM_MIGRATION_NAME}
