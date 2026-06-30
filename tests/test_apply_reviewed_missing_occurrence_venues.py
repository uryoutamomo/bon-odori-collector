import tempfile
import unittest
from pathlib import Path

from apply_reviewed_missing_occurrence_venues import apply_plan, build_plan, occurrence
from master_db import init_db, normalize_text


NOW = "2026-01-01T00:00:00+00:00"


def create_db(path: Path):
    conn = init_db(path)
    conn.execute(
        """
        INSERT INTO event_series(
          series_id, series_key, canonical_name, normalized_name, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("series_1", "test-series", "銀座一丁目東町会・新富町会 納涼盆踊り大会", "銀座一丁目東町会新富町会納涼盆踊り大会", NOW, NOW),
    )
    conn.execute(
        """
        INSERT INTO event_occurrences(
          occurrence_id, series_id, event_year, display_name, date_status,
          lifecycle_status, confidence, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("occ_1", "series_1", 2025, "銀座一丁目東町会・新富町会 納涼盆踊り大会", "confirmed", "published", "confirmed", NOW, NOW),
    )
    conn.commit()
    return conn


class ApplyReviewedMissingOccurrenceVenuesTest(unittest.TestCase):
    def test_creates_reviewed_new_venue_and_fills_occurrence(self):
        venue_data = {
            "canonical_name": "京橋プラザ区民館",
            "aliases": ["京橋プラザ", "中央区京橋プラザ"],
            "area": "中央区",
            "address": "東京都中央区銀座一丁目25番3号",
            "access": "東京メトロ有楽町線「新富町」駅徒歩2分",
            "source_url": "https://www.city.chuo.lg.jp/a0013/kurashi/chiikicommunity/kuminkan/syukaisisetu02.html",
        }
        review = {
            "review": [
                {
                    "occurrence_id": "occ_1",
                    "event_name": "銀座一丁目東町会・新富町会 納涼盆踊り大会",
                    "event_year": 2025,
                    "review_action": "ready_new_venue_candidate",
                    "candidate_venue_data": venue_data,
                    "confidence": "high",
                    "reason": "official facility confirmed",
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "master.sqlite"
            conn = create_db(db_path)
            try:
                planned, skipped = build_plan(conn, review)
                applied = apply_plan(conn, planned, NOW)

                self.assertEqual(skipped, [])
                self.assertEqual(len(applied), 1)
                self.assertEqual(applied[0]["action"], "create_venue_and_fill_occurrence")
                self.assertTrue(applied[0]["venue_created"])

                after = occurrence(conn, "occ_1")
                self.assertEqual(after["venue_name"], "京橋プラザ区民館")

                series_venue = conn.execute(
                    "SELECT usual_venue_id FROM event_series WHERE series_id = 'series_1'"
                ).fetchone()[0]
                self.assertEqual(series_venue, after["venue_id"])

                aliases = {
                    row[0]
                    for row in conn.execute(
                        "SELECT normalized_alias FROM venue_aliases WHERE venue_id = ?",
                        (after["venue_id"],),
                    )
                }
                self.assertIn(normalize_text("京橋プラザ区民館"), aliases)
                self.assertIn(normalize_text("京橋プラザ"), aliases)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
