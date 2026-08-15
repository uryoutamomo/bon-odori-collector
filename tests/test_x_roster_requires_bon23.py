"""2軸名簿への自動編入は、23区の盆踊り投稿が1件以上ある人に限る、という検査。

告知力・記録力は「どう書くか」を測っていて「盆踊りについて書いたか」は見ていない。
2026-08-15 の実測では、その結果として

  - 投稿327件・盆踊り投稿ゼロの @bondbont が名簿にも証拠掘りコホートにもいた
  - 逆に盆踊り投稿12件を持つ @mypl_katsushika が告知力4198位・記録力13594位に沈み、
    名簿の外にいた（同じ立場の人が2,607人）

という逆転が起きていた。順位付けはそのままに、実績ゼロの人だけを落とす。

人の判断（手動名簿・公式台帳・重要情報提供者）は別経路で合流するので、
この条件で落ちても消えない。そこも合わせて検査する。
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import collect


SCORES = {"accounts": {
    # 書き方の点は高いが、盆踊りについては一度も書いていない
    "loud_but_silent": {"handle": "@loud_but_silent", "posts_seen": 327,
                        "announce_score": 99, "record_score": 99, "bon23_count": 0,
                        "distinct_post_days": 30},
    # 点は低いが、盆踊りの投稿を実際に持っている
    "quiet_but_real": {"handle": "@quiet_but_real", "posts_seen": 8,
                       "announce_score": 1, "record_score": 1, "bon23_count": 12,
                       "distinct_post_days": 4},
    # まだ盆踊りの観測がされていない（キー自体が無い）
    "not_measured_yet": {"handle": "@not_measured_yet", "posts_seen": 5,
                         "announce_score": 50, "record_score": 50,
                         "distinct_post_days": 3},
}}


def roster(*, manual=(), cfg=None):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "x_official_source_accounts.json"
        path.write_text(json.dumps({"accounts": []}), encoding="utf-8")
        with patch.object(collect, "X_OFFICIAL_SOURCE_ACCOUNTS_FILE", str(path)), \
             patch.object(collect, "_load_x_account_scores", lambda c=None: SCORES), \
             patch.object(collect, "_load_x_roster_exclusions", lambda: {}), \
             patch.object(collect, "_load_important_informants", lambda: []), \
             patch.object(collect, "_load_collection_roster",
                          lambda: [{"handle": h, "manual_status": "優先"} for h in manual]), \
             patch.object(collect, "_load_notion_member_list", lambda: []):
            accounts = collect.load_whitelist_accounts(
                cfg or {"auto_trusted_roster": {"per_axis_accounts": 5}})
    return {collect._norm_handle(row["handle"]) for row in accounts}


class RosterRequiresBonOdoriRecordTest(unittest.TestCase):
    def test_account_without_any_bon_odori_post_is_not_auto_enrolled(self):
        """点が満点でも、盆踊りを一度も書いていない人は読まない。"""
        self.assertNotIn("loud_but_silent", roster())

    def test_account_with_bon_odori_posts_is_auto_enrolled_even_with_low_scores(self):
        """点が低くても、実際に盆踊りを書いている人は読む。"""
        self.assertIn("quiet_but_real", roster())

    def test_account_never_measured_is_not_treated_as_zero(self):
        """観測して0件だったのと、まだ観測していないのは別。後者は落とさない。

        unknown を減点にしていた過去の誤り（2026-08-11に是正）を繰り返さないため。
        """
        self.assertIn("not_measured_yet", roster())

    def test_hand_picked_account_survives_without_any_bon_odori_post(self):
        """人が名簿に入れた相手は、この条件では消えない（判断を機械が巻き戻さない）。"""
        self.assertIn("loud_but_silent", roster(manual=["@loud_but_silent"]))

    def test_requirement_can_be_switched_off_by_configuration(self):
        """運用で戻せること。閾値の変更が設定でできないと、緊急時に困る。"""
        self.assertIn("loud_but_silent", roster(cfg={
            "auto_trusted_roster": {"per_axis_accounts": 5, "require_bon23_post": False},
        }))


if __name__ == "__main__":
    unittest.main()
