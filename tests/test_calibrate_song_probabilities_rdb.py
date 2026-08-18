import unittest

from calibrate_song_probabilities_rdb import compute_historical_probability


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


if __name__ == "__main__":
    unittest.main()
