import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import collect


def voice(handle, text, day, *, media=False):
    return {
        "source": "x_whitelist", "account": f"@{handle}", "text": text,
        "date": f"2026-08-{day:02d}T12:00:00+00:00", "media_urls": ["https://img"] if media else [],
    }


class XBonodorerReevaluationTest(unittest.TestCase):
    def test_same_named_ordinance_city_ward_is_not_bon23_but_bare_ward_is(self):
        scores = collect._build_x_account_scores([
            voice("nagoya", "名古屋市北区の盆踊りのお知らせ", 1),
            voice("setagaya", "#世田谷の盆踊り。今夜開催です", 1),
        ])

        self.assertEqual(scores["accounts"]["nagoya"]["bon23_count"], 0)
        self.assertEqual(scores["accounts"]["setagaya"]["bon23_count"], 1)

    def test_small_sample_ratio_is_shrunk_toward_the_base_rate(self):
        self.assertLess(collect._x_smoothed_ratio(3, 3, 0.35), 1.0)
        self.assertGreater(collect._x_smoothed_ratio(0, 3, 0.35), 0.0)

    def test_area_bot_excludes_a_person_who_visits_other_prefectures(self):
        bot_text = "兵庫県の盆踊りニュース https://example.test/article"
        person_text = "兵庫県の盆踊りに行った https://example.test/post"
        scores = collect._build_x_account_scores(
            [voice("bot", bot_text, day) for day in range(1, 5)]
            + [voice("person", person_text, day) for day in range(1, 5)],
            {"experience_keywords": ["行った"]},
        )

        self.assertTrue(scores["accounts"]["bot"]["is_area_bot"])
        self.assertFalse(scores["accounts"]["person"]["is_area_bot"])
        self.assertGreater(scores["accounts"]["person"]["experience_ratio"], 0.15)

    def test_song_list_terms_remain_legacy_quality_signals_but_not_experience_style(self):
        scores = collect._build_x_account_scores(
            [voice("program", "盆踊りの曲目表を公開しました", day) for day in range(1, 4)],
            {"experience_keywords": ["曲目表"]},
        )

        row = scores["accounts"]["program"]
        self.assertEqual(row["top_reasons"]["experience"], 3)
        self.assertEqual(row["experience_count"], 0)

    def test_gap_credits_are_written_and_do_not_change_whitelist_selection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            credits = Path(tmpdir) / "credits.json"
            credits.write_text('{"credits":{"useful":2}}', encoding="utf-8")
            with patch.object(collect, "X_GAP_CREDITS_FILE", str(credits)):
                scores = collect._build_x_account_scores([
                    voice("useful", "世田谷の盆踊りを告知します", 1),
                ])
        self.assertEqual(scores["accounts"]["useful"]["gap_credits"], 2)

        original = {"accounts": {"useful": {
            "handle": "@useful", "status": "trusted", "posts_seen": 5, "usefulness_score": 90,
        }}}
        enriched = {"accounts": {"useful": {
            **original["accounts"]["useful"], "announce_score": 99, "voice_score": 99,
            "is_area_bot": False, "gap_credits": 2,
        }}}
        with tempfile.TemporaryDirectory() as tmpdir:
            common = (
                patch.object(collect, "NOTION_TOKEN", None),
                patch.object(collect, "X_OFFICIAL_SOURCE_ACCOUNTS_FILE", str(Path(tmpdir) / "missing.json")),
                patch.object(collect, "X_IMPORTANT_INFORMANTS_FILE", str(Path(tmpdir) / "missing.json")),
                patch.object(collect, "X_COLLECTION_ROSTER_FILE", str(Path(tmpdir) / "missing.json")),
            )
            for mocked in common:
                mocked.start()
            try:
                with patch.object(collect, "_load_x_account_scores", return_value=original):
                    before = collect.load_whitelist_accounts({"auto_trusted_roster": {"max_accounts": 10}})
                with patch.object(collect, "_load_x_account_scores", return_value=enriched):
                    after = collect.load_whitelist_accounts({"auto_trusted_roster": {"max_accounts": 10}})
            finally:
                for mocked in reversed(common):
                    mocked.stop()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
