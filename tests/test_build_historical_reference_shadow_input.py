import hashlib
import tempfile
import unittest
from pathlib import Path

from build_historical_reference_shadow_input import build_input
from master_db import init_db


def insert_series(conn, series_id):
    conn.execute(
        "INSERT INTO event_series(series_id, series_key, canonical_name, normalized_name, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, 'now', 'now')",
        (series_id, series_id, series_id, series_id),
    )


def insert_occurrence(conn, occurrence_id, series_id, sequence=1):
    conn.execute(
        "INSERT INTO event_occurrences(occurrence_id, series_id, event_year, "
        "occurrence_sequence, display_name, created_at, updated_at) "
        "VALUES (?, ?, 2026, ?, ?, 'now', 'now')",
        (occurrence_id, series_id, sequence, occurrence_id),
    )


def insert_candidate(conn, candidate_id, series_id, occurrence_id):
    conn.execute(
        """
        INSERT INTO historical_promotion_candidates(
          candidate_id, target_series_id, target_occurrence_id, target_event_name,
          historical_years_json, promotion_confidence, recommended_action,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, '[2024, 2025]', 'high',
                  'auto_promote_historical_reference', 'now', 'now')
        """,
        (candidate_id, series_id, occurrence_id, candidate_id),
    )


class BuildHistoricalReferenceShadowInputTest(unittest.TestCase):
    def test_builds_read_only_current_identity_snapshot_and_excludes_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "master.sqlite"
            conn = init_db(database)
            insert_series(conn, "series_one")
            insert_series(conn, "series_two")
            insert_occurrence(conn, "occ_one", "series_one")
            insert_occurrence(conn, "occ_mismatch", "series_one", sequence=2)
            insert_candidate(conn, "candidate_one", "series_one", "occ_one")
            conn.execute("PRAGMA foreign_keys = OFF")
            insert_candidate(conn, "candidate_mismatch", "series_two", "occ_mismatch")
            conn.commit()
            conn.close()
            checksum_before = hashlib.sha256(database.read_bytes()).hexdigest()

            payload = build_input(database, source_locator="s3://example/snapshot.sqlite")

            self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), checksum_before)
            self.assertEqual(payload["source"]["database_sha256"], checksum_before)
            self.assertEqual(payload["source"]["database_locator"], "s3://example/snapshot.sqlite")
            self.assertEqual(payload["selection"]["total_candidate_count"], 2)
            self.assertEqual(payload["selection"]["included_count"], 1)
            self.assertEqual(payload["selection"]["excluded_count"], 1)
            self.assertEqual(
                payload["selection"]["excluded_candidate_ids"], ["candidate_mismatch"]
            )
            candidate = payload["candidates"][0]
            self.assertEqual(candidate["candidate_id"], "candidate_one")
            self.assertEqual(candidate["historical_years"], [2024, 2025])
            self.assertEqual(candidate["occurrence_series_id"], "series_one")
            self.assertEqual(
                candidate["current_identity"],
                {
                    "series_resolved": True,
                    "occurrence_resolved": True,
                    "occurrence_series_matches": True,
                },
            )


if __name__ == "__main__":
    unittest.main()
