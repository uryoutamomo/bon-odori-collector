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


if __name__ == "__main__":
    unittest.main()
