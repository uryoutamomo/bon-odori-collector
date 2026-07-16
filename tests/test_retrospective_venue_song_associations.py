import unittest
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "legacy" / "build-reports" / "build_retrospective_venue_song_associations.py"
SPEC = importlib.util.spec_from_file_location("build_retrospective_venue_song_associations", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

build_from_voices = MODULE.build_from_voices


class RetrospectiveVenueSongAssociationsTest(unittest.TestCase):
    def test_builds_probability_from_independent_x_evidence(self):
        payload = build_from_voices(
            [
                {
                    "source": "x",
                    "account": "@a",
                    "date": "2026-07-01T10:00:00+00:00",
                    "tweet_id": "1",
                    "url": "https://x.com/a/status/1",
                    "text": "中央公園の盆踊りに7月20日行った。曲目は東京音頭、炭坑節で楽しかった。",
                },
                {
                    "source": "x",
                    "account": "@b",
                    "date": "2026-07-02T10:00:00+00:00",
                    "tweet_id": "2",
                    "url": "https://x.com/b/status/2",
                    "text": "中央公園の盆踊り、7月20日開催。曲目は東京音頭。",
                },
            ],
            generated_at="2026-06-14T00:00:00+00:00",
        )

        tokyo = next(item for item in payload["associations"] if item["song_name"] == "東京音頭")
        self.assertEqual(tokyo["venue"], "中央公園")
        self.assertEqual(tokyo["evidence_count"], 2)
        self.assertEqual(tokyo["speaker_count"], 2)
        self.assertGreaterEqual(tokyo["probability"], 70)

    def test_flags_practice_context_lower_than_observed_context(self):
        payload = build_from_voices(
            [
                {
                    "source": "x",
                    "account": "@a",
                    "date": "2026-06-01T10:00:00+00:00",
                    "tweet_id": "1",
                    "url": "https://x.com/a/status/1",
                    "text": "6/11 中央公園盆踊り大会の練習会。曲目は東京音頭、炭坑節。",
                }
            ],
            generated_at="2026-06-14T00:00:00+00:00",
        )

        row = next(item for item in payload["associations"] if item["song_name"] == "東京音頭")
        self.assertIn("practice_or_preview", row["flags"])
        self.assertLess(row["probability"], 55)

    def test_drops_false_song_fragments_and_splits_compounds(self):
        payload = build_from_voices(
            [
                {
                    "source": "x",
                    "account": "@a",
                    "date": "2026-06-01T10:00:00+00:00",
                    "tweet_id": "1",
                    "url": "https://x.com/a/status/1",
                    "text": "飛鳥山公園の盆踊りで山王音頭と千代田踊り、良い予習ができました。ぜひご一緒に踊りましょう。",
                }
            ],
            generated_at="2026-06-14T00:00:00+00:00",
        )

        names = {item["song_name"] for item in payload["associations"]}
        self.assertIn("山王音頭", names)
        self.assertIn("千代田踊り", names)
        self.assertNotIn("ぜひご一緒に踊り", names)

    def test_uses_x_only_by_default(self):
        payload = build_from_voices(
            [
                {
                    "source": "youtube",
                    "account": "@video",
                    "date": "2026-06-01T10:00:00+00:00",
                    "url": "https://www.youtube.com/watch?v=1",
                    "text": "中央公園の盆踊り。曲目は東京音頭。",
                }
            ],
            generated_at="2026-06-14T00:00:00+00:00",
        )

        self.assertEqual(payload["scanned_voice_count"], 0)
        self.assertEqual(payload["association_count"], 0)


if __name__ == "__main__":
    unittest.main()
