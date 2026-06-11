import unittest

from bon_odori_songs import extract_song_candidates, extract_song_hints


def names(rows):
    return [row["name"] for row in rows]


class BonOdoriSongsTest(unittest.TestCase):
    def test_extracts_explicit_song_list(self):
        rows = extract_song_hints(
            "2026-03-15（日）納涼太鼓 大場連が盆踊り3曲。曲目は東京音頭、炭坑節、荒川音頭。"
        )

        self.assertEqual(names(rows), ["東京音頭", "炭坑節", "荒川音頭"])

    def test_extracts_local_ondo_in_dance_context(self):
        rows = extract_song_hints(
            "2025-08-23（土）18:00から盆踊り。大井どんたく音頭、品川音頭、東京音頭、品川甚句など。"
        )

        self.assertIn("大井どんたく音頭", names(rows))
        self.assertIn("品川音頭", names(rows))
        self.assertIn("東京音頭", names(rows))
        self.assertIn("品川甚句", names(rows))

    def test_ignores_generic_event_words(self):
        rows = extract_song_hints("納涼盆踊り大会。踊り大会は18時開始。")

        self.assertEqual(rows, [])

    def test_review_candidates_include_known_songs_in_context(self):
        rows = extract_song_candidates(
            "築地本願寺で花笠音頭からはじまり、ソーラン節、炭坑節と民謡踊りを楽しく。"
        )

        self.assertIn("花笠音頭", names(rows))
        self.assertIn("ソーラン節", names(rows))
        self.assertIn("炭坑節", names(rows))

    def test_review_candidates_drop_sentence_fragments(self):
        rows = extract_song_candidates("去年は入谷南公園の朝顔音頭踊り大会に踊りに行った。")

        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
