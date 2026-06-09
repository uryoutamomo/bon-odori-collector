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

    def test_future_schedule_counts_are_tracked(self):
        now = collect.datetime.now(collect.timezone.utc)
        old = now - collect.timedelta(days=45)
        scores = collect._build_x_account_scores([
            {
                "source": "x_whitelist",
                "account": "@future",
                "text": "明日、中央公園で盆踊りを開催予定です。時間と会場のお知らせ。",
                "date": now.isoformat(),
            },
            {
                "source": "x_whitelist",
                "account": "@future",
                "text": "明日、町会の盆踊り練習を実施します。",
                "date": old.isoformat(),
            },
            {
                "source": "x_whitelist",
                "account": "@future",
                "text": "盆踊りに行ってきた。写真も楽しかった。",
                "date": now.isoformat(),
            },
        ], {"account_ranking": {"recent_days": 30}})

        row = scores["accounts"]["future"]

        self.assertEqual(row["valuable_posts"], 3)
        self.assertEqual(row["future_schedule_posts"], 2)
        self.assertEqual(row["recent_valuable_posts"], 2)
        self.assertEqual(row["recent_future_schedule_posts"], 1)


if __name__ == "__main__":
    unittest.main()
