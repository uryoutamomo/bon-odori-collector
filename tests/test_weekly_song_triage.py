import unittest

from song_processing.weekly_song_triage import classify_candidate, is_song_like


class WeeklySongTriageTest(unittest.TestCase):
    def classify(self, term):
        return classify_candidate({"term": term})

    def test_canonicalizes_known_sentence_fragments(self):
        decision, canonical, reason = self.classify("子供用にドラえもん音頭")

        self.assertEqual(decision, "direct")
        self.assertEqual(canonical, "ドラえもん音頭")
        self.assertIn("正規曲名", reason)

    def test_rejects_sentence_fragments(self):
        decision, canonical, reason = self.classify("またその行事内で行われる踊り")

        self.assertEqual(decision, "reject")
        self.assertEqual(canonical, "またその行事内で行われる踊り")
        self.assertIn("文章断片", reason)

    def test_keeps_ambiguous_terms_for_review(self):
        decision, canonical, reason = self.classify("郡上おどり")

        self.assertEqual(decision, "review")
        self.assertEqual(canonical, "郡上おどり")
        self.assertIn("多義語", reason)

    def test_accepts_song_like_terms(self):
        self.assertTrue(is_song_like("東京音頭"))
        self.assertTrue(is_song_like("南中ソーラン"))
        self.assertFalse(is_song_like("今日は踊り"))


if __name__ == "__main__":
    unittest.main()
