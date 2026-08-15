"""収集の関門で「意味」を理由に投稿を捨てない。

2026-08-15 に生投稿7,162件で実測したところ、除外語の関門が落としていた212件のうち
117件（55%）が盆踊りの話だった。「セトリ」「セットリスト」で曲目そのものを、「ガチャ」で
縁日のガチャガチャを、「ポケモン」でポケモン音頭の参加報告を捨てていた。正しく弾けていたのは
95件（全体の1.3%）で、うち79件は同一アカウントのお笑いライブ定型告知だった。
"""
import unittest

from collect import _score_voice, _x_post_value_score
from collection_support.event_evidence import classify_event_evidence

# 実際に捨てられていた投稿（raw S3 の原文を短くしたもの）
REAL_DROPPED = {
    "セトリ": "江戸川区盆探索2 鹿骨中学校 盆踊り 初日参加 by 鹿骨２丁目町会 江戸川ふるさと音頭 ご縁でセトリを初日のみならず二日目の方も情報いただく",
    "セットリスト": "今日明日は歌舞伎町BONODORI！ 初心者から上級者まで楽しめる渾身のセットリストと盆踊りの構成になっております",
    "ガチャ": "北大泉商栄会の盆踊り大会に行ってきました。ドラえもん音頭やダンシングヒーローの盆踊りで会場は大賑わい。ガチャガチャやアームレスリングなど子どもが楽しめる企画もたくさん",
    "ポケモン": "今日はうちの町会の盆踊り最終日でした。松本梨香さんがゲストで来てくれて、ポケモン歌ってくれたよ",
    "ライブ": "袴腰広場に来たのはフリーライブも見るため。今日のトップはひとにゃん。#ゐの市盆踊り",
    "郡上踊り": "三大盆踊りの郡上踊りの徹夜踊りなんて4日間20時〜午前5時までやってる",
}
# 廃止前の設定。これらが残っていても捨ててはいけない。
LEGACY_CONFIG = {
    "exclude_keywords": ["ポケモン", "セトリ", "セットリスト", "ライブ", "Zepp", "ガチャ", "郡上踊り",
                         "悪口盆踊り", "ダーク盆踊り", "真冬の盆踊り", "音ゲー", "ソシャゲ"],
    "experience_keywords": ["行ってきた", "参加した"],
}


class NoSemanticExclusionTest(unittest.TestCase):
    def test_real_posts_are_not_dropped_by_the_value_gate(self):
        """実際に捨てられていた投稿が、関門（score >= 0）を通ること。"""
        dropped = {}
        for keyword, text in REAL_DROPPED.items():
            score, reasons = _x_post_value_score({"text": text}, LEGACY_CONFIG, {})
            if score < 0.0 or "exclude" in reasons:
                dropped[keyword] = (score, reasons)
        self.assertEqual(dropped, {}, f"また捨てている: {dropped}")

    def test_voice_scoring_never_returns_noise(self):
        """🔴ノイズは voices.json への投入を止める札だった。もう返さない。"""
        noisy = [keyword for keyword, text in REAL_DROPPED.items()
                 if _score_voice(text, LEGACY_CONFIG) == "🔴ノイズ"]
        self.assertEqual(noisy, [], f"ノイズ扱いに戻っている: {noisy}")

    def test_event_evidence_does_not_penalise_excluded_context(self):
        """候補の優先付けでも同じ語彙で減点しない。"""
        # 分類器が拾う形（E パターンの「踊った」）で、かつ除外語「ガチャ」を含む参加報告。
        text = "北大泉商栄会の盆踊り大会でドラえもん音頭を踊った。ガチャガチャもあって子どもが楽しそうだった"
        voice = {"text": text, "account": "@tester", "date": "2026-08-14"}
        evidence = classify_event_evidence(voice, LEGACY_CONFIG)
        self.assertIsNotNone(evidence, "参加報告が候補にならないなら前提が変わっている")
        self.assertNotIn("excluded_context:-5", evidence["score_reasons"])

    def test_song_information_survives(self):
        """曲目そのものを含む投稿が残ること（盆助が集めている情報の中心）。"""
        score, reasons = _x_post_value_score({"text": REAL_DROPPED["セットリスト"]}, LEGACY_CONFIG, {})
        self.assertGreater(score, 0.0)
        self.assertIn("bon", reasons)

    def test_the_gate_still_drops_posts_without_any_context(self):
        """意味を見ない側の関門まで外していないこと（文脈ゼロは従来どおり落ちる）。"""
        score, reasons = _x_post_value_score({"text": "おはようございます"}, LEGACY_CONFIG, {})
        self.assertLess(score, 0.0)
        self.assertIn("no_context", reasons)


if __name__ == "__main__":
    unittest.main()
