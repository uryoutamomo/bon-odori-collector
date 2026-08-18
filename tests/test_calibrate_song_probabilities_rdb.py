import unittest
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

from calibrate_song_probabilities_rdb import (
    calibrate,
    compute_historical_probability,
    normalize_kind,
    validate_apply_request,
)
from master_rdb.master_db import init_db


NOW = "2026-08-18T00:00:00+00:00"


class CalibrateHistoricalSongProbabilityTest(unittest.TestCase):
    def test_decays_one_year_old_youtube_observation(self):
        result = compute_historical_probability(
            [
                {
                    "kind": "observed",
                    "reliability": 0.85,
                    "speaker": "youtube:channel",
                }
            ],
            target_year=2026,
            source_year=2025,
        )

        self.assertEqual(result["probability"], 51)
        self.assertEqual(result["basis"], "past_evidence")
        self.assertEqual(result["basis_label"], "2025年実測")

    def test_combines_evidence_from_multiple_historical_years(self):
        result = compute_historical_probability(
            [
                {"kind": "observed", "reliability": 0.80, "speaker": "report:2024", "source_year": 2024},
                {"kind": "observed", "reliability": 0.85, "speaker": "youtube:2025", "source_year": 2025},
                {"kind": "observed", "reliability": 0.80, "speaker": "report:2025", "source_year": 2025},
                {"kind": "observed", "reliability": 0.70, "speaker": "blog:2025", "source_year": 2025},
            ],
            target_year=2026,
            source_year=2025,
        )

        self.assertEqual(result["probability"], 84)
        self.assertEqual(result["basis_label"], "2024・2025年実測")
        self.assertEqual(result["source_years"], [2024, 2025])
        self.assertEqual(result["speaker_count"], 4)
        self.assertEqual(
            result["annual_probabilities"],
            [
                {
                    "source_year": 2024,
                    "probability": 36,
                    "source_kind": "observed",
                    "speaker_count": 1,
                    "evidence_used": 1,
                },
                {
                    "source_year": 2025,
                    "probability": 74,
                    "source_kind": "observed",
                    "speaker_count": 3,
                    "evidence_used": 3,
                },
            ],
        )

    def test_two_consecutive_years_score_higher_than_latest_year_alone(self):
        latest_only = compute_historical_probability(
            [
                {
                    "kind": "observed",
                    "reliability": 0.85,
                    "speaker": "youtube:channel",
                    "source_year": 2024,
                }
            ],
            target_year=2026,
            source_year=2024,
        )
        consecutive = compute_historical_probability(
            [
                {
                    "kind": "observed",
                    "reliability": 0.85,
                    "speaker": "youtube:channel",
                    "source_year": 2023,
                },
                {
                    "kind": "observed",
                    "reliability": 0.85,
                    "speaker": "youtube:channel",
                    "source_year": 2024,
                },
            ],
            target_year=2026,
            source_year=2024,
        )

        self.assertEqual(latest_only["probability"], 38)
        self.assertEqual(consecutive["probability"], 56)
        self.assertGreater(consecutive["probability"], latest_only["probability"])

    def test_legacy_annual_probabilities_also_accumulate_across_years(self):
        latest_only = compute_historical_probability(
            [],
            target_year=2026,
            annual_fallbacks=[{
                "source_year": 2025,
                "probability": 95,
                "source_count": 1,
                "source_kind": "observed",
            }],
        )
        consecutive = compute_historical_probability(
            [],
            target_year=2026,
            annual_fallbacks=[
                {"source_year": 2024, "probability": 95, "source_count": 1, "source_kind": "observed"},
                {"source_year": 2025, "probability": 95, "source_count": 1, "source_kind": "observed"},
            ],
        )

        self.assertEqual(latest_only["probability"], 57)
        self.assertEqual(consecutive["probability"], 75)
        self.assertEqual(consecutive["basis_label"], "2024・2025年実測")
        self.assertGreater(consecutive["probability"], latest_only["probability"])

    def test_poster_post_is_an_announcement(self):
        self.assertEqual(normalize_kind("poster_post", "announced"), "announced")

    def test_recalculate_existing_requires_an_explicit_scope(self):
        args = Namespace(
            recalculate_existing=True,
            target_year=None,
            occurrence_id="",
            apply=False,
            master_db=Path("master.sqlite"),
            out_db=Path("out.sqlite"),
            confirm="",
        )

        with self.assertRaisesRegex(ValueError, "requires --target-year or --occurrence-id"):
            validate_apply_request(args)

    def test_recalculation_is_scoped_and_uses_only_accepted_links(self):
        with TemporaryDirectory() as tmp:
            conn = init_db(Path(tmp) / "master.sqlite")
            conn.execute(
                """
                INSERT INTO event_series(
                  series_id, series_key, canonical_name, normalized_name, created_at, updated_at
                ) VALUES ('series_1', 'series-1', 'テスト盆踊り', 'テスト盆踊り', ?, ?)
                """,
                (NOW, NOW),
            )
            conn.execute(
                """
                INSERT INTO event_occurrences(
                  occurrence_id, origin, series_id, event_year, display_name, date_start,
                  created_at, updated_at
                ) VALUES ('occ_2026', 'curated', 'series_1', 2026, 'テスト盆踊り',
                          '2026-08-21', ?, ?)
                """,
                (NOW, NOW),
            )
            conn.execute(
                """
                INSERT INTO songs(
                  song_id, canonical_title, normalized_title, status, created_at, updated_at
                ) VALUES ('song_1', '東京音頭', '東京音頭', 'active', ?, ?)
                """,
                (NOW, NOW),
            )
            conn.execute(
                """
                INSERT INTO occurrence_songs(
                  occurrence_song_id, origin, occurrence_id, song_id, song_title_raw,
                  normalized_title, role, evidence_status, probability, confidence,
                  created_at, updated_at
                ) VALUES ('osong_1', 'curated', 'occ_2026', 'song_1', '東京音頭',
                          '東京音頭', 'setlist', 'announced', 80, 'high', ?, ?)
                """,
                (NOW, NOW),
            )
            conn.executemany(
                """
                INSERT INTO evidence_items(
                  evidence_id, platform, evidence_type, source_key, observed_at,
                  detected_event_date, raw_json
                ) VALUES (?, 'web', 'poster_post', ?, '2026-08-07', '2026-08-21', '{}')
                """,
                [("accepted", "official"), ("retracted", "old")],
            )
            conn.executemany(
                """
                INSERT INTO occurrence_song_evidence_links(
                  occurrence_song_id, evidence_id, link_status, confidence
                ) VALUES ('osong_1', ?, ?, ?)
                """,
                [("accepted", "accepted", 0.95), ("retracted", "retracted", 0.99)],
            )

            default = calibrate(conn, NOW, target_year=2026)
            recalculated = calibrate(
                conn,
                NOW,
                target_year=2026,
                recalculate_existing=True,
            )
            probability = conn.execute(
                "SELECT probability FROM occurrence_songs WHERE occurrence_song_id='osong_1'"
            ).fetchone()[0]

        self.assertEqual(default["targets_considered"], 0)
        self.assertEqual(recalculated["updated"][0]["basis"], "current_announced")
        self.assertEqual(probability, 95)


if __name__ == "__main__":
    unittest.main()
