"""Additive schema migration for X song identity/materialization contract v2."""

from __future__ import annotations

from datetime import datetime, timezone


MIGRATION_VERSION = 4
MIGRATION_NAME = "x_song_identity_v2"

DDL = """
CREATE TABLE IF NOT EXISTS x_song_resolution_decisions (
  decision_id TEXT PRIMARY KEY,
  observation_id TEXT NOT NULL,
  observation_sha256 TEXT NOT NULL,
  packet_id TEXT NOT NULL UNIQUE,
  packet_sha256 TEXT NOT NULL,
  phase TEXT NOT NULL CHECK(phase IN ('retrieval', 'novelty')),
  action TEXT NOT NULL CHECK(action IN ('match_song', 'candidate_missing', 'new_song', 'unresolved')),
  selected_song_id TEXT,
  proposed_canonical_title TEXT,
  depends_on_decision_id TEXT,
  candidate_rows_json TEXT NOT NULL,
  candidate_set_sha256 TEXT NOT NULL,
  catalog_snapshot_json TEXT NOT NULL,
  catalog_snapshot_sha256 TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  reason_detail TEXT,
  actor_id TEXT NOT NULL,
  model_id TEXT,
  prompt_sha256 TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'superseded', 'retracted')),
  supersedes_decision_id TEXT,
  decided_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (selected_song_id) REFERENCES songs(song_id),
  FOREIGN KEY (depends_on_decision_id) REFERENCES x_song_resolution_decisions(decision_id),
  FOREIGN KEY (supersedes_decision_id) REFERENCES x_song_resolution_decisions(decision_id),
  CHECK (
    (phase = 'retrieval' AND action IN ('match_song', 'candidate_missing', 'unresolved'))
    OR (phase = 'novelty' AND action IN ('match_song', 'new_song', 'unresolved'))
  ),
  CHECK ((action = 'match_song') = (selected_song_id IS NOT NULL)),
  CHECK ((action = 'new_song') = (proposed_canonical_title IS NOT NULL)),
  CHECK ((phase = 'novelty') = (depends_on_decision_id IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_x_song_resolution_active
ON x_song_resolution_decisions(observation_id, phase)
WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_x_song_resolution_observation
ON x_song_resolution_decisions(observation_id, status);

CREATE TABLE IF NOT EXISTS x_occurrence_resolution_decisions (
  decision_id TEXT PRIMARY KEY,
  observation_id TEXT NOT NULL,
  observation_sha256 TEXT NOT NULL,
  packet_id TEXT NOT NULL UNIQUE,
  packet_sha256 TEXT NOT NULL,
  resolution_source TEXT NOT NULL CHECK(resolution_source IN ('report_dependency', 'direct_candidates')),
  action TEXT NOT NULL CHECK(action IN ('match_occurrence', 'dependency_pending', 'unresolved')),
  selected_occurrence_id TEXT,
  event_dependency_key TEXT,
  dependency_decision_id TEXT,
  candidate_rows_json TEXT NOT NULL,
  candidate_set_sha256 TEXT NOT NULL,
  occurrence_snapshot_json TEXT NOT NULL,
  occurrence_snapshot_sha256 TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  reason_detail TEXT,
  actor_id TEXT NOT NULL,
  model_id TEXT,
  prompt_sha256 TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'superseded', 'retracted')),
  supersedes_decision_id TEXT,
  decided_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (selected_occurrence_id) REFERENCES event_occurrences(occurrence_id),
  FOREIGN KEY (supersedes_decision_id) REFERENCES x_occurrence_resolution_decisions(decision_id),
  CHECK ((action = 'match_occurrence') = (selected_occurrence_id IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_x_occurrence_resolution_active
ON x_occurrence_resolution_decisions(observation_id)
WHERE status = 'active';

CREATE TABLE IF NOT EXISTS x_song_materializations (
  materialization_id TEXT PRIMARY KEY,
  observation_id TEXT NOT NULL,
  observation_sha256 TEXT NOT NULL,
  song_decision_id TEXT NOT NULL,
  occurrence_decision_id TEXT NOT NULL,
  song_id TEXT NOT NULL,
  occurrence_id TEXT NOT NULL,
  occurrence_song_id TEXT NOT NULL,
  evidence_id TEXT NOT NULL,
  claim_type TEXT NOT NULL CHECK(claim_type IN ('announced', 'observed')),
  role TEXT NOT NULL CHECK(role IN ('setlist', 'result')),
  evidence_status TEXT NOT NULL CHECK(evidence_status IN ('announced', 'observed')),
  song_change_kind TEXT NOT NULL CHECK(song_change_kind IN ('none', 'created', 'promoted_candidate')),
  song_status_before TEXT,
  song_updated_at_after TEXT,
  created_occurrence_song INTEGER NOT NULL CHECK(created_occurrence_song IN (0, 1)),
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'retracted')),
  materialized_at TEXT NOT NULL,
  retracted_at TEXT,
  FOREIGN KEY (song_decision_id) REFERENCES x_song_resolution_decisions(decision_id),
  FOREIGN KEY (occurrence_decision_id) REFERENCES x_occurrence_resolution_decisions(decision_id),
  FOREIGN KEY (song_id) REFERENCES songs(song_id),
  FOREIGN KEY (occurrence_id) REFERENCES event_occurrences(occurrence_id),
  FOREIGN KEY (occurrence_song_id) REFERENCES occurrence_songs(occurrence_song_id),
  FOREIGN KEY (evidence_id) REFERENCES evidence_items(evidence_id),
  UNIQUE(observation_id, observation_sha256)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_x_song_materialization_active
ON x_song_materializations(observation_id)
WHERE status = 'active';

CREATE TABLE IF NOT EXISTS x_song_retractions (
  retraction_id TEXT PRIMARY KEY,
  materialization_id TEXT NOT NULL UNIQUE,
  observation_id TEXT NOT NULL,
  evidence_link_action TEXT NOT NULL,
  occurrence_song_action TEXT NOT NULL,
  song_action TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  reason_detail TEXT,
  actor_id TEXT NOT NULL,
  retracted_at TEXT NOT NULL,
  FOREIGN KEY (materialization_id) REFERENCES x_song_materializations(materialization_id)
);
"""


def migrate_x_song_identity(conn):
    """Create E2-S v2 append-only ledgers without changing domain rows."""
    migrations = {
        row[1] for row in conn.execute("PRAGMA table_info(local_judgment_schema_migrations)")
    }
    if "version" not in migrations:
        raise ValueError("local judgment migration must run before X song identity migration")

    before = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    conn.executescript(DDL)
    conn.execute(
        """
        INSERT OR IGNORE INTO local_judgment_schema_migrations(version, name, applied_at)
        VALUES (?, ?, ?)
        """,
        (MIGRATION_VERSION, MIGRATION_NAME, datetime.now(timezone.utc).isoformat()),
    )
    after = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    tables = {
        "x_song_resolution_decisions",
        "x_occurrence_resolution_decisions",
        "x_song_materializations",
        "x_song_retractions",
    }
    return {
        "migration_version": MIGRATION_VERSION,
        "migration_name": MIGRATION_NAME,
        "tables_added": sorted(tables - before),
        "tables_present": sorted(tables & after),
    }
