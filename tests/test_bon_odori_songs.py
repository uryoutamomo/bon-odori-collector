import unittest

from song_processing.bon_odori_songs import extract_song_candidates, extract_song_hints


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
            "2025-08-23（土）18:00から盆踊り。曲目は大井どんたく音頭、品川音頭、東京音頭、品川甚句など。"
        )

        self.assertIn("大井どんたく音頭", names(rows))
        self.assertIn("品川音頭", names(rows))
        self.assertIn("東京音頭", names(rows))
        self.assertIn("品川甚句", names(rows))

    def test_extracts_master_song_names_in_song_context(self):
        rows = extract_song_hints("曲目はBeat It、東京音頭、炭坑節。")

        self.assertIn("Beat It", names(rows))

    def test_extracts_tsukiji_local_song_with_particles(self):
        rows = extract_song_hints("曲目は築地音頭、これがお江戸の盆ダンス、あさりときりみのおだいどこ音頭、ホームラン音頭。")

        self.assertIn("あさりときりみのおだいどこ音頭", names(rows))
        self.assertIn("これがお江戸の盆ダンス", names(rows))

    def test_ignores_generic_event_words(self):
        rows = extract_song_hints("納涼盆踊り大会。踊り大会は18時開始。")

        self.assertEqual(rows, [])

    def test_hints_reject_sentence_fragments_without_explicit_song_context(self):
        rows = extract_song_hints(
            "下北沢駅東口周辺で開かれる街なかの踊り。出店者や踊り手も参加。路上で行われる踊り。"
        )
        self.assertEqual(rows, [])

    def test_hints_strip_terminal_marker_from_explicit_song_list(self):
        rows = extract_song_hints("曲目：終 炭坑節、終 津軽甚句")
        self.assertIn("炭坑節", names(rows))
        self.assertIn("津軽甚句", names(rows))
        self.assertNotIn("終 炭坑節", names(rows))

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

    def test_review_candidates_drop_generic_song_names(self):
        rows = extract_song_candidates(
            "盆踊り（ぼんおどり）は、日本において、盆の時期に先祖を供養する行事、またその行事内で行われる踊り。"
        )

        self.assertEqual(rows, [])
        self.assertEqual(extract_song_candidates("曲は踊り好きの先達やあたらしく踊り"), [])

    def test_review_candidates_drop_blocked_cultural_context(self):
        rows = extract_song_candidates("死霊の盆踊りを観た。曲はマイケル音頭っぽい。")

        self.assertEqual(rows, [])

    def test_review_candidates_strip_noise_prefixes(self):
        rows = extract_song_candidates("曲目は演目・大の坂踊り、回かすがい郡上おどり")

        self.assertIn("大の坂踊り", names(rows))
        self.assertIn("かすがい郡上おどり", names(rows))
        self.assertNotIn("演目・大の坂踊り", names(rows))
        self.assertNotIn("回かすがい郡上おどり", names(rows))


if __name__ == "__main__":
    unittest.main()
