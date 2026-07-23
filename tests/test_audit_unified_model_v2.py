import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import master_rdb.unified_model_audit as audit_unified_model_v2_module
from master_rdb.unified_model_audit import audit_observations, audit_rdb
from youtube_backfill.build_event_occurrence_observations import series_key, stable_id


class AuditUnifiedModelV2Test(unittest.TestCase):
    def test_observation_audit_flags_name_year_mismatch(self):
        skey = series_key("SHIBUYA MIYASHITA PARK BON DANCE 2026", "宮下公園")
        row = {
            "observation_id": stable_id(skey, 2025, "2025-09-27"),
            "series_key": skey,
            "event_name": "SHIBUYA MIYASHITA PARK BON DANCE 2026",
            "venue": "宮下公園",
            "year": 2025,
            "date_start": "2025-09-27",
            "date_end": "2025-09-27",
            "observed_dates": ["2025-09-27"],
            "source_type": "youtube_observed",
            "source_video_count": 1,
            "confidence": "low",
            "songs": [],
        }
        summary, issues = audit_observations({
            "series": [{
                "series_key": skey,
                "canonical_name": row["event_name"],
                "usual_venue": row["venue"],
                "observed_years": [2025],
                "observation_count": 1,
            }],
            "observations": [row],
        })

        self.assertEqual(summary["issue_count"], 1)
        self.assertEqual(issues[0]["issue_type"], "event_name_year_mismatch")

    def test_rdb_audit_flags_missing_link_targets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "sample.sqlite"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.executescript(
                    """
                    CREATE TABLE events (event_id TEXT, event_name TEXT);
                    CREATE TABLE venues (venue_id TEXT, venue_name TEXT);
                    CREATE TABLE event_venues (event_id TEXT, venue_id TEXT);
                    CREATE TABLE songs (song_id TEXT, song_name TEXT);
                    CREATE TABLE dance_variants (dance_variant_id TEXT);
                    CREATE TABLE event_song_links (event_id TEXT, song_id TEXT, song_title TEXT, occurrence_key TEXT, evidence_id TEXT, link_status TEXT, link_source TEXT, dance_variant_id TEXT, notes TEXT);
                    CREATE TABLE evidence_items (evidence_id TEXT);
                    CREATE TABLE event_evidence_links (event_id TEXT, evidence_id TEXT, link_status TEXT);
                    CREATE TABLE song_evidence_links (song_id TEXT, song_title TEXT, evidence_id TEXT, occurrence_key TEXT, link_status TEXT, link_source TEXT, notes TEXT);
                    CREATE TABLE review_queue (review_status TEXT);
                    CREATE TABLE rdb_issues (issue_key TEXT);
                    INSERT INTO venues VALUES ('venue1', '会場');
                    INSERT INTO event_venues VALUES ('missing-event', 'venue1');
                    INSERT INTO song_evidence_links VALUES ('', '東京音頭', 'missing-evidence', 'occ1', 'matched_song', 'test', '');
                    """
                )

            summary, issues = audit_rdb(db_path)

        self.assertEqual(summary["issue_count"], 2)
        self.assertEqual(
            {issue["issue_type"] for issue in issues},
            {"event_venues_missing_event", "song_evidence_missing_evidence"},
        )

    def test_audit_rdb_closes_its_connection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "sample.sqlite"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.executescript(
                    """
                    CREATE TABLE events (event_id TEXT, event_name TEXT);
                    CREATE TABLE venues (venue_id TEXT, venue_name TEXT);
                    CREATE TABLE event_venues (event_id TEXT, venue_id TEXT);
                    CREATE TABLE songs (song_id TEXT, song_name TEXT);
                    CREATE TABLE dance_variants (dance_variant_id TEXT);
                    CREATE TABLE event_song_links (event_id TEXT, song_id TEXT, song_title TEXT, occurrence_key TEXT, evidence_id TEXT, link_status TEXT, link_source TEXT, dance_variant_id TEXT, notes TEXT);
                    CREATE TABLE evidence_items (evidence_id TEXT);
                    CREATE TABLE event_evidence_links (event_id TEXT, evidence_id TEXT, link_status TEXT);
                    CREATE TABLE song_evidence_links (song_id TEXT, song_title TEXT, evidence_id TEXT, occurrence_key TEXT, link_status TEXT, link_source TEXT, notes TEXT);
                    CREATE TABLE review_queue (review_status TEXT);
                    CREATE TABLE rdb_issues (issue_key TEXT);
                    """
                )

            opened_connections = []
            real_connect = sqlite3.connect

            def _tracking_connect(*args, **kwargs):
                conn = real_connect(*args, **kwargs)
                opened_connections.append(conn)
                return conn

            with patch.object(audit_unified_model_v2_module.sqlite3, "connect", side_effect=_tracking_connect):
                audit_rdb(db_path)

        self.assertTrue(opened_connections)
        for conn in opened_connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
