import unittest

import collect


class RankXBonodoriAccountsTest(unittest.TestCase):
    def test_one_high_value_post_stays_candidate(self):
        row = {
            "status": "active",
            "score": 25,
            "posts_seen": 1,
            "valuable_posts": 1,
        }

        self.assertEqual(collect._x_account_usefulness_rank(row), "Candidate")

    def test_repeated_valuable_accounts_can_rank_s(self):
        row = {
            "status": "trusted",
            "score": 7,
            "quality_score": 7,
            "posts_seen": 12,
            "valuable_posts": 8,
            "recent_valuable_posts": 2,
            "value_ratio": 0.667,
            "confidence": "high",
        }

        row["usefulness_rank"] = collect._x_account_usefulness_rank(row)

        self.assertEqual(row["usefulness_rank"], "S")
        self.assertGreaterEqual(collect._x_account_usefulness_score(row), 90)

    def test_muted_usefulness_score_is_zero(self):
        self.assertEqual(collect._x_account_usefulness_score({
            "usefulness_rank": "Muted",
            "quality_score": 10,
        }), 0)

    def test_composite_score_balances_lifetime_and_recent(self):
        self.assertEqual(collect._x_account_composite_score(10, 0, 0), 10)
        self.assertEqual(collect._x_account_composite_score(10, 20, 10), 16)
        self.assertEqual(collect._x_account_composite_score(10, 20, 1), 12)

    def test_role_tags_infer_discovery_and_report_roles(self):
        tags = collect._x_account_role_tags({
            "future_schedule": 2,
            "venue": 1,
            "date_time": 2,
            "experience": 3,
        })

        self.assertEqual(tags, ["発見型", "裏取り型", "参加レポ型", "地域/会場型"])


if __name__ == "__main__":
    unittest.main()
