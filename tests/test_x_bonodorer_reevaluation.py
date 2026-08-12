import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

import collect
from scripts.check_x_bonodorer_gold import build_rosters


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

    def test_mixed_post_keeps_tokyo23_and_outside_evidence_independently(self):
        post = voice("mixed", "東京の盆踊りと大阪市の盆踊りを紹介します", 1)
        scores = collect._build_x_account_scores([post])

        self.assertTrue(post["has_tokyo23_evidence"])
        self.assertTrue(post["has_outside_evidence"])
        self.assertEqual(scores["accounts"]["mixed"]["bon23_count"], 1)
        self.assertEqual(scores["accounts"]["mixed"]["outside_count"], 1)

    def test_master_event_name_is_tokyo23_evidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = Path(tmpdir) / "runtime.json"
            runtime.write_text(json.dumps({
                "songs": [], "places": [], "events": ["鉄砲洲納涼盆踊り", "大井どんたく夏まつり"],
            }), encoding="utf-8")
            scores = collect._build_x_account_scores([
                voice("teppo", "鉄砲洲納涼盆踊りへ行きました", 1),
                voice("oi", "大井どんたく夏まつりの盆踊りを開催します", 1),
            ], {"x_bonodorer_master_runtime_file": str(runtime)})

        self.assertEqual(scores["accounts"]["teppo"]["bon23_count"], 1)
        self.assertEqual(scores["accounts"]["oi"]["bon23_count"], 1)

    def test_announce_score_is_not_capped_by_missing_tokyo23_evidence(self):
        account = {"release": {
            "handle": "@release", "recent_future_schedule_posts": 20,
            "profile_description": "", "recent_posts_seen": 1,
        }}
        metrics = {"release": {
            "posts_with_text": 20, "bon_count": 20, "bon23_count": 0,
            "outside_count": 0, "url_count": 0, "listy_count": 0,
            "opinion_count": 0, "experience_count": 0, "detail_count": 0,
            "media_count": 0, "text_length": 100, "post_days": {"2026-08-01"},
            "change_count": 0, "onsite23_count": 0, "photo23_count": 0,
            "song_count": 0, "place_count": 0,
        }}
        collect._add_x_bonodorer_scores(account, metrics, {})
        self.assertGreater(account["release"]["announce_score"], 8.0)

    def test_roster_keeps_unknown_evidence_account_unless_a_final_exclusion_applies(self):
        accounts = {
            "unknown": {"announce_score": 9, "record_score": 9, "is_area_bot": False},
            "bot": {"announce_score": 99, "record_score": 99, "is_area_bot": True},
            "reviewed": {"announce_score": 99, "record_score": 99, "is_area_bot": False},
            "paused": {"announce_score": 99, "record_score": 99, "is_area_bot": False},
            "manual": {"announce_score": -99, "record_score": -99, "is_area_bot": False},
        }
        rosters = build_rosters(
            accounts,
            {"paused": "休止", "manual": "優先"},
            {"reviewed": {"reason": "東京以外が中心"}},
        )
        self.assertIn("unknown", rosters["announce"])
        self.assertNotIn("bot", rosters["announce"])
        self.assertNotIn("reviewed", rosters["record"])
        self.assertNotIn("paused", rosters["record"])
        self.assertIn("manual", rosters["announce"])
        self.assertEqual(rosters["eligibility"]["reviewed"], "reviewed_exclusion")

    def test_shelf_exclusion_export_uses_why_as_reason(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "shelf.json"
            path.write_text(json.dumps({"excluded": [{
                "handle": "@reviewed", "why": "東京以外が中心", "memo": "棚卸し済み",
            }]}), encoding="utf-8")
            exclusions = collect._load_x_roster_exclusions(path)
        self.assertEqual(exclusions["reviewed"]["reason"], "東京以外が中心")

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

    def test_change_notice_and_onsite_record_are_scored_separately(self):
        scores = collect._build_x_account_scores([
            voice("change", "世田谷区の盆踊りは荒天で中止です", 1),
            voice("change", "世田谷区の盆踊りは順延です", 2),
            voice("onsite", "今日の盆踊り、墨田区で始まりました", 1, media=True),
            voice("onsite", "本日は墨田区の盆踊りを開催中", 2, media=True),
            voice("onsite", "墨田区の盆踊り、ただいま演奏中", 3),
        ])
        self.assertEqual(scores["accounts"]["change"]["change_count"], 2)
        self.assertGreater(scores["accounts"]["change"]["announce_score"], 0)
        self.assertGreater(scores["accounts"]["onsite"]["record_score"], 0)
        self.assertNotIn("voice_score", scores["accounts"]["onsite"])

    def test_profile_is_neutral_when_missing_and_organizations_are_not_penalized(self):
        rows = [voice("missing", "世田谷の盆踊りを開催中", day) for day in range(1, 6)]
        rows += [{**voice("org", "世田谷の盆踊りを開催中", day), "profile_description": "地域の町会公式です"} for day in range(1, 6)]
        scores = collect._build_x_account_scores(rows)
        self.assertEqual(scores["accounts"]["missing"]["announce_score"], scores["accounts"]["org"]["announce_score"])

    def test_critique_is_a_post_tag_not_an_account_score(self):
        self.assertTrue(collect._x_is_critique_post("盆踊り文化を続ける意味と課題を考える"))
        self.assertFalse(collect._x_is_critique_post("盆踊りをめぐる外国人の政治論争"))

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
